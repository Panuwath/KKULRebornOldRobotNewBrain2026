"""Database adapter for new Zenbo Core API tables."""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence, Tuple, Union

Params = Optional[Union[Mapping[str, Any], Sequence[Any]]]
_backend = "sqlite"
_sqlite: Optional[sqlite3.Connection] = None
_pool: Any = None
_lock = threading.RLock()
_local = threading.local()
_parameter = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _postgres_sql(sql: str) -> str:
    """Rewrite named parameters, excluding quoted text and double-colon casts."""
    output, index, quote = [], 0, None
    while index < len(sql):
        char = sql[index]
        if quote:
            output.append(char)
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == ":" and (index == 0 or sql[index - 1] != ":"):
            match = _parameter.match(sql, index + 1)
            if match and (match.end() == len(sql) or sql[match.end()] != ":"):
                output.append(f"%({match.group(0)})s")
                index = match.end()
                continue
        output.append(char)
        index += 1
    return "".join(output)


def init() -> None:
    """Initialize the configured backend and ensure its new tables exist."""
    global _backend, _sqlite, _pool
    backend = os.getenv("DB_CONNECTION", "sqlite").strip().lower() or "sqlite"
    if backend not in {"sqlite", "pgsql"}:
        raise ValueError("DB_CONNECTION must be 'sqlite' or 'pgsql'")
    _backend = backend
    if backend == "pgsql":
        if _sqlite is not None:
            _sqlite.close()
            _sqlite = None
        if _pool is None:
            from psycopg.conninfo import make_conninfo
            from psycopg_pool import ConnectionPool
            dsn = make_conninfo(
                host=os.getenv("DB_HOST", "localhost"),
                port=os.getenv("DB_PORT", "5432"),
                dbname=os.getenv("DB_DATABASE", "zenbo"),
                user=os.getenv("DB_USERNAME", ""),
                password=os.getenv("DB_PASSWORD", ""),
                connect_timeout=5,
            )
            _pool = ConnectionPool(conninfo=dsn, open=True, timeout=5)
            try:
                _pool.wait(timeout=5)
            except Exception:
                _pool.close()
                _pool = None
                raise
        _run_postgres_migrations()
    else:
        if _pool is not None:
            _pool.close()
            _pool = None
        if _sqlite is None:
            path = os.getenv("COMMAND_HISTORY_DB", "/app/data/command_history.sqlite3")
            if path != ":memory:":
                Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            _sqlite = sqlite3.connect(path, check_same_thread=False)
            _sqlite.row_factory = sqlite3.Row
            _sqlite.execute("PRAGMA foreign_keys = ON")
        ensure_sqlite_tables()


def _sqlite_connection() -> sqlite3.Connection:
    if _sqlite is None:
        raise RuntimeError("Database is not initialized; call db.init() first")
    return _sqlite


def ensure_sqlite_tables() -> None:
    """Create SQLite equivalents of all PostgreSQL-managed tables."""
    ddl = """
    CREATE TABLE IF NOT EXISTS web_users (sub TEXT PRIMARY KEY, email TEXT, display_name TEXT, role TEXT NOT NULL DEFAULT 'viewer', provider TEXT NOT NULL DEFAULT 'libsso', created_at_ms INTEGER, last_login_ms INTEGER, disabled INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS web_auth_sessions (token_hash TEXT PRIMARY KEY, sub TEXT, username TEXT, display_name TEXT, role TEXT, provider TEXT, created_at_ms INTEGER, expires_at_ms INTEGER);
    CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value_encrypted BLOB, updated_by TEXT, updated_at_ms INTEGER);
    CREATE TABLE IF NOT EXISTS command_history (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at_ms INTEGER NOT NULL, robot_slug TEXT, source TEXT NOT NULL, status TEXT NOT NULL, accepted_latency_ms INTEGER, payload_json TEXT NOT NULL, user_id TEXT, display_name TEXT);
    CREATE INDEX IF NOT EXISTS command_history_created_idx ON command_history(created_at_ms DESC);
    CREATE INDEX IF NOT EXISTS command_history_robot_idx ON command_history(robot_slug, created_at_ms DESC);
    CREATE TABLE IF NOT EXISTS speech_phrases (id INTEGER PRIMARY KEY AUTOINCREMENT, user_sub TEXT, robot_slug TEXT, text TEXT NOT NULL, text_norm TEXT, voice_profile TEXT, face TEXT, use_count INTEGER DEFAULT 1, pinned INTEGER DEFAULT 0, scope TEXT DEFAULT 'personal', created_at_ms INTEGER, last_used_at_ms INTEGER, deleted_at_ms INTEGER);
    CREATE INDEX IF NOT EXISTS idx_speech_phrases_user_text ON speech_phrases(user_sub, text_norm);
    CREATE INDEX IF NOT EXISTS idx_speech_phrases_last_used ON speech_phrases(last_used_at_ms);
    CREATE TABLE IF NOT EXISTS camera_sessions (session_id TEXT PRIMARY KEY, robot_slug TEXT, username TEXT, started_at_ms INTEGER, ended_at_ms INTEGER, state TEXT);
    CREATE INDEX IF NOT EXISTS idx_camera_sessions_robot_started ON camera_sessions(robot_slug, started_at_ms);
    CREATE TABLE IF NOT EXISTS apk_releases (version_code INTEGER PRIMARY KEY, version_name TEXT, sha256 TEXT, url TEXT, channel TEXT, notes TEXT, created_at_ms INTEGER);
    CREATE TABLE IF NOT EXISTS robot_update_events (id INTEGER PRIMARY KEY AUTOINCREMENT, robot_slug TEXT, version_code INTEGER, state TEXT, detail_json TEXT, created_at_ms INTEGER);
    CREATE TABLE IF NOT EXISTS compiler_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_sub TEXT, robot_slug TEXT, input_text TEXT, provider TEXT, model TEXT, intents_json TEXT, confidence REAL, latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, fallback_used INTEGER, dispatched INTEGER, created_at_ms INTEGER);
    CREATE TABLE IF NOT EXISTS field_permits (id INTEGER PRIMARY KEY AUTOINCREMENT, permit_id TEXT UNIQUE NOT NULL, robot_slug TEXT NOT NULL, operator_sub TEXT NOT NULL, level_max INTEGER NOT NULL DEFAULT 3, issued_at_ms INTEGER NOT NULL, expires_at_ms INTEGER NOT NULL, revoked_at_ms INTEGER, attestation_json TEXT);
    CREATE INDEX IF NOT EXISTS idx_field_permits_robot ON field_permits(robot_slug, expires_at_ms);
    """
    with _lock:
        connection = _sqlite_connection()
        connection.executescript(ddl)
        from field_rollout import SCHEMA
        connection.executescript(SCHEMA)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(web_users)")}
        if "provider" not in columns:
            connection.execute("ALTER TABLE web_users ADD COLUMN provider TEXT NOT NULL DEFAULT 'libsso'")
        connection.commit()


def _run_postgres_migrations() -> None:
    with _pool.connection() as connection, connection.transaction():
        connection.execute("SET LOCAL lock_timeout = '5s'")
        connection.execute("SELECT pg_advisory_xact_lock(72401983)")
        for migration in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
            with connection.transaction():
                if migration.name != "0000_schema_migrations.sql":
                    applied = connection.execute(
                        "SELECT 1 FROM schema_migrations WHERE filename = %s", (migration.name,)
                    ).fetchone()
                    if applied:
                        continue
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations (filename, applied_at_ms) VALUES (%s, %s) ON CONFLICT (filename) DO NOTHING",
                    (migration.name, int(time.time() * 1000)),
                )


def _active_pg() -> Any:
    return getattr(_local, "postgres_connection", None)


def _pg_params(sql: str, params: Params) -> Tuple[str, Any]:
    """Return (sql, values) ready for psycopg."""
    if params is None:
        return sql, None
    if isinstance(params, (list, tuple)):
        if "?" in sql:
            return sql.replace("?", "%s"), list(params)
        return sql, list(params)
    return _postgres_sql(sql), params


def execute(sql: str, params: Params = None, returning_id: bool = False) -> Optional[int]:
    """Execute a parameterized statement and optionally return a generated id."""
    values = params or {}
    if _backend == "pgsql":
        statement, pg_values = _pg_params(sql, params)
        if returning_id and " returning " not in statement.lower():
            statement = statement.rstrip().rstrip(";") + " RETURNING id"
        active = _active_pg()
        if active is not None:
            cursor = active.execute(statement, pg_values)
            row = cursor.fetchone() if returning_id else None
        else:
            with _pool.connection() as connection:
                cursor = connection.execute(statement, pg_values)
                row = cursor.fetchone() if returning_id else None
        return int(row[0]) if row else None
    with _lock:
        cursor = _sqlite_connection().execute(sql, values)
        if not getattr(_local, "sqlite_transaction", False):
            _sqlite_connection().commit()
        return int(cursor.lastrowid) if returning_id else None


def _fetch(sql: str, params: Params, one: bool) -> Any:
    values = params or {}
    if _backend == "pgsql":
        from psycopg.rows import dict_row
        statement, pg_values = _pg_params(sql, params)
        active = _active_pg()
        if active is not None:
            cursor = active.cursor(row_factory=dict_row)
            cursor.execute(statement, pg_values)
            rows = cursor.fetchone() if one else cursor.fetchall()
        else:
            with _pool.connection() as connection:
                cursor = connection.cursor(row_factory=dict_row)
                cursor.execute(statement, pg_values)
                rows = cursor.fetchone() if one else cursor.fetchall()
    else:
        with _lock:
            cursor = _sqlite_connection().execute(sql, values)
            rows = cursor.fetchone() if one else cursor.fetchall()
    if one:
        return dict(rows) if rows is not None else None
    return [dict(row) for row in rows]


def fetchone(sql: str, params: Params = None) -> Optional[Dict[str, Any]]:
    """Fetch one row as a dictionary."""
    return _fetch(sql, params, True)


def fetchall(sql: str, params: Params = None) -> list[Dict[str, Any]]:
    """Fetch all rows as dictionaries."""
    return _fetch(sql, params, False)


@contextmanager
def transaction() -> Iterator[None]:
    """Run adapter calls atomically and roll back exceptions."""
    if _backend == "pgsql":
        if _active_pg() is not None:
            raise RuntimeError("Nested transactions are not supported")
        with _pool.connection() as connection:
            _local.postgres_connection = connection
            try:
                with connection.transaction():
                    yield
            finally:
                del _local.postgres_connection
        return
    if getattr(_local, "sqlite_transaction", False):
        raise RuntimeError("Nested transactions are not supported")
    with _lock:
        connection = _sqlite_connection()
        connection.execute("BEGIN")
        _local.sqlite_transaction = True
        try:
            yield
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            _local.sqlite_transaction = False


def health_check() -> Dict[str, Any]:
    """Return backend availability and query latency."""
    started = time.perf_counter()
    try:
        ok = fetchone("SELECT 1 AS healthy") == {"healthy": 1}
    except Exception:
        ok = False
    return {"backend": _backend, "ok": ok, "latency_ms": round((time.perf_counter() - started) * 1000, 3)}


def close() -> None:
    """Release connections during application shutdown or isolated tests."""
    global _pool, _sqlite
    if _pool is not None:
        _pool.close()
        _pool = None
    if _sqlite is not None:
        _sqlite.close()
        _sqlite = None


# One backend for modern and legacy repositories.
from postgres_compat import connection, integrity_errors, parameters as _pg_params
