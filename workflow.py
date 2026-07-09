from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

VALID_STATUSES = {"new", "pending", "approved", "declined", "done"}
VALID_TYPES = {"PTO", "Sick", "Document"}


@dataclass(frozen=True)
class WorkflowScenario:
    request_type: str
    assigned_to: str


_REQUEST_PATTERNS = [
    re.compile(
        r"\b(i\s+want|i\s+need|i\s+would\s+like|please|request|apply|submit)\b",
        re.IGNORECASE,
    ),
]

_SCENARIOS: List[tuple[WorkflowScenario, List[re.Pattern[str]], bool]] = [
    (
        WorkflowScenario(request_type="PTO", assigned_to="Manager"),
        [
            re.compile(r"\bpto\b", re.IGNORECASE),
            re.compile(r"\bvacation\b", re.IGNORECASE),
            re.compile(r"\btime\s+off\b", re.IGNORECASE),
            re.compile(r"\bannual\s+leave\b", re.IGNORECASE),
            re.compile(r"\bpersonal\s+leave\b", re.IGNORECASE),
            re.compile(r"\b(?<!sick )leave\b", re.IGNORECASE),
        ],
        True,
    ),
    (
        WorkflowScenario(request_type="Sick", assigned_to="Manager"),
        [
            re.compile(r"\bsick\s+leave\b", re.IGNORECASE),
            re.compile(r"\bsick\s+day\b", re.IGNORECASE),
            re.compile(r"\bcall(?:ing)?\s+in\s+sick\b", re.IGNORECASE),
        ],
        True,
    ),
    (
        WorkflowScenario(request_type="Document", assigned_to="HR"),
        [
            re.compile(r"\bcertificate\b", re.IGNORECASE),
            re.compile(r"\bletter\b", re.IGNORECASE),
            re.compile(r"\bdocument\b", re.IGNORECASE),
            re.compile(r"\bdocument\s+request\b", re.IGNORECASE),
        ],
        False,
    ),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_period_or_date(text: str) -> str:
    if not text:
        return "unspecified"
    range_match = re.search(
        r"(?:from)\s+\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\s+"
        r"(?:to)\s+\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?",
        text,
        flags=re.IGNORECASE,
    )
    if range_match:
        return range_match.group(0).strip()
    date_match = re.search(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", text)
    if date_match:
        return date_match.group(0).strip()
    lowered = text.lower()
    for token in ("today", "tomorrow"):
        if token in lowered:
            return token
    return "unspecified"


def _match_scenario(text: str) -> Optional[WorkflowScenario]:
    if not text:
        return None
    period_or_date = _extract_period_or_date(text)
    has_request_intent = any(pattern.search(text) for pattern in _REQUEST_PATTERNS)
    for scenario, patterns, require_period in _SCENARIOS:
        if not any(pattern.search(text) for pattern in patterns):
            continue
        if not has_request_intent:
            continue
        if require_period and period_or_date == "unspecified":
            continue
        return scenario
    return None


class WorkflowStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self._init_with_fallback()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_requests (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    period_or_date TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_to TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _init_with_fallback(self) -> None:
        primary = self.db_path
        fallback = Path.cwd() / ".demo_state" / "workflow.db"
        candidates: List[Path] = [primary]
        if fallback != primary:
            candidates.append(fallback)

        last_error: Optional[Exception] = None
        for candidate in candidates:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                self.db_path = candidate
                self._init_db()
                self._verify_writable()
                return
            except sqlite3.Error as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error

    def _verify_writable(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA user_version = 1")
            conn.commit()

    def create_request(
        self,
        request_type: str,
        created_by: str,
        period_or_date: str,
        comment: str,
        status: str,
        assigned_to: str,
    ) -> dict:
        request_id = uuid.uuid4().hex
        created_at = _utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO workflow_requests
                (id, type, created_by, period_or_date, comment, status, assigned_to, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    request_type,
                    created_by,
                    period_or_date,
                    comment,
                    status,
                    assigned_to,
                    created_at,
                ),
            )
            conn.commit()
        return {
            "id": request_id,
            "type": request_type,
            "created_by": created_by,
            "period_or_date": period_or_date,
            "comment": comment,
            "status": status,
            "assigned_to": assigned_to,
            "created_at": created_at,
        }

    def list_by_user(self, created_by: str) -> List[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, type, created_by, period_or_date, comment, status, assigned_to, created_at
                FROM workflow_requests
                WHERE created_by = ?
                ORDER BY created_at DESC
                """,
                (created_by,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_all(self, limit: int = 200) -> List[dict]:
        bounded = max(1, min(limit, 1000))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, type, created_by, period_or_date, comment, status, assigned_to, created_at
                FROM workflow_requests
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def update_status(self, request_id: str, status: str) -> Optional[dict]:
        if status not in VALID_STATUSES:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT id, type, created_by, period_or_date, comment, status, assigned_to, created_at
                FROM workflow_requests
                WHERE id = ?
                """,
                (request_id,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE workflow_requests SET status = ? WHERE id = ?",
                (status, request_id),
            )
            conn.commit()
        data = _row_to_dict(row)
        data["status"] = status
        return data


class WorkflowService:
    def __init__(self, db_path: str) -> None:
        self.store = WorkflowStore(db_path)

    def try_create(self, text: str, created_by: str) -> Optional[dict]:
        scenario = _match_scenario(text)
        if not scenario:
            return None
        return self.store.create_request(
            request_type=scenario.request_type,
            created_by=created_by or "anonymous",
            period_or_date=_extract_period_or_date(text),
            comment=text.strip(),
            status="pending",
            assigned_to=scenario.assigned_to,
        )

    def list_for_user(self, created_by: str) -> List[dict]:
        return self.store.list_by_user(created_by or "anonymous")

    def list_all(self, limit: int = 200) -> List[dict]:
        return self.store.list_all(limit=limit)

    def update_status(self, request_id: str, status: str) -> Optional[dict]:
        return self.store.update_status(request_id, status)


def _row_to_dict(row: tuple) -> dict:
    return {
        "id": row[0],
        "type": row[1],
        "created_by": row[2],
        "period_or_date": row[3],
        "comment": row[4],
        "status": row[5],
        "assigned_to": row[6],
        "created_at": row[7],
    }
