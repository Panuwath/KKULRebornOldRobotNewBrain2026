"""Speech-phrase history for reusable Zenbo text prompts."""
import re
import time
from typing import List, Optional

from pydantic import BaseModel, Field

import db

_SELECT_COLUMNS = (
    "id, user_sub, robot_slug, text, text_norm, voice_profile, face, "
    "use_count, pinned, scope, created_at_ms, last_used_at_ms"
)


class SpeechPhraseCreate(BaseModel):
    text: str = Field(..., max_length=1000)
    robot_slug: Optional[str] = Field(default=None)
    voice_profile: Optional[str] = Field(default=None)
    face: Optional[str] = Field(default=None)
    pinned: bool = Field(default=False)
    scope: str = Field(default="personal")


class SpeechPhraseUpdate(BaseModel):
    text: Optional[str] = Field(default=None, max_length=1000)
    pinned: Optional[bool] = Field(default=None)
    scope: Optional[str] = Field(default=None)


class SpeechPhraseOut(BaseModel):
    id: int
    user_sub: str
    robot_slug: Optional[str]
    text: str
    text_norm: str
    voice_profile: Optional[str]
    face: Optional[str]
    use_count: int
    pinned: bool
    scope: str
    created_at_ms: int
    last_used_at_ms: int


def init_phrases_table() -> None:
    """Ensure the speech_phrases table and indexes exist via db.py."""
    db.init()
    if db._backend == "pgsql":
        return
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS speech_phrases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_sub TEXT,
            robot_slug TEXT,
            text TEXT NOT NULL,
            text_norm TEXT NOT NULL,
            voice_profile TEXT,
            face TEXT,
            use_count INTEGER NOT NULL DEFAULT 0,
            pinned INTEGER NOT NULL DEFAULT 0,
            scope TEXT NOT NULL DEFAULT 'personal',
            created_at_ms INTEGER NOT NULL,
            last_used_at_ms INTEGER NOT NULL,
            deleted_at_ms INTEGER
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS speech_phrases_user_norm_idx "
        "ON speech_phrases(user_sub, text_norm, deleted_at_ms)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS speech_phrases_last_used_idx "
        "ON speech_phrases(user_sub, last_used_at_ms DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS speech_phrases_scope_idx "
        "ON speech_phrases(scope, deleted_at_ms)"
    )


def normalize_text(text: str) -> str:
    """Lowercase, strip, and collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _row_to_out(row: dict) -> SpeechPhraseOut:
    return SpeechPhraseOut(
        id=row["id"],
        user_sub=row["user_sub"],
        robot_slug=row["robot_slug"],
        text=row["text"],
        text_norm=row["text_norm"],
        voice_profile=row["voice_profile"],
        face=row["face"],
        use_count=row["use_count"],
        pinned=bool(row["pinned"]),
        scope=row["scope"],
        created_at_ms=row["created_at_ms"],
        last_used_at_ms=row["last_used_at_ms"],
    )


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def upsert_phrase(
    user_sub: str,
    text: str,
    robot_slug: Optional[str],
    voice_profile: Optional[str],
    face: Optional[str],
    scope: str = "personal",
) -> SpeechPhraseOut:
    """Create a new phrase or increment use_count for an existing one."""
    text_norm = normalize_text(text)
    now_ms = int(time.time() * 1000)
    existing = db.fetchone(
        f"SELECT {_SELECT_COLUMNS} FROM speech_phrases "
        "WHERE user_sub = ? AND text_norm = ? AND deleted_at_ms IS NULL",
        (user_sub, text_norm),
    )
    if existing:
        new_count = existing["use_count"] + 1
        db.execute(
            "UPDATE speech_phrases SET use_count = ?, last_used_at_ms = ? WHERE id = ?",
            (new_count, now_ms, existing["id"]),
        )
        return get_phrase(existing["id"], user_sub, admin=True)
    new_id = db.execute(
        "INSERT INTO speech_phrases "
        "(user_sub, robot_slug, text, text_norm, voice_profile, face, use_count, pinned, scope, created_at_ms, last_used_at_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_sub, robot_slug, text, text_norm, voice_profile, face, 1, False, scope, now_ms, now_ms),
        returning_id=True,
    )
    return get_phrase(int(new_id), user_sub, admin=True)


def list_phrases(
    user_sub: str,
    limit: int = 20,
    q: str = "",
    sort: str = "recent",
    scope: Optional[str] = None,
) -> List[SpeechPhraseOut]:
    """Return the user's own phrases plus shared phrases."""
    params: List = [user_sub]
    query = (
        f"SELECT {_SELECT_COLUMNS} FROM speech_phrases "
        "WHERE deleted_at_ms IS NULL AND (user_sub = ? OR scope = 'shared')"
    )
    if scope:
        query += " AND scope = ?"
        params.append(scope)
    if q and q.strip():
        query += " AND text_norm LIKE ? ESCAPE '\\'"
        params.append(f"%{_like_escape(normalize_text(q))}%")
    query += " ORDER BY "
    query += (
        "use_count DESC, last_used_at_ms DESC"
        if sort == "frequent"
        else "last_used_at_ms DESC, use_count DESC"
    )
    query += " LIMIT ?"
    params.append(limit)
    rows = db.fetchall(query, tuple(params))
    return [_row_to_out(row) for row in rows]


def get_phrase(id: int, user_sub: str, admin: bool = False) -> Optional[SpeechPhraseOut]:
    """Fetch a single phrase if the caller is the owner, an admin, or the phrase is shared."""
    row = db.fetchone(
        f"SELECT {_SELECT_COLUMNS} FROM speech_phrases "
        "WHERE id = ? AND deleted_at_ms IS NULL",
        (id,),
    )
    if not row:
        return None
    if not admin and row["user_sub"] != user_sub and row["scope"] != "shared":
        return None
    return _row_to_out(row)


def update_phrase(
    id: int,
    user_sub: str,
    admin: bool,
    fields: SpeechPhraseUpdate,
) -> Optional[SpeechPhraseOut]:
    """Update a phrase if the caller owns it or is an admin."""
    phrase = get_phrase(id, user_sub, admin)
    if not phrase:
        return None
    updates: dict = {}
    if fields.text is not None:
        updates["text"] = fields.text
        updates["text_norm"] = normalize_text(fields.text)
    if fields.pinned is not None:
        updates["pinned"] = fields.pinned
    if fields.scope is not None:
        updates["scope"] = fields.scope
    if not updates:
        return phrase
    set_clause = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [id]
    db.execute(f"UPDATE speech_phrases SET {set_clause} WHERE id = ?", values)
    return get_phrase(id, user_sub, admin)


def soft_delete_phrase(id: int, user_sub: str, admin: bool) -> bool:
    """Soft-delete a phrase if the caller owns it or is an admin."""
    phrase = get_phrase(id, user_sub, admin)
    if not phrase:
        return False
    now_ms = int(time.time() * 1000)
    db.execute(
        "UPDATE speech_phrases SET deleted_at_ms = ? WHERE id = ?",
        (now_ms, id),
    )
    return True


async def record_from_interact(
    text: str,
    source: str,
    user_sub: Optional[str],
    robot_slug: Optional[str],
    voice_profile: Optional[str],
    face: Optional[str],
    record_phrase: bool,
) -> None:
    """Record an accepted interaction phrase asynchronously when enabled."""
    if not record_phrase:
        return
    if not text or not text.strip():
        return
    source = (source or "").lower()
    if not any(source.startswith(prefix) for prefix in ("liff", "line", "web")):
        return
    if not user_sub:
        return
    upsert_phrase(user_sub, text, robot_slug, voice_profile, face, scope="personal")
