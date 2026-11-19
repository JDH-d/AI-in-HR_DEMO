from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from domain.errors import ConversationError


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    """Persistent, owner-scoped chat data in the application's SQLite database."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            # Separate migration ledger: workflow migrations own PRAGMA user_version.
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL,
                    manager_id TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_migrations (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    turn_id TEXT NOT NULL,
                    sender_id TEXT REFERENCES users(id),
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('complete', 'pending', 'failed')),
                    lease_until REAL,
                    attempt_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(conversation_id, turn_id, role)
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_owner
                    ON conversations(owner_id, updated_at DESC, id);
                CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation
                    ON chat_messages(conversation_id, sequence);
                INSERT OR IGNORE INTO chat_migrations VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
                COMMIT;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.create_function(
            "casefold", 1, lambda value: (value or "").casefold(), deterministic=True
        )
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_user(self, user: dict) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO users(id, display_name, role, manager_id, created_at)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET
                display_name=excluded.display_name, role=excluded.role, manager_id=excluded.manager_id
                """,
                (user["id"], user["display_name"], user["role"], user.get("manager_id"), now()),
            )

    @staticmethod
    def owned(db, conversation_id: str, owner: str):
        row = db.execute(
            "SELECT * FROM conversations WHERE id=? AND owner_id=?", (conversation_id, owner)
        ).fetchone()
        if row is None:
            raise ConversationError("not_found", "Conversation not found.")
        return dict(row)

    @staticmethod
    def expire(db, conversation_id: str):
        db.execute(
            """UPDATE chat_messages SET status='failed', lease_until=NULL,
            content='The response was interrupted. You can retry this message.'
            WHERE conversation_id=? AND status='pending' AND lease_until < ?""",
            (conversation_id, time.time()),
        )

    @staticmethod
    def messages(db, conversation_id: str) -> list[dict]:
        rows = db.execute(
            "SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY sequence",
            (conversation_id,),
        ).fetchall()
        result = []
        for row in rows:
            message = {
                key: row[key]
                for key in ("id", "turn_id", "sender_id", "role", "content", "created_at", "status")
            }
            message.update(json.loads(row["metadata"]))
            result.append(message)
        return result

    def create(self, owner: str, conversation_id: str, title: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if existing:
                return self.owned(db, conversation_id, owner)
            stamp = now()
            db.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
                (conversation_id, owner, title, stamp, stamp),
            )
            return self.owned(db, conversation_id, owner)

    def list(self, owner: str, query: str, limit: int, offset: int) -> dict:
        with self.connect() as db:
            rows = db.execute(
                """SELECT c.* FROM conversations c WHERE c.owner_id=? AND
                (?='' OR instr(casefold(c.title),casefold(?))>0 OR EXISTS (
                    SELECT 1 FROM chat_messages m WHERE m.conversation_id=c.id
                    AND instr(casefold(m.content),casefold(?))>0))
                ORDER BY c.updated_at DESC, c.id LIMIT ? OFFSET ?""",
                (owner, query, query, query, limit + 1, offset),
            ).fetchall()
            return {
                "conversations": [dict(row) for row in rows[:limit]],
                "has_more": len(rows) > limit,
            }

    def get(self, conversation_id: str, owner: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            conversation = self.owned(db, conversation_id, owner)
            self.expire(db, conversation_id)
            return {"conversation": conversation, "messages": self.messages(db, conversation_id)}

    def rename(self, conversation_id: str, owner: str, title: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owned(db, conversation_id, owner)
            db.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                (title, now(), conversation_id),
            )
            return self.owned(db, conversation_id, owner)

    def delete(self, conversation_id: str, owner: str) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owned(db, conversation_id, owner)
            self.expire(db, conversation_id)
            if db.execute(
                "SELECT 1 FROM chat_messages WHERE conversation_id=? AND status='pending'",
                (conversation_id,),
            ).fetchone():
                raise ConversationError(
                    "conflict", "Wait for the current reply before deleting this conversation."
                )
            db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))

    def begin_turn(
        self, conversation_id: str, owner: str, turn_id: str, content: str, lease_seconds: float
    ) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owned(db, conversation_id, owner)
            self.expire(db, conversation_id)
            previous = db.execute(
                "SELECT * FROM chat_messages WHERE conversation_id=? AND turn_id=? ORDER BY sequence",
                (conversation_id, turn_id),
            ).fetchall()
            if previous and previous[0]["content"] != content:
                raise ConversationError(
                    "conflict", "This message ID already belongs to different text."
                )
            if previous and previous[1]["status"] == "complete":
                return {"cached": True}
            if db.execute(
                "SELECT 1 FROM chat_messages WHERE conversation_id=? AND status='pending'",
                (conversation_id,),
            ).fetchone():
                raise ConversationError(
                    "conflict",
                    "A reply is already being prepared. Reload the conversation shortly.",
                )
            if previous:
                latest = db.execute(
                    "SELECT turn_id FROM chat_messages WHERE conversation_id=? ORDER BY sequence DESC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                if latest["turn_id"] != turn_id:
                    raise ConversationError(
                        "conflict", "Only the latest failed message can be retried."
                    )
                db.execute(
                    "UPDATE chat_messages SET status='pending', content='', lease_until=? WHERE id=?",
                    (time.time() + lease_seconds, previous[1]["id"]),
                )
            else:
                stamp = now()
                for role, text, sender, state in [
                    ("user", content, owner, "complete"),
                    ("assistant", "", None, "pending"),
                ]:
                    db.execute(
                        """INSERT INTO chat_messages
                        (id,conversation_id,turn_id,sender_id,role,content,created_at,status,lease_until)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            str(uuid.uuid4()),
                            conversation_id,
                            turn_id,
                            sender,
                            role,
                            text,
                            stamp,
                            state,
                            time.time() + lease_seconds if state == "pending" else None,
                        ),
                    )
                count = db.execute(
                    "SELECT count(*) FROM chat_messages WHERE conversation_id=?", (conversation_id,)
                ).fetchone()[0]
                if count == 2:
                    db.execute(
                        "UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",
                        (" ".join(content.split())[:80], conversation_id),
                    )
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id))
            attempt_id = str(uuid.uuid4())
            db.execute(
                "UPDATE chat_messages SET attempt_id=? WHERE conversation_id=? AND turn_id=? AND role='assistant'",
                (attempt_id, conversation_id, turn_id),
            )
            history = [m for m in self.messages(db, conversation_id) if m["status"] == "complete"]
            return {"cached": False, "history": history[-80:], "attempt_id": attempt_id}

    def finish_turn(
        self,
        conversation_id: str,
        turn_id: str,
        content: str,
        metadata: dict,
        *,
        attempt_id: str,
        failed=False,
    ):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                """UPDATE chat_messages SET content=?, metadata=?, status=?, lease_until=NULL, created_at=?
                WHERE conversation_id=? AND turn_id=? AND role='assistant' AND status='pending' AND attempt_id=?""",
                (
                    content,
                    json.dumps(metadata, ensure_ascii=False),
                    "failed" if failed else "complete",
                    now(),
                    conversation_id,
                    turn_id,
                    attempt_id,
                ),
            )
            if updated.rowcount:
                db.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id)
                )
