#!/usr/bin/env python3
"""Run opt-in PG tests in a fresh UTF-8 loopback-only cluster, then stop it."""
import argparse
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, help="Directory containing initdb and pg_ctl")
    args = parser.parse_args()
    binary = args.pg_bin
    if binary is None:
        found = shutil.which("initdb")
        if found:
            binary = Path(found).parent
    if binary is None or not all((binary / name).is_file() for name in ("initdb", "pg_ctl")):
        parser.error("Pass --pg-bin for the locally installed PostgreSQL binaries")
    if any(importlib.util.find_spec(name) is None for name in ("pytest", "psycopg", "psycopg_pool")):
        parser.error("Install pytest and psycopg[binary,pool] in the test Python environment")

    root = Path(tempfile.mkdtemp(prefix="zenbo-postgres-test-"))
    data = root / "data"
    socket_dir = root / "socket"
    socket_dir.mkdir()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    try:
        subprocess.run([str(binary / "initdb"), "-D", str(data), "-U", "zenbo_test",
                        "--auth=trust", "--no-locale", "--encoding=UTF8"],
                       check=True, stdout=subprocess.DEVNULL)
        options = shlex.join(["-h", "127.0.0.1", "-p", str(port), "-k", str(socket_dir)])
        subprocess.run([str(binary / "pg_ctl"), "-D", str(data), "-l", str(root / "postgres.log"),
                        "-o", options, "-w", "start"], check=True)
        env = {**os.environ, "ZENBO_TEST_POSTGRES": "1", "DB_HOST": "127.0.0.1",
               "DB_PORT": str(port), "DB_USERNAME": "zenbo_test", "DB_PASSWORD": "",
               "DB_CONNECTION": "sqlite", "COMMAND_HISTORY_DB": ":memory:"}
        result = subprocess.run([sys.executable, "-m", "pytest", "-q",
                                 "services/core-api/test_postgres_migration.py"],
                                cwd=Path(__file__).resolve().parents[1], env=env)
        return result.returncode
    finally:
        # Never remove a cluster that failed to stop; retain it for diagnosis.
        if (data / "postmaster.pid").exists():
            subprocess.run([str(binary / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
                           check=True)
        shutil.rmtree(root)


if __name__ == "__main__":
    raise SystemExit(main())
