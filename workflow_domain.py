from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

SUPPORTED_REQUEST_TYPES = ("pto", "sick_leave")
VALID_TYPES = frozenset(SUPPORTED_REQUEST_TYPES)
VALID_STATUSES = {
    "draft",
    "in_review",
    "reported",
    "acknowledged",
    "approved",
    "declined",
    "cancelled",
}
REQUEST_TRANSITIONS = {
    "pto": {
        "draft": {"in_review", "cancelled"},
        "in_review": {"approved", "declined", "cancelled"},
        "approved": set(),
        "declined": set(),
        "cancelled": set(),
    },
    "sick_leave": {
        "draft": {"reported", "cancelled"},
        "reported": {"acknowledged", "cancelled"},
        "acknowledged": set(),
        "cancelled": set(),
    },
}

REQUEST_TYPE_LABELS = {
    "pto": "PTO",
    "sick_leave": "Sick leave",
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
_US_DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2}/\d{1,2}/\d{4})(?!\d)")


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
    details: dict[str, object] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_user_id(value: str | None, default: str) -> str:
    return " ".join((value or "").split()).strip() or default


def duration_days(start_date: str | None, end_date: str | None) -> int | None:
    if not start_date or not end_date:
        return None
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return (end - start).days + 1


def _default_sick_leave_details(
    start_date: str | None,
    end_date: str | None,
) -> dict[str, object]:
    expected_return_date: str | None = None
    if start_date:
        try:
            last_day_away = date.fromisoformat(end_date or start_date)
            expected_return_date = (last_day_away + timedelta(days=1)).isoformat()
        except ValueError:
            expected_return_date = None
    return {
        "expected_return_date": expected_return_date,
        "expected_return_unknown": expected_return_date is None,
        "time_away": "full_day",
        "partial_hours": None,
        "extended_or_recurring": False,
    }


def normalize_request_details(
    request_type: str,
    details: dict[str, object] | None,
) -> dict[str, object]:
    if request_type != "sick_leave":
        return {}
    source = details or {}
    return_unknown = source.get("expected_return_unknown") is True
    return {
        "expected_return_date": (
            None if return_unknown else optional_string(source.get("expected_return_date"))
        ),
        "expected_return_unknown": return_unknown,
        "time_away": source.get("time_away"),
        "partial_hours": source.get("partial_hours"),
        "extended_or_recurring": source.get("extended_or_recurring") is True,
    }


def request_end_date(
    request_type: str,
    start_date: str | None,
    end_date: str | None,
    details: dict[str, object],
) -> str | None:
    if request_type != "sick_leave":
        return end_date
    if details.get("expected_return_unknown") is True:
        return None
    expected_return = optional_string(details.get("expected_return_date"))
    if not start_date or not expected_return:
        return end_date
    try:
        start = date.fromisoformat(start_date)
        last_day_away = date.fromisoformat(expected_return) - timedelta(days=1)
    except ValueError:
        return end_date
    return max(start, last_day_away).isoformat()


def validate_request_fields(
    request_type: str,
    start_date: str | None,
    end_date: str | None,
    comment: str,
    approver: str,
    details: dict[str, object] | None = None,
) -> list[str]:
    errors: list[str] = []
    if request_type not in VALID_TYPES:
        errors.append("Request type is not supported.")
    if request_type != "sick_leave" and not comment.strip():
        errors.append("Comment is required.")
    if not approver.strip():
        errors.append("Approver is required.")

    parsed_start: date | None = None
    parsed_end: date | None = None
    for field_name, value in (("Start date", start_date), ("End date", end_date)):
        if not value:
            required = request_type == "pto" or (
                request_type == "sick_leave" and field_name == "Start date"
            )
            if required:
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

    if request_type == "sick_leave":
        sick_details = details or {}
        time_away = sick_details.get("time_away")
        if time_away not in ("full_day", "partial_day"):
            errors.append("Choose whether you will be away for a full or partial day.")

        expected_return_unknown = sick_details.get("expected_return_unknown") is True
        expected_return_value = optional_string(sick_details.get("expected_return_date"))
        expected_return: date | None = None
        if not expected_return_unknown and not expected_return_value:
            errors.append("Choose an expected return date or select Not sure yet.")
        if expected_return_value:
            try:
                expected_return = date.fromisoformat(expected_return_value)
            except ValueError:
                errors.append("Expected return must be a real calendar date in YYYY-MM-DD format.")

        if parsed_start and expected_return:
            if time_away == "full_day" and expected_return <= parsed_start:
                errors.append("Expected return must be after the first full day away.")
            if time_away == "partial_day" and expected_return < parsed_start:
                errors.append("Expected return cannot be before the first day away.")

        partial_hours = sick_details.get("partial_hours")
        if time_away == "partial_day":
            valid_hours = (
                isinstance(partial_hours, (int, float))
                and not isinstance(partial_hours, bool)
                and 0 < partial_hours <= 24
            )
            if not valid_hours:
                errors.append("Partial-day hours must be greater than 0 and no more than 24.")
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
        approver = "manager.demo"
        details = (
            _default_sick_leave_details(start_date, end_date)
            if request_type == "sick_leave"
            else {}
        )
        comment = "" if request_type == "sick_leave" else text.strip()
        end_date = request_end_date(request_type, start_date, end_date, details)
        errors = date_errors + validate_request_fields(
            request_type=request_type,
            start_date=start_date,
            end_date=end_date,
            comment=comment,
            approver=approver,
            details=details,
        )
        return WorkflowDraftData(
            request_type=request_type,
            start_date=start_date,
            end_date=end_date,
            comment=comment,
            applicant=normalize_user_id(applicant, "anonymous"),
            approver=approver,
            details=details,
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
            (match.start(), match.group(1), "%m/%d/%Y")
            for match in _US_DATE_PATTERN.finditer(text or "")
        )
        for _, token, date_format in sorted(matches):
            try:
                parsed_dates.append(datetime.strptime(token, date_format).date())
            except ValueError:
                invalid_tokens.append(token)
                parsed_dates.append(None)

        dates: list[date | None] = parsed_dates or relative_dates
        start = dates[0] if dates else None
        end = (dates[1] if len(dates) > 1 else dates[0]) if dates else None
        start_date = start.isoformat() if start else None
        end_date = end.isoformat() if end else None
        errors = [
            f"Invalid calendar date: {token}. Use YYYY-MM-DD or MM/DD/YYYY."
            for token in invalid_tokens
        ]
        return start_date, end_date, errors


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
