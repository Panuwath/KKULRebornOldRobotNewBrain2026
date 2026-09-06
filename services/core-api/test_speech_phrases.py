"""Contract tests for the speech-phrase history module."""
import asyncio
import os
import tempfile
from typing import Generator

import pytest

import db
import speech_phrases


@pytest.fixture
def clean_db() -> Generator[None, None, None]:
    """Route db.py to a temporary SQLite file for each test."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(temp_dir.name, "speech_phrases.sqlite3")
    os.environ["DB_CONNECTION"] = "sqlite"
    os.environ["COMMAND_HISTORY_DB"] = db_path

    if db._sqlite is not None:
        db._sqlite.close()
    db._sqlite = None
    db._pool = None
    db._backend = "sqlite"

    db.init()
    yield
    if db._sqlite is not None:
        db._sqlite.close()
        db._sqlite = None
    temp_dir.cleanup()


def test_normalize_text():
    assert speech_phrases.normalize_text("  Hello   WORLD  ") == "hello world"
    assert speech_phrases.normalize_text("สวัสดี   ครับ") == "สวัสดี ครับ"


def test_create_phrase(clean_db):
    phrase = speech_phrases.upsert_phrase(
        user_sub="user-a",
        text="  Hello   Booky  ",
        robot_slug="booky-1",
        voice_profile="male_child",
        face="HAPPY",
        scope="personal",
    )
    assert phrase.id > 0
    assert phrase.user_sub == "user-a"
    assert phrase.text == "  Hello   Booky  "
    assert phrase.text_norm == "hello booky"
    assert phrase.robot_slug == "booky-1"
    assert phrase.voice_profile == "male_child"
    assert phrase.face == "HAPPY"
    assert phrase.use_count == 1
    assert phrase.pinned is False
    assert phrase.scope == "personal"
    assert phrase.created_at_ms > 0
    assert phrase.last_used_at_ms > 0


def test_upsert_increments_use_count(clean_db):
    first = speech_phrases.upsert_phrase("user-a", "Hello", None, None, None, "personal")
    assert first.use_count == 1

    second = speech_phrases.upsert_phrase("user-a", "  hello  ", None, None, None, "personal")
    assert second.id == first.id
    assert second.use_count == 2
    assert second.text_norm == "hello"

    phrases = speech_phrases.list_phrases("user-a", sort="frequent")
    assert len(phrases) == 1
    assert phrases[0].use_count == 2


def test_list_filters_and_sorts(clean_db):
    speech_phrases.upsert_phrase("user-a", "Apple pie", None, None, None, "personal")
    speech_phrases.upsert_phrase("user-a", "Banana", None, None, None, "personal")
    speech_phrases.upsert_phrase("user-a", "Banana", None, None, None, "personal")

    filtered = speech_phrases.list_phrases("user-a", q="ban")
    assert len(filtered) == 1
    assert filtered[0].text == "Banana"

    recent = speech_phrases.list_phrases("user-a", sort="recent")
    assert recent[0].text == "Banana"

    frequent = speech_phrases.list_phrases("user-a", sort="frequent")
    assert frequent[0].text == "Banana"


def test_list_includes_shared_phrases(clean_db):
    own = speech_phrases.upsert_phrase("user-a", "Own phrase", None, None, None, "personal")
    shared = speech_phrases.upsert_phrase("user-b", "Shared phrase", None, None, None, "shared")

    user_a_phrases = speech_phrases.list_phrases("user-a")
    assert len(user_a_phrases) == 2
    ids = {p.id for p in user_a_phrases}
    assert own.id in ids
    assert shared.id in ids

    user_b_phrases = speech_phrases.list_phrases("user-b")
    # The shared phrase owned by user-b appears once even though it matches both filters.
    assert len(user_b_phrases) == 1

    scoped = speech_phrases.list_phrases("user-a", scope="shared")
    assert len(scoped) == 1
    assert scoped[0].id == shared.id


def test_update_phrase(clean_db):
    phrase = speech_phrases.upsert_phrase("user-a", "Old text", None, None, None, "personal")
    updated = speech_phrases.update_phrase(
        phrase.id,
        "user-a",
        False,
        speech_phrases.SpeechPhraseUpdate(text="New text", pinned=True, scope="shared"),
    )
    assert updated.text == "New text"
    assert updated.text_norm == "new text"
    assert updated.pinned is True
    assert updated.scope == "shared"


def test_soft_delete_phrase(clean_db):
    phrase = speech_phrases.upsert_phrase("user-a", "Delete me", None, None, None, "personal")
    assert speech_phrases.soft_delete_phrase(phrase.id, "user-a", False) is True
    assert speech_phrases.get_phrase(phrase.id, "user-a", False) is None
    assert speech_phrases.list_phrases("user-a") == []


def test_unauthorized_access(clean_db):
    phrase = speech_phrases.upsert_phrase("user-a", "Secret", None, None, None, "personal")

    assert speech_phrases.get_phrase(phrase.id, "user-b", False) is None
    assert speech_phrases.update_phrase(
        phrase.id,
        "user-b",
        False,
        speech_phrases.SpeechPhraseUpdate(text="Hacked"),
    ) is None
    assert speech_phrases.soft_delete_phrase(phrase.id, "user-b", False) is False


def test_admin_can_share_and_access_any_phrase(clean_db):
    user_phrase = speech_phrases.upsert_phrase("user-a", "User phrase", None, None, None, "personal")
    admin_view = speech_phrases.get_phrase(user_phrase.id, "admin-1", admin=True)
    assert admin_view is not None
    assert admin_view.id == user_phrase.id

    shared = speech_phrases.update_phrase(
        user_phrase.id,
        "admin-1",
        True,
        speech_phrases.SpeechPhraseUpdate(scope="shared"),
    )
    assert shared.scope == "shared"

    owner_view = speech_phrases.get_phrase(user_phrase.id, "user-a", False)
    assert owner_view.scope == "shared"


def test_record_from_interact(clean_db):
    asyncio.run(
        speech_phrases.record_from_interact(
            text="Welcome everyone",
            source="liff",
            user_sub="line-user-1",
            robot_slug="booky-1",
            voice_profile="male_child",
            face="HAPPY",
            record_phrase=True,
        )
    )
    phrases = speech_phrases.list_phrases("line-user-1")
    assert len(phrases) == 1
    assert phrases[0].text == "Welcome everyone"
    assert phrases[0].robot_slug == "booky-1"
    assert phrases[0].voice_profile == "male_child"
    assert phrases[0].face == "HAPPY"

    # record_phrase=False should skip
    asyncio.run(
        speech_phrases.record_from_interact(
            text="Skip me",
            source="liff",
            user_sub="line-user-1",
            robot_slug="booky-1",
            voice_profile=None,
            face=None,
            record_phrase=False,
        )
    )
    assert len(speech_phrases.list_phrases("line-user-1")) == 1

    # Non-web/LIFF/LINE source should skip
    asyncio.run(
        speech_phrases.record_from_interact(
            text="API phrase",
            source="api",
            user_sub="line-user-1",
            robot_slug=None,
            voice_profile=None,
            face=None,
            record_phrase=True,
        )
    )
    assert len(speech_phrases.list_phrases("line-user-1")) == 1

    # Empty text should skip
    asyncio.run(
        speech_phrases.record_from_interact(
            text="   ",
            source="web",
            user_sub="line-user-1",
            robot_slug=None,
            voice_profile=None,
            face=None,
            record_phrase=True,
        )
    )
    assert len(speech_phrases.list_phrases("line-user-1")) == 1
