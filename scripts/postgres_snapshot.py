"""Read-only consistent snapshot manifest, executed in the Core Python image."""
import datetime
import decimal
import hashlib
import json
import os
import sys

import psycopg
from psycopg import sql


def encode(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {'bytes_hex': bytes(value).hex()}
    if isinstance(value, decimal.Decimal):
        return {'decimal': str(value)}
    if isinstance(value, (datetime.date, datetime.time, datetime.datetime)):
        return {'iso': value.isoformat()}
    return {'type': type(value).__name__, 'value': str(value)}


def main():
    with psycopg.connect(connect_timeout=5) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        connection.execute("SET LOCAL TIME ZONE 'UTC'")
        connection.execute("SET LOCAL statement_timeout = '120s'")
        connection.execute("SET LOCAL lock_timeout = '5s'")
        connection.execute("SET LOCAL idle_in_transaction_session_timeout = '180s'")
        snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
        tables = {}
        for (name,) in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall():
            with connection.cursor(name='manifest_rows') as cursor:
                cursor.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier('public', name)))
                # Named cursors expose description after the first fetch.
                rows = cursor.fetchmany(1000)
                columns = [column.name for column in cursor.description]
                hashes = []
                while rows:
                    for row in rows:
                        encoded = json.dumps(row, default=encode, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
                        hashes.append(hashlib.sha256(encoded).digest())
                    rows = cursor.fetchmany(1000)
            digest = hashlib.sha256()
            for row_hash in sorted(hashes):
                digest.update(row_hash)
            tables[name] = {'columns': columns, 'rows': len(hashes), 'sha256': digest.hexdigest()}
        print(json.dumps({'snapshot': snapshot, 'tables': tables}), flush=True)
        if '--hold' in sys.argv:
            if not sys.stdin.readline():
                raise RuntimeError('Snapshot owner disappeared before backup completed')


if __name__ == '__main__':
    main()
