# PostgreSQL backup and isolated restore

Scope: the Zenbo Core PostgreSQL database only. No robot commands, APK changes,
broker persistence, n8n data, or production restore are performed by these jobs.

## Deployment

Install `scripts/postgres-backup.py` and `scripts/postgres_snapshot.py` under
`/var/docker/zenbo-liff/scripts`. The host requires Python 3 and Docker.

Create `.postgres-backup.json` (mode 600) with `postgres_image` (the installed
PostgreSQL 17 image ID), `core_image` (`zenbo-liff-zenbo-core-api:latest`),
`network` (`lib_default`), and `keep` (14).

Create `.postgres-backup.env` (mode 600) with standard libpq variables:
`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`. Never commit this file.
The `zenbo_backup` login needs CONNECT, schema USAGE, and SELECT on tables and
sequences, including default grants for future migrations. It has no write role.

## Commands

```sh
python3 /var/docker/zenbo-liff/scripts/postgres-backup.py backup
python3 /var/docker/zenbo-liff/scripts/postgres-backup.py restore-drill
```

Backup uses an exported repeatable-read snapshot shared between a read-only
row-hash manifest and `pg_dump`. Partial archives are not published. The archive
TOC and SHA-256 are checked before retaining the latest 14 completed sets.

Restore verifies the archive checksum, restores to a disposable PostgreSQL
container with `--network none` and no published port, and compares every public
table's columns, row count, and content hash against that same source snapshot.
The inspector joins only the disposable container's network namespace.
Temporary PostgreSQL data is held in a 1 GiB tmpfs; larger databases require
an explicit capacity adjustment. Production is not a restore target.

## Schedule and evidence

Host time zone: Asia/Bangkok. Backup daily at 02:30; restore drill Sunday at
03:30. Preserve unrelated crontab entries. Both jobs share a nonblocking lock.

Evidence is under `backups/postgres/`: paired `.dump`/`.json` files,
`backup-status.json`, `restore-drill-status.json`, and `cron.log`.
Check `ok` and `finished_at`; a stale success is not a current success.

## Recovery boundary

Archives contain sensitive application data and must remain mode 600 in a
restricted directory. These are same-host backups, not protection from host or
disk loss. Encrypted off-host storage, alert routing, and PITR/WAL archiving are
separate follow-up work. Current scheduling targets an RPO of up to 24 hours
when successful; no production RTO is claimed from a small isolated drill.

Before a real recovery, stop writers, preserve the current PostgreSQL database,
restore into a new database, validate content and application access, and then
change the application connection. Never overwrite the live database or switch
to the pre-migration SQLite snapshot without reconciling newer writes.
Role passwords, ownership grants, and deployment secrets require separate
protected recovery records; these dumps deliberately omit owners and ACLs.
