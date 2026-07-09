from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

VALID_TYPES = {"pto", "sick_leave", "document"}
VALID_STATUSES = {
    "draft",
    "submitted",
    "in_review",
    "approved",
    "declined",
    "completed",
    "cancelled",
}
ALLOWED_TRANSITIONS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"in_review", "cancelled"},
    "in_review": {"approved", "declined", "cancelled"},
    "approved": {"completed"},
    "declined": set(),
    "completed": set(),
    "cancelled": set(),
}

_TYPE_LABELS = {
    "pto": "PTO",
    "sick_leave": "Sick leave",
    "document": "Document",
}
_TYPE_TERMS = {
    "sick_leave": ("sick leave", "sick day", "calling in sick", "call in sick"),
    "pto": (
        "pto",
        "vacation",
        "time off",
        "annual leave",
        "personal leave",
        "leave request",
        " leave ",
    ),
    "document": (
        "document request",
        "employment letter",
        "employment certificate",
        "certificate",
        "letter",
        "document",
    ),
}
_ACTION_PHRASES = (
    "i need",
    "i want",
    "i would like",
    "i'd like",
    "please create",
    "please submit",
    "please request",
    "apply for",
    "submit a",
    "submit my",
    "create a",
    "create my",
    "request pto",
    "request vacation",
    "request sick",
    "request time off",
)
_QUESTION_PREFIXES = (
    "how ",
    "what ",
    "when ",
    "where ",
    "why ",
    "who ",
    "can i ",
    "could i ",
    "do i ",
    "does ",
    "is ",
    "are ",
    "tell me ",
    "explain ",
)
_KNOWLEDGE_MARKERS = (
    " policy",
    "policies",
    "to know",
    "information about",
    "details about",
    "rules for",
    "explain",
    "how does",
    "how do",
    "what is",
    "when can",
    "am i eligible",
)
_ISO_DATE_PATTERN = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_DMY_DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2}[./]\d{1,2}[./]\d{4})(?!\d)")


class WorkflowError(RuntimeError):
    pass


class WorkflowNotFoundError(WorkflowError):
    pass


class WorkflowPermissionError(WorkflowError):
    pass


class WorkflowValidationError(WorkflowError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class InvalidTransitionError(WorkflowError):
    def __init__(self, current_status: str, target_status: str) -> None:
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(f"Transition from {current_status} to {target_status} is not allowed")


@dataclass(frozen=True)
class WorkflowDraftData:
    request_type: str
    start_date: str | None
    end_date: str | None
    comment: str
    applicant: str
    approver: str
    validation_errors: list[str] = field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_user(value: str | None, default: str) -> str:
    return " ".join((value or "").split()).strip() or default


def _duration_days(start_date: str | None, end_date: str | None) -> int | None:
    if not start_date or not end_date:
        return None
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return (end - start).days + 1


def validate_request_fields(
    request_type: str,
    start_date: str | None,
    end_date: str | None,
    comment: str,
    approver: str,
) -> list[str]:
    errors: list[str] = []
    if request_type not in VALID_TYPES:
        errors.append("Request type is not supported.")
    if not comment.strip():
        errors.append("Comment is required.")
    if not approver.strip():
        errors.append("Approver is required.")

    parsed_start: date | None = None
    parsed_end: date | None = None
    for field_name, value in (("Start date", start_date), ("End date", end_date)):
        if not value:
            if request_type in {"pto", "sick_leave"}:
                errors.append(f"{field_name} is required.")
            continue
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            errors.append(f"{field_name} must be a real calendar date in YYYY-MM-DD format.")
            continue
        if field_name == "Start date":
            parsed_start = parsed
        else:
            parsed_end = parsed

    if parsed_start and parsed_end and parsed_end < parsed_start:
        errors.append("End date cannot be earlier than start date.")
    return errors


class WorkflowInterpreter:
    """Conservatively turns an explicit action request into structured draft fields."""

    def __init__(self, today_provider: Callable[[], date] | None = None) -> None:
        self.today_provider = today_provider or date.today

    def analyze(self, text: str, applicant: str) -> WorkflowDraftData | None:
        normalized = " ".join((text or "").lower().split())
        if not normalized or not self._is_explicit_action(normalized):
            return None

        request_type = self._detect_type(normalized)
        if request_type is None:
            return None

        start_date, end_date, date_errors = self._extract_dates(text)
        approver = "HR" if request_type == "document" else "Manager"
        errors = date_errors + validate_request_fields(
            request_type=request_type,
            start_date=start_date,
            end_date=end_date,
            comment=text,
            approver=approver,
        )
        return WorkflowDraftData(
            request_type=request_type,
            start_date=start_date,
            end_date=end_date,
            comment=text.strip(),
            applicant=_normalize_user(applicant, "anonymous"),
            approver=approver,
            validation_errors=list(dict.fromkeys(errors)),
        )

    @staticmethod
    def _is_explicit_action(normalized: str) -> bool:
        has_action = any(phrase in normalized for phrase in _ACTION_PHRASES)
        if not has_action:
            return False
        if any(marker in normalized for marker in _KNOWLEDGE_MARKERS):
            return False
        is_question = normalized.endswith("?") or normalized.startswith(_QUESTION_PREFIXES)
        return not is_question or normalized.startswith(
            ("please create", "please submit", "i need", "i want", "i would like", "i'd like")
        )

    @staticmethod
    def _detect_type(normalized: str) -> str | None:
        for request_type, terms in _TYPE_TERMS.items():
            if any(term in normalized for term in terms):
                return request_type
        return None

    def _extract_dates(self, text: str) -> tuple[str | None, str | None, list[str]]:
        lowered = (text or "").lower()
        relative_dates: list[date] = []
        today = self.today_provider()
        if "today" in lowered:
            relative_dates.append(today)
        if "tomorrow" in lowered:
            relative_dates.append(today + timedelta(days=1))

        parsed_dates: list[date | None] = []
        invalid_tokens: list[str] = []
        matches = [
            (match.start(), match.group(1), "%Y-%m-%d")
            for match in _ISO_DATE_PATTERN.finditer(text or "")
        ]
        matches.extend(
            (match.start(), match.group(1), "%d/%m/%Y")
            for match in _DMY_DATE_PATTERN.finditer((text or "").replace(".", "/"))
        )
        for _, token, date_format in sorted(matches):
            try:
                parsed_dates.append(datetime.strptime(token.replace(".", "/"), date_format).date())
            except ValueError:
                invalid_tokens.append(token)
                parsed_dates.append(None)

        dates: list[date | None] = parsed_dates or relative_dates
        start = dates[0] if dates else None
        end = (dates[1] if len(dates) > 1 else dates[0]) if dates else None
        start_date = start.isoformat() if start else None
        end_date = end.isoformat() if end else None
        errors = [f"Invalid calendar date: {token}. Use YYYY-MM-DD." for token in invalid_tokens]
        return start_date, end_date, errors


class WorkflowStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self._init_with_fallback()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_with_fallback(self) -> None:
        primary = self.db_path
        fallback = Path.cwd() / ".demo_state" / "workflow.db"
        candidates = [primary] + ([fallback] if fallback != primary else [])
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                self.db_path = candidate
                self._init_db()
                return
            except sqlite3.Error as exc:
                last_error = exc
        if last_error:
            raise last_error

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
                    created_at TEXT NOT NULL
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
            conn.execute("PRAGMA user_version = 2")
            conn.commit()

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
            "pending": "submitted",
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
            applicant = _normalize_user(data.get("created_by"), "anonymous")
            approver = _normalize_user(data.get("assigned_to"), "Manager")
            created_at = data.get("created_at") or _utc_now()
            status = status_map.get(str(data.get("status", "")).lower(), "submitted")
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
            ON CONFLICT(id) DO UPDATE SET
                display_name = excluded.display_name,
                role = CASE WHEN users.role = 'employee' THEN excluded.role ELSE users.role END,
                manager_id = COALESCE(users.manager_id, excluded.manager_id)
            """,
            (user_id, user_id, role, manager_id, _utc_now()),
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
                created_at or _utc_now(),
            ),
        )

    def create_draft(self, draft: WorkflowDraftData) -> dict:
        request_id = uuid.uuid4().hex
        created_at = _utc_now()
        duration = None
        try:
            duration = _duration_days(draft.start_date, draft.end_date)
        except ValueError:
            pass
        with closing(self._connect()) as conn:
            self._ensure_user(conn, draft.applicant, "employee", draft.approver)
            self._ensure_user(conn, draft.approver, "approver")
            conn.execute(
                """
                INSERT INTO workflow_requests
                (id, type, start_date, end_date, duration_days, comment, applicant, approver,
                 status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
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
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM workflow_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return _request_row_to_dict(row) if row else None

    def list_by_user(self, applicant: str) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_requests
                WHERE applicant = ?
                ORDER BY created_at DESC
                """,
                (_normalize_user(applicant, "anonymous"),),
            ).fetchall()
        return [_request_row_to_dict(row) for row in rows]

    def list_all(self, limit: int = 200) -> list[dict]:
        bounded = max(1, min(limit, 1000))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_requests ORDER BY created_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return [_request_row_to_dict(row) for row in rows]

    def confirm_draft(
        self,
        request_id: str,
        actor: str,
        fields: dict,
    ) -> dict:
        with closing(self._connect()) as conn:
            row = self._require_request(conn, request_id)
            if row["applicant"] != actor:
                raise WorkflowPermissionError("Only the applicant can submit this draft.")
            if row["status"] != "draft":
                raise InvalidTransitionError(row["status"], "submitted")

            request_type = str(fields.get("type") or row["type"]).strip().lower()
            start_date = _optional_string(fields.get("start_date", row["start_date"]))
            end_date = _optional_string(fields.get("end_date", row["end_date"]))
            comment = str(fields.get("comment", row["comment"])).strip()
            approver = str(fields.get("approver", row["approver"])).strip()
            errors = validate_request_fields(request_type, start_date, end_date, comment, approver)
            if errors:
                raise WorkflowValidationError(errors)
            duration = _duration_days(start_date, end_date)
            now = _utc_now()
            self._ensure_user(conn, approver, "approver")
            conn.execute(
                """
                UPDATE workflow_requests
                SET type = ?, start_date = ?, end_date = ?, duration_days = ?, comment = ?,
                    approver = ?, status = 'submitted', updated_at = ?
                WHERE id = ?
                """,
                (
                    request_type,
                    start_date,
                    end_date,
                    duration,
                    comment,
                    approver,
                    now,
                    request_id,
                ),
            )
            self._insert_event(
                conn,
                request_id,
                "status_changed",
                "draft",
                "submitted",
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
            row = self._require_request(conn, request_id)
            current = row["status"]
            if normalized_target not in ALLOWED_TRANSITIONS.get(current, set()):
                raise InvalidTransitionError(current, normalized_target)
            now = _utc_now()
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
        created_at = _utc_now()
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
        created_at = _utc_now()
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
    ) -> dict:
        if rating < 1 or rating > 5:
            raise WorkflowValidationError(["Rating must be between 1 and 5."])
        feedback_id = uuid.uuid4().hex
        created_at = _utc_now()
        with closing(self._connect()) as conn:
            self._ensure_user(conn, user_id, "employee")
            conn.execute(
                """
                INSERT INTO assistant_feedback
                (id, user_id, rating, comment, question, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (feedback_id, user_id, rating, comment.strip(), question.strip(), created_at),
            )
            conn.commit()
        return {
            "id": feedback_id,
            "user_id": user_id,
            "rating": rating,
            "comment": comment.strip(),
            "question": question.strip(),
            "created_at": created_at,
        }

    @staticmethod
    def _require_request(conn: sqlite3.Connection, request_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM workflow_requests WHERE id = ?", (request_id,)).fetchone()
        if not row:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return row


class WorkflowService:
    def __init__(
        self,
        db_path: str,
        interpreter: WorkflowInterpreter | None = None,
    ) -> None:
        self.store = WorkflowStore(db_path)
        self.interpreter = interpreter or WorkflowInterpreter()

    def prepare_draft(self, text: str, applicant: str) -> dict | None:
        draft = self.interpreter.analyze(text, applicant)
        if draft is None:
            return None
        return self.store.create_draft(draft)

    def create_structured_draft(
        self,
        *,
        request_type: str,
        start_date: str | None,
        end_date: str | None,
        comment: str,
        applicant: str,
        approver: str,
    ) -> dict:
        errors = validate_request_fields(
            request_type,
            start_date,
            end_date,
            comment,
            approver,
        )
        if errors:
            raise WorkflowValidationError(errors)
        return self.store.create_draft(
            WorkflowDraftData(
                request_type=request_type,
                start_date=start_date,
                end_date=end_date,
                comment=comment.strip(),
                applicant=_normalize_user(applicant, "anonymous"),
                approver=_normalize_user(approver, "manager.demo"),
            )
        )

    def confirm_draft(self, request_id: str, applicant: str, fields: dict) -> dict:
        return self.store.confirm_draft(
            request_id,
            _normalize_user(applicant, "anonymous"),
            fields,
        )

    def cancel(self, request_id: str, applicant: str, comment: str = "") -> dict:
        request = self.get_for_user(request_id, applicant)
        if request is None:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return self.store.transition(
            request_id,
            "cancelled",
            _normalize_user(applicant, "anonymous"),
            comment,
        )

    def get_for_user(self, request_id: str, applicant: str) -> dict | None:
        request = self.store.get_request(request_id)
        if not request:
            return None
        if request["applicant"] != _normalize_user(applicant, "anonymous"):
            return None
        return request

    def list_for_user(self, applicant: str) -> list[dict]:
        return self.store.list_by_user(applicant)

    def list_all(self, limit: int = 200) -> list[dict]:
        return self.store.list_all(limit=limit)

    def transition(
        self,
        request_id: str,
        status: str,
        actor: str = "admin",
        comment: str = "",
    ) -> dict:
        return self.store.transition(request_id, status, actor, comment)

    def add_manager_comment(self, request_id: str, author: str, body: str) -> dict:
        return self.store.add_comment(request_id, author, body)

    def history(self, request_id: str) -> dict:
        request = self.store.get_request(request_id)
        if not request:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return {
            "request": request,
            "events": self.store.list_events(request_id),
            "comments": self.store.list_comments(request_id),
        }

    def add_feedback(
        self,
        request_id: str,
        user_id: str,
        rating: int,
        comment: str = "",
    ) -> dict:
        if self.get_for_user(request_id, user_id) is None:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return self.store.add_feedback(request_id, user_id, rating, comment)

    def metrics(self) -> dict:
        return self.store.metrics()

    def add_assistant_feedback(
        self,
        user_id: str,
        rating: int,
        comment: str = "",
        question: str = "",
    ) -> dict:
        return self.store.add_assistant_feedback(user_id, rating, comment, question)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _request_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "type_label": _TYPE_LABELS.get(row["type"], row["type"]),
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "duration_days": row["duration_days"],
        "comment": row["comment"],
        "applicant": row["applicant"],
        "approver": row["approver"],
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
