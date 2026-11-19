"""Audience-specific request notifications, independent of providers and storage."""

from domain.request_policy import require_visible
from domain.workflow import WorkflowNotFoundError

AUDIENCES = ("employee", "manager")
_CURRENT_STATES = {
    "new_request": {"submitted"},
    "information_requested": {"needs_information"},
    "information_provided": {"in_review"},
    "reconsideration_requested": {"submitted"},
    "assigned": {"submitted", "in_review", "needs_information"},
    "cancelled": {"cancelled"},
}


def has_recipient(payload: dict) -> bool:
    """Legacy channel broadcasts deliberately do not have a valid route."""
    return (
        isinstance(payload, dict)
        and payload.get("audience") in AUDIENCES
        and isinstance(payload.get("recipient_id"), str)
        and bool(payload["recipient_id"].strip())
    )


def is_current_recipient(payload: dict, request: dict | None = None) -> bool:
    if not has_recipient(payload):
        return False
    if payload.get("kind") == "test":
        return True
    kind = payload.get("kind")
    if (
        not request
        or not isinstance(kind, str)
        or kind not in _CURRENT_STATES
        or request["status"] not in _CURRENT_STATES[kind]
    ):
        return False
    if payload.get("request_id") != request["id"]:
        return False
    audience = "employee" if kind == "information_requested" else "manager"
    if payload["audience"] != audience:
        return False
    if audience == "manager" and request["applicant"] == payload["recipient_id"]:
        return False
    try:
        require_visible(request, payload["recipient_id"], audience)
    except WorkflowNotFoundError:
        return False
    return True


def notification_for_event(event: dict, request: dict) -> dict | None:
    """Return one intended recipient, or no message for unrelated/obsolete events."""
    event_type = event.get("event_type")
    before, after = event.get("from_status"), event.get("to_status")
    employee_action = event.get("actor") == request["applicant"]
    audience, recipient = "manager", request["approver"]
    if (
        event_type == "request_information"
        and before == "in_review"
        and after == "needs_information"
    ):
        if event.get("actor") != request["approver"]:
            return None
        kind, audience, recipient = "information_requested", "employee", request["applicant"]
    elif (
        event_type == "status_changed"
        and before == "draft"
        and after == "submitted"
        and employee_action
    ):
        kind = "new_request"
    elif (
        event_type == "provide_information"
        and before == "needs_information"
        and after == "in_review"
        and employee_action
    ):
        kind = "information_provided"
    elif (
        event_type == "reconsideration_requested"
        and before in {"approved", "rejected", "completed"}
        and after == "submitted"
        and employee_action
    ):
        kind = "reconsideration_requested"
    elif event_type == "assignee_changed":
        details = event.get("details") or {}
        changes = details.get("changes", {}) if isinstance(details, dict) else {}
        assignment = changes.get("approver", {}) if isinstance(changes, dict) else {}
        if (
            not isinstance(assignment, dict)
            or assignment.get("after") != recipient
            or assignment.get("before") in {None, recipient}
            or event.get("actor") != assignment["before"]
        ):
            return None
        kind = "assigned"
    elif (
        event_type == "status_changed"
        and before in {"submitted", "in_review", "needs_information"}
        and after == "cancelled"
        and employee_action
    ):
        kind = "cancelled"
    else:
        return None
    payload = {
        "kind": kind,
        "audience": audience,
        "recipient_id": recipient,
        "number": request["number"],
        "request_id": request["id"],
        "from_status": before,
        "to_status": after,
        "occurred_at": event["created_at"],
    }
    return payload if is_current_recipient(payload, request) else None
