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
    """Stores user-scoped chat history in its own local SQLite database."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        legacy_db_path: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.legacy_db_path = Path(legacy_db_path) if legacy_db_path is not None else None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._import_legacy_history()

    @property
    def backend_id(self) -> str:
        """Stable identity of this conversation storage, independent of its URL or path.

        A copied database retains its logical storage identity. Creating a new
        database creates a new identity; unrelated workflow/document stores are
        not fingerprinted by this value.
        """
        return self._backend_id

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
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
                    workflow_request_id TEXT,
                    outcome_code TEXT NOT NULL DEFAULT 'unknown',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_owner
                    ON conversations(owner_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_conversation_messages
                    ON conversation_messages(conversation_id, created_at);

                CREATE TABLE IF NOT EXISTS conversation_migrations (
                    name TEXT PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS conversation_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            # Concurrent initializers must read the winning persisted value,
            # not keep their own candidate UUID. Existing storage is unchanged.
            conn.execute(
                "INSERT OR IGNORE INTO conversation_metadata (key, value) VALUES (?, ?)",
                ("backend_id", str(uuid.uuid4())),
            )
            self._backend_id = str(
                conn.execute(
                    "SELECT value FROM conversation_metadata WHERE key = 'backend_id'"
                ).fetchone()["value"]
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(conversation_messages)").fetchall()
            }
            if "workflow_request_id" not in columns:
                conn.execute(
                    "ALTER TABLE conversation_messages ADD COLUMN workflow_request_id TEXT"
                )
            if "outcome_code" not in columns:
                conn.execute(
                    "ALTER TABLE conversation_messages "
                    "ADD COLUMN outcome_code TEXT NOT NULL DEFAULT 'unknown'"
                )
            self._backfill_message_metadata(conn)
            conn.execute(
                """
                DELETE FROM conversations
                WHERE NOT EXISTS (
                    SELECT 1 FROM conversation_messages
                    WHERE conversation_messages.conversation_id = conversations.id
                )
                """
            )
            conn.commit()

    def _import_legacy_history(self) -> None:
        legacy_path = self.legacy_db_path
        if legacy_path is None or not legacy_path.is_file():
            return
        if legacy_path.resolve() == self.db_path.resolve():
            return

        with closing(self._connect()) as target:
            if target.execute(
                "SELECT 1 FROM conversation_migrations WHERE name = 'legacy_history_import'"
            ).fetchone():
                return
            if target.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]:
                # An existing history must not be replaced after the user deletes its last chat.
                target.execute(
                    "INSERT OR IGNORE INTO conversation_migrations VALUES ('legacy_history_import')"
                )
                target.commit()
                return

        with closing(sqlite3.connect(str(legacy_path))) as source:
            source.row_factory = sqlite3.Row
            tables = {
                row["name"]
                for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if not {"conversations", "conversation_messages"}.issubset(tables):
                return
            message_columns = {
                row["name"]
                for row in source.execute("PRAGMA table_info(conversation_messages)").fetchall()
            }
            conversations = source.execute("SELECT * FROM conversations").fetchall()
            messages = source.execute("SELECT * FROM conversation_messages").fetchall()

        with closing(self._connect()) as target:
            target.execute("BEGIN IMMEDIATE")
            target.executemany(
                """
                INSERT OR IGNORE INTO conversations
                    (id, owner_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["id"],
                        row["owner_id"],
                        row["title"],
                        row["created_at"],
                        row["updated_at"],
                    )
                    for row in conversations
                ],
            )
            target.executemany(
                """
                INSERT OR IGNORE INTO conversation_messages
                    (id, conversation_id, role, content, sources, workflow_request,
                     workflow_request_id, outcome_code, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["id"],
                        row["conversation_id"],
                        row["role"],
                        row["content"],
                        row["sources"],
                        row["workflow_request"],
                        row["workflow_request_id"]
                        if "workflow_request_id" in message_columns
                        else None,
                        (
                            row["outcome_code"]
                            if "outcome_code" in message_columns
                            else _legacy_outcome_code(row["role"], row["sources"])
                        ),
                        row["created_at"],
                    )
                    for row in messages
                ],
            )
            self._backfill_message_metadata(target)
            target.execute(
                "INSERT OR IGNORE INTO conversation_migrations VALUES ('legacy_history_import')"
            )
            target.commit()

    @classmethod
    def _backfill_message_metadata(cls, conn: sqlite3.Connection) -> None:
        cls._backfill_workflow_ids(conn)
        conn.execute(
            """
            UPDATE conversation_messages
            SET outcome_code = 'grounded'
            WHERE role = 'assistant'
              AND outcome_code = 'unknown'
              AND sources NOT IN ('', '[]')
            """
        )

    @staticmethod
    def _backfill_workflow_ids(conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT id, workflow_request FROM conversation_messages
            WHERE workflow_request_id IS NULL AND workflow_request IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            try:
                snapshot = json.loads(row["workflow_request"])
            except (json.JSONDecodeError, TypeError):
                continue
            request_id = snapshot.get("id") if isinstance(snapshot, dict) else None
            if request_id:
                conn.execute(
                    "UPDATE conversation_messages SET workflow_request_id = ? WHERE id = ?",
                    (str(request_id), row["id"]),
                )

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

    def delete_for_user(self, conversation_id: str, owner_id: str) -> bool:
        """Delete a user's conversation and its messages, leaving workflow requests intact."""
        with closing(self._connect()) as conn:
            deleted = conn.execute(
                "DELETE FROM conversations WHERE id = ? AND owner_id = ?",
                (conversation_id, owner_id),
            )
            conn.commit()
        return deleted.rowcount > 0

    def metrics(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            questions = conn.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE role = 'user'"
            ).fetchone()[0]
            grounded = conn.execute(
                """
                SELECT COUNT(*) FROM conversation_messages
                WHERE role = 'assistant' AND outcome_code = 'grounded'
                """
            ).fetchone()[0]
        return {"questions": int(questions), "grounded_answers": int(grounded)}

    def record_exchange(
        self,
        owner_id: str,
        *,
        conversation_id: str | None,
        user_content: str,
        assistant_content: str,
        sources: list[dict] | None = None,
        workflow_request: dict | None = None,
        outcome_code: str = "unknown",
    ) -> dict:
        cleaned_user_content = user_content.strip()
        if not cleaned_user_content:
            raise ValueError("A conversation exchange requires a user message.")

        active_id = conversation_id or uuid.uuid4().hex
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conversation = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND owner_id = ?",
                (active_id, owner_id),
            ).fetchone()
            if conversation_id and conversation is None:
                raise ConversationNotFoundError("The conversation could not be found.")

            user_created_at = _utc_now()
            assistant_created_at = _utc_now()
            if conversation is None:
                title = _conversation_title(cleaned_user_content)
                conn.execute(
                    """
                    INSERT INTO conversations (id, owner_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (active_id, owner_id, title, user_created_at, assistant_created_at),
                )
            else:
                title = str(conversation["title"])

            conn.execute(
                """
                INSERT INTO conversation_messages
                    (id, conversation_id, role, content, sources, workflow_request, created_at)
                VALUES (?, ?, 'user', ?, '[]', NULL, ?)
                """,
                (uuid.uuid4().hex, active_id, cleaned_user_content, user_created_at),
            )
            conn.execute(
                """
                INSERT INTO conversation_messages
                    (id, conversation_id, role, content, sources, workflow_request,
                     workflow_request_id, outcome_code, created_at)
                VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    active_id,
                    assistant_content,
                    json.dumps(sources or [], ensure_ascii=False),
                    (
                        json.dumps(workflow_request, ensure_ascii=False)
                        if workflow_request is not None
                        else None
                    ),
                    str(workflow_request["id"]) if workflow_request else None,
                    outcome_code,
                    assistant_created_at,
                ),
            )
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, assistant_created_at, active_id),
            )
            conn.commit()

        detail = self.get_for_user(active_id, owner_id)
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


def _legacy_outcome_code(role: str, sources: str) -> str:
    return "grounded" if role == "assistant" and sources not in {"", "[]"} else "unknown"


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
        "workflow_request_id": row["workflow_request_id"],
        "created_at": row["created_at"],
    }
