#!/usr/bin/env python3
"""Host-side PostgreSQL backup and network-isolated restore drill.

Uses Docker and Python standard library only. Never imports the robot service.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def run(args, **kwargs):
    return subprocess.run(args, check=True, timeout=180, **kwargs)


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspector(root, config):
    return ['--mount', 'type=bind,src=' + str(root / 'scripts/postgres_snapshot.py') + ',dst=/snapshot.py,readonly', config['core_image'], 'python', '/snapshot.py']


def backup(root, directory, config):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    stem = 'zenbo-' + stamp + '-' + uuid.uuid4().hex[:8]
    temporary = directory / (stem + '.partial')
    archive = directory / (stem + '.dump')
    envfile = str(root / '.postgres-backup.env')
    name = 'zenbo-snapshot-' + uuid.uuid4().hex[:12]
    command = ['docker', 'run', '--rm', '-i', '--name', name, '--network', config['network'], '--env-file', envfile] + inspector(root, config) + ['--hold']
    source = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = source.stdout.readline()
        if not line:
            raise RuntimeError('Read-only source snapshot could not be opened')
        manifest = json.loads(line)
        with temporary.open('xb') as output:
            run(['docker', 'run', '--rm', '--network', config['network'], '--env-file', envfile,
                 config['postgres_image'], 'pg_dump', '--format=custom', '--no-owner', '--no-acl',
                 '--lock-wait-timeout=5s', '--snapshot=' + manifest['snapshot']], stdout=output)
            output.flush()
            os.fsync(output.fileno())
        source.communicate(input='complete\n', timeout=15)
        if source.returncode:
            raise RuntimeError('Snapshot transaction ended unexpectedly')
        # Validate archive structure before publishing it or pruning old backups.
        with temporary.open('rb') as stream:
            run(['docker', 'run', '--rm', '-i', '--network', 'none', config['postgres_image'], 'pg_restore', '--list'], stdin=stream, stdout=subprocess.DEVNULL)
        manifest.pop('snapshot')
        manifest.update({'archive': archive.name, 'sha256': checksum(temporary), 'created_at_utc': stamp, 'format': 1})
        os.replace(temporary, archive)
        atomic_json(directory / (stem + '.json'), manifest)
        complete = sorted(directory.glob('zenbo-*.json'))
        for old in complete[:-config.get('keep', 14)]:
            owned_archive = old.with_suffix('.dump')
            if owned_archive.is_file() and not owned_archive.is_symlink():
                owned_archive.unlink()
                old.unlink()
        return {'archive': archive.name, 'tables': len(manifest['tables']), 'rows': sum(t['rows'] for t in manifest['tables'].values()), 'sha256': manifest['sha256']}
    finally:
        if source.poll() is None:
            source.kill()
            source.wait(timeout=10)
        run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if container_exists(name) else None
        temporary.unlink(missing_ok=True)


def container_exists(name):
    result = subprocess.run(['docker', 'container', 'inspect', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    return result.returncode == 0


def restore(root, directory, config):
    manifests = sorted(directory.glob('zenbo-*.json'))
    if not manifests:
        raise RuntimeError('No completed backup is available')
    manifest_path = manifests[-1]
    manifest = json.loads(manifest_path.read_text())
    archive = manifest_path.with_suffix('.dump')
    if archive.name != manifest['archive'] or checksum(archive) != manifest['sha256']:
        raise RuntimeError('Backup checksum mismatch; refusing restore')
    name = 'zenbo-restore-' + uuid.uuid4().hex[:12]
    try:
        run(['docker', 'run', '--rm', '-d', '--name', name, '--network', 'none', '--memory', '2g',
             '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,size=1g',
             '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', '-e', 'POSTGRES_DB=zenbo_restore',
             config['postgres_image']], stdout=subprocess.DEVNULL)
        for attempt in range(30):
            ready = subprocess.run(['docker', 'exec', name, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', '-d', 'zenbo_restore'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Isolated PostgreSQL did not become ready')
        with archive.open('rb') as stream:
            run(['docker', 'exec', '-i', name, 'pg_restore', '-h', '127.0.0.1', '-U', 'postgres', '-d', 'zenbo_restore', '--no-owner', '--no-privileges', '--exit-on-error', '--single-transaction'], stdin=stream)
        command = ['docker', 'run', '--rm', '--network', 'container:' + name,
                   '-e', 'PGHOST=127.0.0.1', '-e', 'PGPORT=5432', '-e', 'PGUSER=postgres', '-e', 'PGDATABASE=zenbo_restore'] + inspector(root, config)
        restored = json.loads(run(command, capture_output=True, text=True).stdout)
        if restored['tables'] != manifest['tables']:
            raise RuntimeError('Restored table/column/count/content hashes differ from the source snapshot')
        return {'archive': archive.name, 'tables_verified': len(restored['tables']), 'rows_verified': sum(t['rows'] for t in restored['tables'].values()), 'network': 'none'}
    finally:
        if container_exists(name):
            run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore-drill'])
    parser.add_argument('--root', default='/var/docker/zenbo-liff')
    args = parser.parse_args()
    os.umask(0o077)
    root = Path(args.root).resolve()
    directory = root / 'backups/postgres'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / '.job.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another PostgreSQL backup/restore job is active; skipped')
            return
        status = {'action': args.action, 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        try:
            config = json.loads((root / '.postgres-backup.json').read_text())
            if config.get('keep', 14) < 1:
                raise ValueError('Retention must keep at least one complete backup')
            result = backup(root, directory, config) if args.action == 'backup' else restore(root, directory, config)
            status.update({'ok': True, 'result': result})
        except Exception as error:
            status.update({'ok': False, 'error_type': type(error).__name__, 'error': str(error)})
        status['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        atomic_json(directory / (args.action + '-status.json'), status)
        print(json.dumps(status, sort_keys=True))
        if not status['ok']:
            sys.exit(1)


if __name__ == '__main__':
    main()
