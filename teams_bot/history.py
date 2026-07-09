from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from api.schemas import Message


class TeamsConversationHistory:
    def __init__(self, db_path: Path, retention_messages: int = 64) -> None:
        self.db_path = db_path
        self.retention_messages = retention_messages
        self._lock = threading.Lock()
        self._init_db()

    def load(self, conversation_key: str, limit: int) -> list[Message]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM teams_conversation_messages
                WHERE conversation_key = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (conversation_key, limit),
            ).fetchall()
        return [
            Message(role=role, content=content)
            for role, content in reversed(rows)
            if role in {"user", "assistant", "system"}
        ]

    def append_turn(self, conversation_key: str, user_text: str, assistant_text: str) -> None:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO teams_conversation_messages
                    (conversation_key, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (conversation_key, "user", user_text, now),
                    (conversation_key, "assistant", assistant_text, now),
                ],
            )
            conn.execute(
                """
                DELETE FROM teams_conversation_messages
                WHERE id IN (
                    SELECT id
                    FROM teams_conversation_messages
                    WHERE conversation_key = ?
                    ORDER BY id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (conversation_key, self.retention_messages),
            )

    def clear(self, conversation_key: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM teams_conversation_messages WHERE conversation_key = ?",
                (conversation_key,),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS teams_conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_key TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_teams_conversation_messages_key_id
                ON teams_conversation_messages(conversation_key, id)
                """
            )

