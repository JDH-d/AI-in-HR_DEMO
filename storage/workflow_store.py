from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from domain.workflow import WorkflowValidationError, normalize_user, utc_now
from storage.request_migrations import migrate_requests
from storage.request_store import RequestStore


class WorkflowStore(RequestStore):
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.create_function("casefold", 1, lambda value: str(value).casefold(), deterministic=True)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            legacy_table = self._prepare_legacy_table(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    manager_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_requests (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    duration_days INTEGER,
                    comment TEXT NOT NULL,
                    applicant TEXT NOT NULL,
                    approver TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS request_events (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    actor TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (request_id) REFERENCES workflow_requests(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS request_comments (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (request_id) REFERENCES workflow_requests(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    comment TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (request_id) REFERENCES workflow_requests(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS assistant_feedback (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    comment TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS quality_reviews (
                    item_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_requests_applicant
                    ON workflow_requests(applicant, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_request
                    ON request_events(request_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_comments_request
                    ON request_comments(request_id, created_at);
                """
            )
            if legacy_table:
                self._migrate_legacy_rows(conn, legacy_table)
            assistant_feedback_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(assistant_feedback)").fetchall()
            }
            if "answer" not in assistant_feedback_columns:
                conn.execute(
                    "ALTER TABLE assistant_feedback ADD COLUMN answer TEXT NOT NULL DEFAULT ''"
                )
            conn.commit()
            migrate_requests(conn)

    @staticmethod
    def _prepare_legacy_table(conn: sqlite3.Connection) -> str | None:
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_requests'"
        ).fetchone()
        if not existing:
            return None
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(workflow_requests)").fetchall()
        }
        if {"start_date", "applicant", "approver", "updated_at"}.issubset(columns):
            return None
        legacy_table = f"workflow_requests_legacy_{uuid.uuid4().hex[:8]}"
        conn.execute(f'ALTER TABLE workflow_requests RENAME TO "{legacy_table}"')
        return legacy_table

    def _migrate_legacy_rows(self, conn: sqlite3.Connection, legacy_table: str) -> None:
        status_map = {
            "new": "draft",
            "pending": "in_review",
            "approved": "approved",
            "declined": "declined",
            "done": "completed",
        }
        rows = conn.execute(f'SELECT * FROM "{legacy_table}"').fetchall()
        for row in rows:
            data = dict(row)
            request_type = {
                "pto": "pto",
                "sick": "sick_leave",
                "document": "document",
            }.get(str(data.get("type", "")).lower(), "document")
            applicant = normalize_user(data.get("created_by"), "anonymous")
            approver = normalize_user(data.get("assigned_to"), "Manager")
            created_at = data.get("created_at") or utc_now()
            status = status_map.get(str(data.get("status", "")).lower(), "in_review")
            self._ensure_user(conn, applicant, "employee")
            self._ensure_user(conn, approver, "approver")
            conn.execute(
                """
                INSERT INTO workflow_requests
                (id, type, start_date, end_date, duration_days, comment, applicant, approver,
                 status, created_at, updated_at)
                VALUES (?, ?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["id"],
                    request_type,
                    data.get("comment", ""),
                    applicant,
                    approver,
                    status,
                    created_at,
                    created_at,
                ),
            )
            self._insert_event(
                conn,
                data["id"],
                "legacy_request_migrated",
                None,
                status,
                "system",
                {"legacy_period": data.get("period_or_date", "")},
                created_at=created_at,
            )

    @staticmethod
    def _ensure_user(
        conn: sqlite3.Connection,
        user_id: str,
        role: str,
        manager_id: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO users (id, display_name, role, manager_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (user_id, user_id, role, manager_id, utc_now()),
        )

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        request_id: str,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        actor: str,
        details: dict | None = None,
        created_at: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO request_events
            (id, request_id, event_type, from_status, to_status, actor, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                request_id,
                event_type,
                from_status,
                to_status,
                actor,
                json.dumps(details or {}, ensure_ascii=False),
                created_at or utc_now(),
            ),
        )

    def add_feedback(
        self,
        request_id: str,
        user_id: str,
        rating: int,
        comment: str,
    ) -> dict:
        if rating < 1 or rating > 5:
            raise WorkflowValidationError(["Rating must be between 1 and 5."])
        feedback_id = uuid.uuid4().hex
        created_at = utc_now()
        with closing(self._connect()) as conn:
            row = self._require_request(conn, request_id)
            conn.execute(
                """
                INSERT INTO feedback (id, request_id, user_id, rating, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (feedback_id, request_id, user_id, rating, comment.strip(), created_at),
            )
            self._insert_event(
                conn,
                request_id,
                "feedback_added",
                row["status"],
                row["status"],
                user_id,
                {"feedback_id": feedback_id, "rating": rating},
            )
            conn.commit()
        return {
            "id": feedback_id,
            "request_id": request_id,
            "user_id": user_id,
            "rating": rating,
            "comment": comment.strip(),
            "created_at": created_at,
        }

    def metrics(self) -> dict:
        with closing(self._connect()) as conn:
            total_requests = conn.execute("SELECT COUNT(*) FROM workflow_requests").fetchone()[0]
            by_status = {
                row["status"]: row["count"]
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM workflow_requests GROUP BY status"
                ).fetchall()
            }
            by_type = {
                row["type"]: row["count"]
                for row in conn.execute(
                    "SELECT type, COUNT(*) AS count FROM workflow_requests GROUP BY type"
                ).fetchall()
            }
            counts = {}
            for table in (
                "users",
                "request_events",
                "request_comments",
                "feedback",
                "assistant_feedback",
            ):
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            positive_feedback = conn.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT rating FROM feedback
                    UNION ALL
                    SELECT rating FROM assistant_feedback
                ) WHERE rating >= 4
                """
            ).fetchone()[0]
        return {
            "total_requests": total_requests,
            "requests_by_status": by_status,
            "requests_by_type": by_type,
            "positive_feedback": positive_feedback,
            **counts,
        }

    def add_assistant_feedback(
        self,
        user_id: str,
        rating: int,
        comment: str,
        question: str,
        answer: str,
    ) -> dict:
        if rating < 1 or rating > 5:
            raise WorkflowValidationError(["Rating must be between 1 and 5."])
        feedback_id = uuid.uuid4().hex
        created_at = utc_now()
        with closing(self._connect()) as conn:
            self._ensure_user(conn, user_id, "employee")
            conn.execute(
                """
                INSERT INTO assistant_feedback
                (id, user_id, rating, comment, question, answer, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    user_id,
                    rating,
                    comment.strip(),
                    question.strip(),
                    answer.strip(),
                    created_at,
                ),
            )
            conn.commit()
        return {
            "id": feedback_id,
            "user_id": user_id,
            "rating": rating,
            "comment": comment.strip(),
            "question": question.strip(),
            "answer": answer.strip(),
            "created_at": created_at,
        }

    def list_assistant_feedback(self, sentiment: str = "all", limit: int = 200) -> list[dict]:
        bounded = max(1, min(limit, 500))
        where = {
            "positive": "WHERE rating >= 4",
            "negative": "WHERE rating <= 2",
            "all": "",
        }.get(sentiment)
        if where is None:
            raise WorkflowValidationError(["Unsupported feedback sentiment filter."])
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT id, rating, comment, question, answer, created_at
                FROM assistant_feedback
                {where}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return [
            {
                **dict(row),
                "sentiment": "positive" if row["rating"] >= 4 else "negative",
            }
            for row in rows
        ]

    def review_quality_item(self, item_id: str, action: str) -> dict:
        cleaned_id = item_id.strip()
        cleaned_action = action.strip().lower()
        if not cleaned_id or cleaned_action not in {"resolved", "ignored"}:
            raise WorkflowValidationError(["Unsupported quality review action."])
        updated_at = utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO quality_reviews (item_id, action, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    action = excluded.action,
                    updated_at = excluded.updated_at
                """,
                (cleaned_id, cleaned_action, updated_at),
            )
            conn.commit()
        return {"item_id": cleaned_id, "action": cleaned_action, "updated_at": updated_at}

    def reviewed_quality_item_ids(self) -> set[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT item_id FROM quality_reviews").fetchall()
        return {str(row["item_id"]) for row in rows}
