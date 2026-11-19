"""Shared, human-driven request procedure. No demographic eligibility rules."""

from domain.workflow import WorkflowNotFoundError, WorkflowPermissionError, WorkflowValidationError

STATUSES = (
    "draft",
    "submitted",
    "in_review",
    "needs_information",
    "approved",
    "rejected",
    "cancelled",
    "completed",
)
PRIORITIES = ("low", "normal", "high", "urgent")
POLICY_VERSION = "request-procedure-v1"
PROCEDURE = (
    "The same review procedure applies to every employee. Decisions must explain the relevant "
    "policy or objective criteria and the request-specific reason. Personal or protected characteristics "
    "must not determine a decision. Do not include diagnoses, identity documents or unrelated personal "
    "information. You may add evidence, respond to questions and request reconsideration of a decision. "
    "Reconsideration returns the request to the assigned manager; it is not an independent appeal tribunal. "
    "Earlier decisions and all changes remain visible to the author and assigned manager."
)
# action: (role, permitted source states, destination)
ACTIONS = {
    "submit": ("employee", {"draft"}, "submitted"),
    "start_review": ("manager", {"submitted"}, "in_review"),
    "request_information": ("manager", {"in_review"}, "needs_information"),
    "provide_information": ("employee", {"needs_information"}, "in_review"),
    "approve": ("manager", {"in_review"}, "approved"),
    "reject": ("manager", {"in_review"}, "rejected"),
    "cancel": ("employee", {"draft", "submitted", "in_review", "needs_information"}, "cancelled"),
    "complete": ("manager", {"approved"}, "completed"),
    "appeal": ("employee", {"approved", "rejected", "completed"}, "submitted"),
}
FINAL_STATUSES = {"approved", "rejected", "completed", "cancelled"}


class RequestConflictError(RuntimeError):
    pass


def require_visible(request: dict, user_id: str, role: str) -> None:
    visible = (role == "employee" and request["applicant"] == user_id) or (
        role == "manager"
        and request["approver"] == user_id
        and request["status"] != "draft"
        and request.get("was_submitted", False)
    )
    if not visible:
        raise WorkflowNotFoundError("The request could not be found or is not available to you.")


def allowed_actions(request: dict, user_id: str, role: str) -> list[str]:
    require_visible(request, user_id, role)
    if role == "manager" and request["applicant"] == user_id:
        return []
    return [
        action
        for action, (required_role, sources, _) in ACTIONS.items()
        if role == required_role and request["status"] in sources
    ]


def require_revision(request: dict, revision: int) -> None:
    if request["revision"] != revision:
        raise RequestConflictError(
            "This request changed. Reload it and review the latest information before retrying."
        )


def require_text(value: str, label: str, minimum: int = 3, maximum: int = 10000) -> str:
    cleaned = value.strip()
    if not minimum <= len(cleaned) <= maximum:
        raise WorkflowValidationError([f"{label} must contain {minimum}–{maximum} characters."])
    return cleaned


def require_participant_write(request: dict, user_id: str, role: str) -> None:
    require_visible(request, user_id, role)
    if role == "manager" and request["applicant"] == user_id:
        raise WorkflowPermissionError("Managers cannot act on their own requests.")
