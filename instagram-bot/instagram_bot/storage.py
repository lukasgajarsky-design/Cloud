"""Lokálna SQLite databáza stavov – ochrana proti duplicitným odpovediam a postom.

Princíp „najprv si zaber, potom konaj“ (claim → act → finish):

1. ``claim_*`` atomicky vloží záznam so stavom ``pending``. Ak záznam už
   existuje, vráti ``False`` a bot daný komentár/správu preskočí.
2. Bot vygeneruje a odošle odpoveď.
3. ``finish_*`` uloží výsledok (``replied``, ``ignored``, ``escalated``, ``failed``…).

Ak by bot spadol medzi krokmi 2 a 3, záznam ostane ``pending`` a bot na vec
už automaticky neodpovie – radšej jedna chýbajúca odpoveď ako dve rovnaké.
Ak zlyhá ešte PRED odoslaním (napr. výpadok Claude), ``release_*`` záznam zmaže
a vec sa spracuje v ďalšom cykle.

SQLite beží v režime WAL, takže súčasné čítanie (napr. ``--learn`` počas ``--run``)
nespôsobuje zamykanie.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS processed_comments (
    comment_id   TEXT PRIMARY KEY,
    media_id     TEXT NOT NULL,
    status       TEXT NOT NULL,
    reply_id     TEXT,
    detail       TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id       TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL,
    status           TEXT NOT NULL,
    reply_id         TEXT,
    detail           TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS published_posts (
    content_hash  TEXT PRIMARY KEY,
    source_name   TEXT NOT NULL,
    status        TEXT NOT NULL,
    container_id  TEXT,
    media_id      TEXT,
    permalink     TEXT,
    detail        TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS style_learning_runs (
    video_hash           TEXT PRIMARY KEY,
    video_name           TEXT NOT NULL,
    frames_sent          INTEGER NOT NULL,
    transcript_segments  INTEGER NOT NULL,
    output_path          TEXT NOT NULL,
    model                TEXT NOT NULL,
    input_tokens         INTEGER NOT NULL,
    output_tokens        INTEGER NOT NULL,
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_status ON processed_comments(status);
CREATE INDEX IF NOT EXISTS idx_messages_status ON processed_messages(status);
"""


class Status:
    """Stavy záznamov v databáze (konštanty, aby sa nepísali reťazce ručne)."""

    PENDING = "pending"
    REPLIED = "replied"
    IGNORED = "ignored"
    ESCALATED = "escalated"
    FAILED = "failed"
    UNKNOWN = "unknown"  # odoslanie s neistým výsledkom – neopakovať automaticky
    SKIPPED_OLD = "skipped_old"
    SKIPPED_OWN = "skipped_own"
    SKIPPED_ANSWERED = "skipped_already_answered"
    SKIPPED_EMPTY = "skipped_empty"
    SKIPPED_WINDOW = "skipped_outside_24h_window"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PostRecord:
    """Záznam o príspevku z fronty (podľa SHA-256 obsahu médií a promptu)."""

    content_hash: str
    source_name: str
    status: str
    container_id: str | None
    media_id: str | None
    permalink: str | None
    detail: str | None


@dataclass(frozen=True)
class LearningRunRecord:
    """Záznam o analýze videa v režime učenia."""

    video_hash: str
    video_name: str
    frames_sent: int
    transcript_segments: int
    output_path: str
    model: str
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateStore:
    """Tenká vrstva nad SQLite s metódami pre jednotlivé typy záznamov."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        # check_same_thread=False + vlastný zámok: bezpečné aj pri použití z viacerých vlákien.
        self._conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.executescript(_SCHEMA)

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _execute(self, sql: str, params: Iterable[object] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    # ------------------------------------------------------------------ komentáre
    def is_comment_known(self, comment_id: str) -> bool:
        return (
            self._execute("SELECT 1 FROM processed_comments WHERE comment_id = ?", (comment_id,)).fetchone() is not None
        )

    def claim_comment(self, comment_id: str, media_id: str) -> bool:
        """Atomicky si „zaberie“ komentár. ``False`` = už bol spracovaný/zabraný."""
        now = _now()
        cursor = self._execute(
            "INSERT OR IGNORE INTO processed_comments (comment_id, media_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (comment_id, media_id, Status.PENDING, now, now),
        )
        return cursor.rowcount == 1

    def mark_comment(self, comment_id: str, media_id: str, status: str, detail: str | None = None) -> None:
        """Rovno zapíše konečný stav (napr. preskočený starý komentár)."""
        now = _now()
        self._execute(
            "INSERT OR IGNORE INTO processed_comments (comment_id, media_id, status, detail, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (comment_id, media_id, status, detail, now, now),
        )

    def finish_comment(
        self, comment_id: str, status: str, *, reply_id: str | None = None, detail: str | None = None
    ) -> None:
        self._execute(
            "UPDATE processed_comments SET status = ?, reply_id = ?, detail = ?, updated_at = ? WHERE comment_id = ?",
            (status, reply_id, detail, _now(), comment_id),
        )

    def release_comment(self, comment_id: str) -> None:
        """Uvoľní zabraný komentár (len ak je stále ``pending``) – spracuje sa znova neskôr."""
        self._execute(
            "DELETE FROM processed_comments WHERE comment_id = ? AND status = ?", (comment_id, Status.PENDING)
        )

    # ---------------------------------------------------------------- DM správy
    def is_message_known(self, message_id: str) -> bool:
        return (
            self._execute("SELECT 1 FROM processed_messages WHERE message_id = ?", (message_id,)).fetchone() is not None
        )

    def claim_message(self, message_id: str, conversation_id: str) -> bool:
        now = _now()
        cursor = self._execute(
            "INSERT OR IGNORE INTO processed_messages (message_id, conversation_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, conversation_id, Status.PENDING, now, now),
        )
        return cursor.rowcount == 1

    def mark_messages(
        self, message_ids: Iterable[str], conversation_id: str, status: str, detail: str | None = None
    ) -> None:
        """Označí viac správ naraz (napr. všetky nezodpovedané správy, na ktoré sme práve odpovedali)."""
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                for message_id in message_ids:
                    self._conn.execute(
                        "INSERT INTO processed_messages "
                        "(message_id, conversation_id, status, detail, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(message_id) DO UPDATE SET status = excluded.status, detail = excluded.detail, "
                        "updated_at = excluded.updated_at",
                        (message_id, conversation_id, status, detail, now, now),
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def finish_message(
        self, message_id: str, status: str, *, reply_id: str | None = None, detail: str | None = None
    ) -> None:
        self._execute(
            "UPDATE processed_messages SET status = ?, reply_id = ?, detail = ?, updated_at = ? WHERE message_id = ?",
            (status, reply_id, detail, _now(), message_id),
        )

    def release_message(self, message_id: str) -> None:
        self._execute(
            "DELETE FROM processed_messages WHERE message_id = ? AND status = ?", (message_id, Status.PENDING)
        )

    # -------------------------------------------------------------------- posty
    def get_post(self, content_hash: str) -> PostRecord | None:
        row = self._execute("SELECT * FROM published_posts WHERE content_hash = ?", (content_hash,)).fetchone()
        if row is None:
            return None
        return PostRecord(
            content_hash=row["content_hash"],
            source_name=row["source_name"],
            status=row["status"],
            container_id=row["container_id"],
            media_id=row["media_id"],
            permalink=row["permalink"],
            detail=row["detail"],
        )

    def upsert_post(
        self,
        content_hash: str,
        source_name: str,
        status: str,
        *,
        container_id: str | None = None,
        media_id: str | None = None,
        permalink: str | None = None,
        detail: str | None = None,
    ) -> None:
        now = _now()
        self._execute(
            "INSERT INTO published_posts "
            "(content_hash, source_name, status, container_id, media_id, permalink, detail, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(content_hash) DO UPDATE SET source_name = excluded.source_name, status = excluded.status, "
            "container_id = COALESCE(excluded.container_id, published_posts.container_id), "
            "media_id = COALESCE(excluded.media_id, published_posts.media_id), "
            "permalink = COALESCE(excluded.permalink, published_posts.permalink), "
            "detail = excluded.detail, updated_at = excluded.updated_at",
            (content_hash, source_name, status, container_id, media_id, permalink, detail, now, now),
        )

    # ------------------------------------------------------- učenie štýlu z videa
    def get_learning_run(self, video_hash: str) -> LearningRunRecord | None:
        row = self._execute("SELECT * FROM style_learning_runs WHERE video_hash = ?", (video_hash,)).fetchone()
        if row is None:
            return None
        return LearningRunRecord(
            video_hash=row["video_hash"],
            video_name=row["video_name"],
            frames_sent=row["frames_sent"],
            transcript_segments=row["transcript_segments"],
            output_path=row["output_path"],
            model=row["model"],
            created_at=row["created_at"],
        )

    def record_learning_run(
        self,
        *,
        video_hash: str,
        video_name: str,
        frames_sent: int,
        transcript_segments: int,
        output_path: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self._execute(
            "INSERT OR REPLACE INTO style_learning_runs (video_hash, video_name, frames_sent, transcript_segments, "
            "output_path, model, input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                video_hash,
                video_name,
                frames_sent,
                transcript_segments,
                output_path,
                model,
                input_tokens,
                output_tokens,
                _now(),
            ),
        )

    # -------------------------------------------------------------------- reporty
    def count_by_status(self, table: str) -> dict[str, int]:
        """Počty záznamov podľa stavu (pre ``--check``)."""
        if table not in {"processed_comments", "processed_messages", "published_posts"}:
            raise ValueError(f"Neznáma tabuľka: {table}")
        rows = self._execute(f"SELECT status, COUNT(*) AS n FROM {table} GROUP BY status")  # noqa: S608 – tabuľka je z whitelistu
        return {row["status"]: row["n"] for row in rows.fetchall()}

    def iter_escalations(self, limit: int = 20) -> Iterator[sqlite3.Row]:
        """Posledné eskalované komentáre a správy, ktoré čakajú na človeka."""
        rows = self._execute(
            "SELECT 'comment' AS kind, comment_id AS item_id, detail, updated_at "
            "FROM processed_comments WHERE status = ? "
            "UNION ALL "
            "SELECT 'dm' AS kind, message_id AS item_id, detail, updated_at FROM processed_messages WHERE status = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (Status.ESCALATED, Status.ESCALATED, limit),
        )
        yield from rows.fetchall()
