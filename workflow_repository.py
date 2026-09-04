from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from workflow_domain import (
    REQUEST_TRANSITIONS,
    REQUEST_TYPE_LABELS,
    SUPPORTED_REQUEST_TYPES,
    VALID_STATUSES,
    VALID_TYPES,
    InvalidTransitionError,
    WorkflowDraftData,
    WorkflowNotFoundError,
    WorkflowPermissionError,
    WorkflowValidationError,
    duration_days,
    normalize_request_details,
    normalize_user_id,
    optional_string,
    request_end_date,
    utc_now,
    validate_request_fields,
)
from workflow_schema import initialize_workflow_schema

_MANAGER_VISIBLE_REQUEST = """
(
  status IN ('in_review', 'reported', 'approved', 'declined', 'acknowledged')
  OR (
    status = 'cancelled'
    AND EXISTS (
      SELECT 1 FROM request_events
      WHERE request_events.request_id = workflow_requests.id
        AND request_events.to_status = 'cancelled'
        AND request_events.from_status IN ('in_review', 'reported')
    )
  )
)
"""


class WorkflowStore:
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
            initialize_workflow_schema(conn)

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

    def create_draft(self, draft: WorkflowDraftData) -> dict:
        if draft.request_type not in VALID_TYPES:
            raise WorkflowValidationError(["Request type is not supported."])
        request_id = uuid.uuid4().hex
        created_at = utc_now()
        duration = None
        try:
            duration = duration_days(draft.start_date, draft.end_date)
        except ValueError:
            duration = None
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO workflow_requests
                (id, type, start_date, end_date, duration_days, comment, applicant, approver,
                 details, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
                """,
                (
                    request_id,
                    draft.request_type,
                    draft.start_date,
                    draft.end_date,
                    duration,
                    draft.comment,
                    draft.applicant,
                    draft.approver,
                    json.dumps(draft.details, ensure_ascii=False),
                    created_at,
                    created_at,
                ),
            )
            self._insert_event(
                conn,
                request_id,
                "draft_created",
                None,
                "draft",
                draft.applicant,
                {"validation_errors": draft.validation_errors},
            )
            conn.commit()
        result = self.get_request(request_id)
        assert result is not None
        result["validation_errors"] = draft.validation_errors
        return result

    def get_request(self, request_id: str) -> dict | None:
        placeholders = _supported_type_placeholders()
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"""
                SELECT * FROM workflow_requests
                WHERE id = ? AND type IN ({placeholders})
                """,
                (request_id, *SUPPORTED_REQUEST_TYPES),
            ).fetchone()
        return _request_row_to_dict(row) if row else None

    def list_by_user(self, applicant: str) -> list[dict]:
        placeholders = _supported_type_placeholders()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM workflow_requests
                WHERE applicant = ? AND type IN ({placeholders})
                ORDER BY created_at DESC
                """,
                (normalize_user_id(applicant, "anonymous"), *SUPPORTED_REQUEST_TYPES),
            ).fetchall()
        return [_request_row_to_dict(row) for row in rows]

    def list_by_approver(self, approver: str, limit: int = 200) -> list[dict]:
        bounded = max(1, min(limit, 1000))
        placeholders = _supported_type_placeholders()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM workflow_requests
                WHERE approver = ?
                  AND {_MANAGER_VISIBLE_REQUEST}
                  AND type IN ({placeholders})
                ORDER BY created_at DESC LIMIT ?
                """,
                (normalize_user_id(approver, "manager.demo"), *SUPPORTED_REQUEST_TYPES, bounded),
            ).fetchall()
        return [_request_row_to_dict(row) for row in rows]

    def get_for_manager(self, request_id: str, manager_id: str) -> dict | None:
        placeholders = _supported_type_placeholders()
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"""
                SELECT * FROM workflow_requests
                WHERE id = ? AND approver = ? AND {_MANAGER_VISIBLE_REQUEST}
                  AND type IN ({placeholders})
                """,
                (request_id, manager_id, *SUPPORTED_REQUEST_TYPES),
            ).fetchone()
        return _request_row_to_dict(row) if row else None

    def list_all(self, limit: int = 200) -> list[dict]:
        bounded = max(1, min(limit, 1000))
        placeholders = _supported_type_placeholders()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM workflow_requests
                WHERE type IN ({placeholders})
                ORDER BY created_at DESC LIMIT ?
                """,
                (*SUPPORTED_REQUEST_TYPES, bounded),
            ).fetchall()
        return [_request_row_to_dict(row) for row in rows]

    def confirm_draft(
        self,
        request_id: str,
        actor: str,
        fields: dict,
    ) -> dict:
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_request(conn, request_id)
            if row["applicant"] != actor:
                raise WorkflowPermissionError("Only the applicant can submit this draft.")
            if row["status"] != "draft":
                target = "reported" if row["type"] == "sick_leave" else "in_review"
                raise InvalidTransitionError(row["status"], target)

            request_type = str(fields.get("type") or row["type"]).strip().lower()
            start_date = optional_string(fields.get("start_date", row["start_date"]))
            end_date = optional_string(fields.get("end_date", row["end_date"]))
            comment = str(fields.get("comment", row["comment"])).strip()
            approver = str(row["approver"])
            current_details = _load_json_object(row["details"])
            details_value = fields["details"] if "details" in fields else current_details
            details = normalize_request_details(request_type, details_value)
            end_date = request_end_date(request_type, start_date, end_date, details)
            errors = validate_request_fields(
                request_type,
                start_date,
                end_date,
                comment,
                approver,
                details,
            )
            if errors:
                raise WorkflowValidationError(errors)
            duration = duration_days(start_date, end_date)
            target_status = "reported" if request_type == "sick_leave" else "in_review"
            now = utc_now()
            conn.execute(
                """
                UPDATE workflow_requests
                SET type = ?, start_date = ?, end_date = ?, duration_days = ?, comment = ?,
                    approver = ?, details = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    request_type,
                    start_date,
                    end_date,
                    duration,
                    comment,
                    approver,
                    json.dumps(details, ensure_ascii=False),
                    target_status,
                    now,
                    request_id,
                ),
            )
            self._insert_event(
                conn,
                request_id,
                "status_changed",
                "draft",
                target_status,
                actor,
                {"confirmed_fields": True},
            )
            conn.commit()
        result = self.get_request(request_id)
        assert result is not None
        return result

    def transition(
        self,
        request_id: str,
        target_status: str,
        actor: str,
        comment: str = "",
    ) -> dict:
        normalized_target = target_status.strip().lower()
        if normalized_target not in VALID_STATUSES:
            raise WorkflowValidationError(["The requested workflow status is not supported."])
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_request(conn, request_id)
            current = row["status"]
            allowed = REQUEST_TRANSITIONS.get(row["type"], {}).get(current, set())
            if normalized_target not in allowed:
                raise InvalidTransitionError(current, normalized_target)
            now = utc_now()
            conn.execute(
                "UPDATE workflow_requests SET status = ?, updated_at = ? WHERE id = ?",
                (normalized_target, now, request_id),
            )
            self._insert_event(
                conn,
                request_id,
                "status_changed",
                current,
                normalized_target,
                actor,
                {"comment": comment.strip()} if comment.strip() else {},
            )
            conn.commit()
        result = self.get_request(request_id)
        assert result is not None
        return result

    def add_comment(self, request_id: str, author: str, body: str) -> dict:
        cleaned = body.strip()
        if not cleaned:
            raise WorkflowValidationError(["Comment cannot be empty."])
        comment_id = uuid.uuid4().hex
        created_at = utc_now()
        with closing(self._connect()) as conn:
            row = self._require_request(conn, request_id)
            conn.execute(
                """
                INSERT INTO request_comments (id, request_id, author, body, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (comment_id, request_id, author, cleaned, created_at),
            )
            self._insert_event(
                conn,
                request_id,
                "comment_added",
                row["status"],
                row["status"],
                author,
                {"comment_id": comment_id},
            )
            conn.commit()
        return {
            "id": comment_id,
            "request_id": request_id,
            "author": author,
            "body": cleaned,
            "created_at": created_at,
        }

    def delete_draft(self, request_id: str, applicant: str) -> bool:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                DELETE FROM workflow_requests
                WHERE id = ? AND applicant = ? AND status = 'draft'
                """,
                (request_id, normalize_user_id(applicant, "anonymous")),
            )
            conn.commit()
        return cursor.rowcount == 1

    def list_events(self, request_id: str) -> list[dict]:
        with closing(self._connect()) as conn:
            self._require_request(conn, request_id)
            rows = conn.execute(
                "SELECT * FROM request_events WHERE request_id = ? ORDER BY created_at, rowid",
                (request_id,),
            ).fetchall()
        return [_event_row_to_dict(row) for row in rows]

    def list_comments(self, request_id: str) -> list[dict]:
        with closing(self._connect()) as conn:
            self._require_request(conn, request_id)
            rows = conn.execute(
                "SELECT * FROM request_comments WHERE request_id = ? ORDER BY created_at, rowid",
                (request_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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
        placeholders = _supported_type_placeholders()
        with closing(self._connect()) as conn:
            total_requests = conn.execute(
                f"SELECT COUNT(*) FROM workflow_requests WHERE type IN ({placeholders})",
                SUPPORTED_REQUEST_TYPES,
            ).fetchone()[0]
            by_status = {
                row["status"]: row["count"]
                for row in conn.execute(
                    f"""
                    SELECT status, COUNT(*) AS count FROM workflow_requests
                    WHERE type IN ({placeholders})
                    GROUP BY status
                    """,
                    SUPPORTED_REQUEST_TYPES,
                ).fetchall()
            }
            by_type = {
                row["type"]: row["count"]
                for row in conn.execute(
                    f"""
                    SELECT type, COUNT(*) AS count FROM workflow_requests
                    WHERE type IN ({placeholders})
                    GROUP BY type
                    """,
                    SUPPORTED_REQUEST_TYPES,
                ).fetchall()
            }
            counts = {}
            for table in (
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
            conn.execute(
                """
                INSERT INTO assistant_feedback
                (id, user_id, rating, comment, question, answer, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    "anonymous",
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

    @staticmethod
    def _require_request(conn: sqlite3.Connection, request_id: str) -> sqlite3.Row:
        placeholders = _supported_type_placeholders()
        row = conn.execute(
            f"""
            SELECT * FROM workflow_requests
            WHERE id = ? AND type IN ({placeholders})
            """,
            (request_id, *SUPPORTED_REQUEST_TYPES),
        ).fetchone()
        if not row:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return row


def _request_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "type_label": REQUEST_TYPE_LABELS.get(row["type"], row["type"]),
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "duration_days": row["duration_days"],
        "comment": row["comment"],
        "applicant": row["applicant"],
        "approver": row["approver"],
        "details": _load_json_object(row["details"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _event_row_to_dict(row: sqlite3.Row) -> dict:
    try:
        details = json.loads(row["details"])
    except (json.JSONDecodeError, TypeError):
        details = {}
    return {
        "id": row["id"],
        "request_id": row["request_id"],
        "event_type": row["event_type"],
        "from_status": row["from_status"],
        "to_status": row["to_status"],
        "actor": row["actor"],
        "details": details,
        "created_at": row["created_at"],
    }


def _supported_type_placeholders() -> str:
    return ", ".join("?" for _ in SUPPORTED_REQUEST_TYPES)


def _load_json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
