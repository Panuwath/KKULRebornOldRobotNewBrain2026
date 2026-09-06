"""Independent parity/rollback harness for the PostgreSQL cutover.

Run directly against either SQLite or PostgreSQL without touching the running
Core web server.  On PostgreSQL it proves the same adapter calls return the same
shapes as SQLite before a live cutover is authorized.
"""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("DB_CONNECTION", "sqlite")
os.environ.setdefault("COMMAND_HISTORY_DB", ":memory:")

import db
import command_history_repository


def _bootstrap() -> db:
    db.init()
    return db


def _assert_unicode_and_null() -> None:
    hid = command_history_repository.append_command(
        robot_slug="parity-robot",
        source="parity",
        status="TEST",
        payload={"thai": "ทดสอบ", "null_key": None, "nested": {"value": 1}},
    )
    row = db.fetchone(
        "SELECT payload_json FROM command_history WHERE id = :id", {"id": hid}
    )
    payload = json.loads(row["payload_json"])
    assert payload["thai"] == "ทดสอบ"
    assert payload["null_key"] is None
    assert payload["nested"] == {"value": 1}


def _assert_pagination() -> None:
    for i in range(5):
        command_history_repository.append_command(
            robot_slug="parity-robot",
            source="parity",
            status="TEST",
            payload={"seq": i},
        )
    result = command_history_repository.list_commands("parity-robot", page=1, page_size=2)
    assert result["total"] >= 5
    assert len(result["items"]) == 2
    assert result["has_next"] is True
    assert all(isinstance(item["payload"], dict) for item in result["items"])


def _assert_transaction_rollback() -> None:
    try:
        with db.transaction():
            db.execute(
                "INSERT INTO speech_phrases (text, text_norm) VALUES (:text, :norm)",
                {"text": "parity-rollback", "norm": "parity-rollback"},
            )
            raise RuntimeError("intentional rollback")
    except RuntimeError:
        pass
    row = db.fetchone(
        "SELECT id FROM speech_phrases WHERE text_norm = :norm",
        {"norm": "parity-rollback"},
    )
    assert row is None


def _assert_health() -> None:
    health = db.health_check()
    assert health["ok"] is True


def run() -> bool:
    _bootstrap()
    _assert_unicode_and_null()
    _assert_pagination()
    _assert_transaction_rollback()
    _assert_health()
    health = db.health_check()
    print(f"parity check passed on {health['backend']} in {health['latency_ms']} ms")
    return True


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
