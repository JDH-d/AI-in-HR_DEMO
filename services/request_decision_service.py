from __future__ import annotations

from services.auth_service import DemoIdentity
from workflow import (
    InvalidTransitionError,
    WorkflowPermissionError,
    WorkflowService,
    WorkflowValidationError,
)


def decide_request(
    workflow_service: WorkflowService,
    *,
    request_id: str,
    target: str,
    identity: DemoIdentity,
    comment: str = "",
) -> dict:
    if identity.role != "manager":
        raise WorkflowPermissionError("Only managers can decide workflow requests.")

    normalized_target = target.strip().lower()
    if normalized_target not in {"approved", "declined"}:
        raise WorkflowValidationError(["Unsupported manager decision."])
    if normalized_target == "declined" and not comment.strip():
        raise WorkflowValidationError(
            ["A manager comment is required when declining a request."]
        )

    cleaned_request_id = request_id.strip()
    request = workflow_service.history(cleaned_request_id)["request"]
    if request["status"] != "in_review":
        raise InvalidTransitionError(request["status"], normalized_target)

    workflow_service.transition(
        cleaned_request_id,
        normalized_target,
        actor=identity.id,
        comment=comment.strip(),
    )
    persisted_request = workflow_service.history(cleaned_request_id)["request"]
    if persisted_request["status"] != normalized_target:
        raise WorkflowValidationError(
            ["The saved request status could not be confirmed. Open it in Web."]
        )
    return persisted_request
