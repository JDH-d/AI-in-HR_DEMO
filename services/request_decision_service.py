from __future__ import annotations

from services.auth_service import DemoIdentity
from workflow import (
    InvalidTransitionError,
    WorkflowNotFoundError,
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
    request = next(
        (
            item
            for item in workflow_service.list_all(limit=1000)
            if item["id"] == cleaned_request_id
        ),
        None,
    )
    if request is None:
        raise WorkflowNotFoundError("The workflow request could not be found.")
    if request["status"] != "in_review":
        raise InvalidTransitionError(request["status"], normalized_target)

    return workflow_service.transition(
        cleaned_request_id,
        normalized_target,
        actor=identity.id,
        comment=comment.strip(),
    )
