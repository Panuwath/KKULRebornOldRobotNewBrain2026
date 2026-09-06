"""Offline SQLite to PostgreSQL copy. Dry-run unless --apply is explicit.

The application and every database writer MUST remain stopped during apply and
cutover. A snapshot alone does not prevent writes being lost after the snapshot.
Never runs robot commands or publishes MQTT messages.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import tempfile


def canonical(value, kind):
    if value is None:
        return None
    if kind in ('json', 'jsonb'):
        if isinstance(value, str):
            value = json.loads(value)
        return ('json', json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False))
    if kind == 'boolean' and value is not None:
        if value not in (0, 1, False, True):
            raise ValueError('Invalid boolean in SQLite source')
        return bool(value)
    if isinstance(value, memoryview):
        return bytes(value)
    # PostgreSQL REAL is IEEE float32, unlike SQLite REAL (float64).
    if kind == 'real' and value is not None:
        import struct
        return struct.unpack('f', struct.pack('f', float(value)))[0]
    return value


def copy_database(source_path, *, apply=False):
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Json, Jsonb
    from psycopg.conninfo import make_conninfo

    source_path = Path(source_path).resolve(strict=True)
    info = make_conninfo(
        host=os.environ['DB_HOST'], port=os.environ.get('DB_PORT', '5432'),
        dbname=os.environ['DB_DATABASE'], user=os.environ['DB_USERNAME'],
        password=os.environ.get('DB_PASSWORD', ''), connect_timeout=5,
    )
    report = {'mode': 'apply' if apply else 'dry-run', 'tables': {}}
    with tempfile.TemporaryDirectory(prefix='zenbo-db-snapshot-') as directory:
        snapshot = sqlite3.connect(str(Path(directory) / 'snapshot.sqlite3'))
        original = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
        try:
            original.backup(snapshot)
        finally:
            original.close()
        try:
            if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('SQLite integrity check failed')
            tables = [r[0] for r in snapshot.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations' ORDER BY name"
            )]
            with psycopg.connect(info) as target:
                target.execute("SET LOCAL lock_timeout = '5s'")
                target.execute("SELECT pg_advisory_xact_lock(72401983)")
                for table in tables:
                    ident = sql.Identifier('public', table)
                    columns = snapshot.execute('PRAGMA table_info("' + table.replace('"', '""') + '")').fetchall()
                    names = [c[1] for c in columns]
                    types = dict(target.execute(
                        'SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=%s AND table_name=%s',
                        ('public', table),
                    ).fetchall())
                    if not types or any(name not in types for name in names):
                        raise RuntimeError(f'Missing PostgreSQL table/columns: {table}; initialize application migrations first')
                    if apply:
                        target.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(ident))
                    source_rows = snapshot.execute('SELECT ' + ','.join('"' + n.replace('"', '""') + '"' for n in names) + ' FROM "' + table.replace('"', '""') + '"').fetchall()
                    expected = Counter(tuple(canonical(v, types[n]) for n, v in zip(names, row)) for row in source_rows)
                    select = sql.SQL('SELECT {} FROM {}').format(sql.SQL(',').join(map(sql.Identifier, names)), ident)
                    actual = Counter(tuple(canonical(v, types[n]) for n, v in zip(names, row)) for row in target.execute(select))
                    if actual and actual != expected:
                        raise RuntimeError(f'Destination contains different data: {table}; nothing will be overwritten')
                    status = 'already-identical' if actual == expected else 'pending-copy'
                    if apply and status == 'pending-copy':
                        insert = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                            ident, sql.SQL(',').join(map(sql.Identifier, names)),
                            sql.SQL(',').join(sql.Placeholder() for _ in names),
                        )
                        def adapt(row):
                            result = []
                            for name, value in zip(names, row):
                                kind = types[name]
                                if value is not None and kind in ('json', 'jsonb'):
                                    parsed = json.loads(value) if isinstance(value, str) else value
                                    value = Jsonb(parsed) if kind == 'jsonb' else Json(parsed)
                                elif kind == 'boolean':
                                    value = canonical(value, kind)
                                result.append(value)
                            return result
                        with target.cursor() as cursor:
                            cursor.executemany(insert, map(adapt, source_rows))
                        copied = Counter(tuple(canonical(v, types[n]) for n, v in zip(names, row)) for row in target.execute(select))
                        if copied != expected:
                            raise RuntimeError(f'Post-copy comparison failed: {table}')
                        status = 'copied-and-verified'
                    if apply:
                        for name in names:
                            sequence = target.execute('SELECT pg_get_serial_sequence(%s, %s)', ('public."' + table.replace('"', '""') + '"', name)).fetchone()[0]
                            if sequence:
                                maximum = target.execute(sql.SQL('SELECT MAX({}) FROM {}').format(sql.Identifier(name), ident)).fetchone()[0]
                                if maximum is not None:
                                    # Never rewind a sequence on retry; setval is not transactional.
                                    current = target.execute(sql.SQL('SELECT last_value FROM {}').format(sql.Identifier(*sequence.split('.')))).fetchone()[0]
                                    target.execute('SELECT setval(%s::regclass, %s, true)', (sequence, max(current, maximum)))
                    report['tables'][table] = {'rows': len(source_rows), 'status': status}
                if not apply:
                    target.rollback()
        finally:
            snapshot.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--writers-stopped', action='store_true')
    args = parser.parse_args()
    if args.apply and not args.writers_stopped:
        parser.error('--apply requires --writers-stopped; stop all source and destination writers first')
    print(json.dumps(copy_database(args.source, apply=args.apply), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
