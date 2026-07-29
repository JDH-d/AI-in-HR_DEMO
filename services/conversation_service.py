from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class ConversationNotFoundError(RuntimeError):
    pass


class ConversationValidationError(RuntimeError):
    pass


class ConversationService:
    def __init__(self, db_path: str) -> None:
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
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    sources TEXT NOT NULL DEFAULT '[]',
                    workflow_request TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
                    ON conversations(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_conversation_messages_order
                    ON conversation_messages(conversation_id, created_at);
                """
            )
            conn.commit()

    def create(self, user_id: str) -> dict:
        cleaned_user_id = _required_text(user_id, "User ID")
        conversation_id = uuid.uuid4().hex
        created_at = _utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, user_id, title, created_at, updated_at)
                VALUES (?, ?, 'New conversation', ?, ?)
                """,
                (conversation_id, cleaned_user_id, created_at, created_at),
            )
            conn.commit()
        return {
            "id": conversation_id,
            "title": "New conversation",
            "created_at": created_at,
            "updated_at": created_at,
        }

    def list_for_user(self, user_id: str) -> list[dict]:
        cleaned_user_id = _required_text(user_id, "User ID")
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT c.*
                FROM conversations AS c
                WHERE c.user_id = ?
                  AND EXISTS (
                      SELECT 1
                      FROM conversation_messages AS message
                      WHERE message.conversation_id = c.id
                  )
                ORDER BY c.updated_at DESC, c.rowid DESC
                """,
                (cleaned_user_id,),
            ).fetchall()
        return [_conversation_row_to_dict(row) for row in rows]

    def get_for_user(self, conversation_id: str, user_id: str) -> dict:
        cleaned_conversation_id = _required_text(conversation_id, "Conversation ID")
        cleaned_user_id = _required_text(user_id, "User ID")
        with closing(self._connect()) as conn:
            conversation = conn.execute(
                """
                SELECT *
                FROM conversations
                WHERE id = ? AND user_id = ?
                """,
                (cleaned_conversation_id, cleaned_user_id),
            ).fetchone()
            if conversation is None:
                raise ConversationNotFoundError("The conversation could not be found.")
            messages = conn.execute(
                """
                SELECT *
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at, rowid
                """,
                (cleaned_conversation_id,),
            ).fetchall()
        return {
            "conversation": _conversation_row_to_dict(conversation),
            "messages": [_message_row_to_dict(row) for row in messages],
        }

    def delete_for_user(self, conversation_id: str, user_id: str) -> dict:
        cleaned_conversation_id = _required_text(conversation_id, "Conversation ID")
        cleaned_user_id = _required_text(user_id, "User ID")
        with closing(self._connect()) as conn:
            conversation = conn.execute(
                """
                SELECT *
                FROM conversations
                WHERE id = ? AND user_id = ?
                """,
                (cleaned_conversation_id, cleaned_user_id),
            ).fetchone()
            if conversation is None:
                raise ConversationNotFoundError("The conversation could not be found.")
            conn.execute(
                """
                DELETE FROM conversations
                WHERE id = ? AND user_id = ?
                """,
                (cleaned_conversation_id, cleaned_user_id),
            )
            conn.commit()
        return _conversation_row_to_dict(conversation)

    def append_exchange(
        self,
        conversation_id: str,
        user_id: str,
        *,
        user_text: str,
        assistant_text: str,
        sources: list[dict] | None = None,
        workflow_request: dict | None = None,
    ) -> dict:
        cleaned_conversation_id = _required_text(conversation_id, "Conversation ID")
        cleaned_user_id = _required_text(user_id, "User ID")
        cleaned_user_text = _required_text(user_text, "User message")
        cleaned_assistant_text = _required_text(assistant_text, "Assistant message")
        user_created_at = _utc_now()
        assistant_created_at = _utc_now()

        with closing(self._connect()) as conn:
            conversation = conn.execute(
                """
                SELECT *
                FROM conversations
                WHERE id = ? AND user_id = ?
                """,
                (cleaned_conversation_id, cleaned_user_id),
            ).fetchone()
            if conversation is None:
                raise ConversationNotFoundError("The conversation could not be found.")

            has_messages = conn.execute(
                """
                SELECT 1
                FROM conversation_messages
                WHERE conversation_id = ?
                LIMIT 1
                """,
                (cleaned_conversation_id,),
            ).fetchone()
            title = conversation["title"]
            if has_messages is None:
                title = _conversation_title(cleaned_user_text)

            conn.execute(
                """
                INSERT INTO conversation_messages
                (id, conversation_id, role, content, sources, workflow_request, created_at)
                VALUES (?, ?, 'user', ?, '[]', NULL, ?)
                """,
                (
                    uuid.uuid4().hex,
                    cleaned_conversation_id,
                    cleaned_user_text,
                    user_created_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO conversation_messages
                (id, conversation_id, role, content, sources, workflow_request, created_at)
                VALUES (?, ?, 'assistant', ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    cleaned_conversation_id,
                    cleaned_assistant_text,
                    json.dumps(sources or [], ensure_ascii=False),
                    (
                        json.dumps(workflow_request, ensure_ascii=False)
                        if workflow_request is not None
                        else None
                    ),
                    assistant_created_at,
                ),
            )
            conn.execute(
                """
                UPDATE conversations
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, assistant_created_at, cleaned_conversation_id),
            )
            conn.commit()

        return self.get_for_user(cleaned_conversation_id, cleaned_user_id)


def _required_text(value: str, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ConversationValidationError(f"{label} cannot be empty.")
    return cleaned


def _conversation_title(text: str, max_length: int = 64) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_length:
        return cleaned
    shortened = cleaned[: max_length - 3].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return f"{shortened or cleaned[: max_length - 3]}..."


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conversation_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _message_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "sources": _json_value(row["sources"], []),
        "workflow_request": _json_value(row["workflow_request"], None),
        "created_at": row["created_at"],
    }


def _json_value(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
