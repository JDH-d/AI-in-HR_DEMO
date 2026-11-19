from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

VALID_TYPES = {"pto", "sick_leave", "document"}
TYPE_LABELS = {
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


class WorkflowDecisionError(WorkflowError):
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
    title: str = ""
    priority: str = "normal"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_user(value: str | None, default: str) -> str:
    return " ".join((value or "").split()).strip() or default


def duration_days(start_date: str | None, end_date: str | None) -> int | None:
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
            applicant=normalize_user(applicant, "anonymous"),
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
