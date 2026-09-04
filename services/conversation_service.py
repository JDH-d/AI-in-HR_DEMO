from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class ConversationNotFoundError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationService:
    """Stores user-scoped chat history in the existing local SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources TEXT NOT NULL DEFAULT '[]',
                    workflow_request TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_owner
                    ON conversations(owner_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_conversation_messages
                    ON conversation_messages(conversation_id, created_at);
                """
            )
            conn.commit()

    def create(self, owner_id: str) -> dict:
        conversation_id = uuid.uuid4().hex
        created_at = _utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, owner_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, owner_id, "New conversation", created_at, created_at),
            )
            conn.commit()
        return {
            "id": conversation_id,
            "title": "New conversation",
            "message_count": 0,
            "created_at": created_at,
            "updated_at": created_at,
        }

    def list_for_user(self, owner_id: str, limit: int = 50) -> list[dict]:
        bounded = max(1, min(limit, 100))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT
                    conversations.*,
                    COUNT(conversation_messages.id) AS message_count
                FROM conversations
                JOIN conversation_messages
                  ON conversation_messages.conversation_id = conversations.id
                WHERE conversations.owner_id = ?
                GROUP BY conversations.id
                ORDER BY conversations.updated_at DESC
                LIMIT ?
                """,
                (owner_id, bounded),
            ).fetchall()
        return [_conversation_row_to_dict(row) for row in rows]

    def get_for_user(self, conversation_id: str, owner_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            conversation = conn.execute(
                """
                SELECT
                    conversations.*,
                    COUNT(conversation_messages.id) AS message_count
                FROM conversations
                LEFT JOIN conversation_messages
                  ON conversation_messages.conversation_id = conversations.id
                WHERE conversations.id = ? AND conversations.owner_id = ?
                GROUP BY conversations.id
                """,
                (conversation_id, owner_id),
            ).fetchone()
            if conversation is None:
                return None
            messages = conn.execute(
                """
                SELECT * FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at, rowid
                """,
                (conversation_id,),
            ).fetchall()
        return {
            "conversation": _conversation_row_to_dict(conversation),
            "messages": [_message_row_to_dict(row) for row in messages],
        }

    def append_exchange(
        self,
        conversation_id: str,
        owner_id: str,
        *,
        user_content: str,
        assistant_content: str,
        sources: list[dict] | None = None,
        workflow_request: dict | None = None,
    ) -> dict:
        with closing(self._connect()) as conn:
            conversation = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND owner_id = ?",
                (conversation_id, owner_id),
            ).fetchone()
            if conversation is None:
                raise ConversationNotFoundError("The conversation could not be found.")

            message_count = conn.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            user_created_at = _utc_now()
            assistant_created_at = _utc_now()
            conn.execute(
                """
                INSERT INTO conversation_messages
                    (id, conversation_id, role, content, sources, workflow_request, created_at)
                VALUES (?, ?, 'user', ?, '[]', NULL, ?)
                """,
                (uuid.uuid4().hex, conversation_id, user_content, user_created_at),
            )
            conn.execute(
                """
                INSERT INTO conversation_messages
                    (id, conversation_id, role, content, sources, workflow_request, created_at)
                VALUES (?, ?, 'assistant', ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    conversation_id,
                    assistant_content,
                    json.dumps(sources or [], ensure_ascii=False),
                    (
                        json.dumps(workflow_request, ensure_ascii=False)
                        if workflow_request is not None
                        else None
                    ),
                    assistant_created_at,
                ),
            )
            title = (
                _conversation_title(user_content)
                if message_count == 0
                else str(conversation["title"])
            )
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, assistant_created_at, conversation_id),
            )
            conn.commit()

        detail = self.get_for_user(conversation_id, owner_id)
        if detail is None:
            raise ConversationNotFoundError("The conversation could not be found.")
        return detail


def _conversation_title(content: str, max_length: int = 52) -> str:
    cleaned = " ".join((content or "").split()).strip()
    if not cleaned:
        return "New conversation"
    if len(cleaned) <= max_length:
        return cleaned
    shortened = cleaned[: max_length + 1].rsplit(" ", 1)[0].rstrip(".,!?;:")
    return f"{shortened or cleaned[:max_length].rstrip()}…"


def _conversation_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "message_count": int(row["message_count"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _message_row_to_dict(row: sqlite3.Row) -> dict:
    try:
        sources = json.loads(row["sources"] or "[]")
    except (json.JSONDecodeError, TypeError):
        sources = []
    try:
        workflow_request = json.loads(row["workflow_request"]) if row["workflow_request"] else None
    except (json.JSONDecodeError, TypeError):
        workflow_request = None
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "sources": sources,
        "workflow": workflow_request,
        "created_at": row["created_at"],
    }
