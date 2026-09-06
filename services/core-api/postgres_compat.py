"""Tuple-row connection interface for legacy repositories on either backend."""
from contextlib import contextmanager
import sqlite3

try:
    from psycopg import IntegrityError as PostgresIntegrityError
    integrity_errors = (sqlite3.IntegrityError, PostgresIntegrityError)
except ImportError:
    integrity_errors = (sqlite3.IntegrityError,)


def parameters(sql, values=None):
    """Translate qmark/named parameters without changing quoted SQL literals."""
    if values is None:
        return sql, None
    named = isinstance(values, dict)
    out = []
    quote = None
    comment = None
    i = 0
    while i < len(sql):
        ch = sql[i]
        pair = sql[i:i + 2]
        if comment:
            out.append('%%' if ch == '%' else ch)
            if comment == 'line' and ch == '\n':
                comment = None
            elif comment == 'block' and pair == '*/':
                out.append('/')
                i += 1
                comment = None
        elif quote:
            out.append('%%' if ch == '%' else ch)
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    out.append(quote)
                    i += 1
                else:
                    quote = None
        elif pair in ('--', '/*'):
            out.append(pair)
            comment = 'line' if pair == '--' else 'block'
            i += 1
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == '%':
            out.append('%%')
        elif not named and ch == '?':
            out.append('%s')
        elif named and ch == ':' and pair != '::' and (i == 0 or sql[i - 1] != ':') and i + 1 < len(sql) and (sql[i + 1].isalpha() or sql[i + 1] == '_'):
            end = i + 2
            while end < len(sql) and (sql[end].isalnum() or sql[end] == '_'):
                end += 1
            out.append('%(' + sql[i + 1:end] + ')s')
            i = end - 1
        else:
            out.append(ch)
        i += 1
    return ''.join(out), values


class LegacyConnection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, values=None):
        from psycopg.rows import tuple_row
        query, bound = parameters(sql, values)
        cursor = self.raw.cursor(row_factory=tuple_row)
        cursor.execute(query, bound)
        return cursor


@contextmanager
def connection(sqlite_path):
    import db
    if db._backend == 'pgsql':
        active = db._active_pg()
        if active is not None:
            yield LegacyConnection(active)
        else:
            if db._pool is None:
                raise RuntimeError('PostgreSQL has not been initialized')
            with db._pool.connection() as raw:
                yield LegacyConnection(raw)
    else:
        raw = sqlite3.connect(sqlite_path)
        try:
            with raw:
                yield raw
        finally:
            raw.close()
