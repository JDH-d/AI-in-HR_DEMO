"""Read-only manager attention rules; deadlines never alter request history."""

from datetime import datetime, timedelta, timezone

REVIEW_DAYS = 5
REVIEW_POLICY_DESCRIPTION = (
    "Review within 5 calendar days after submission, reconsideration or an employee reply. "
    "Waiting for employee information pauses review. Starting review, comments and reassignment "
    "do not restart the clock. Older requests without a submission event use their creation time."
)


def as_utc(value: str | datetime | None) -> datetime | None:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value or "")
    except (ValueError, TypeError):
        return None
    return (
        result.replace(tzinfo=timezone.utc)
        if result.tzinfo is None
        else result.astimezone(timezone.utc)
    )


def attention_for_request(request: dict, anchor: dict | None, now: datetime) -> dict:
    result = {"due_at": None, "overdue": False, "reasons": []}
    if request["status"] not in {"submitted", "in_review"}:
        return result
    started = as_utc((anchor or {}).get("created_at")) or as_utc(request["created_at"])
    if started:
        due = started + timedelta(days=REVIEW_DAYS)
        result["due_at"] = due.isoformat()
        result["overdue"] = now > due
        if result["overdue"]:
            result["reasons"].append("overdue")
    if request["priority"] in {"urgent", "high"}:
        result["reasons"].append("high_priority")
    if request["review_round"] > 1:
        result["reasons"].append("reconsideration")
    if (anchor or {}).get("event_type") == "provide_information":
        result["reasons"].append("employee_reply")
    return result
