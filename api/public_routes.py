from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from api.schemas import WorkflowAction, WorkflowConfirmation, WorkflowFeedbackCreate
from services.runtime import workflow_service
from workflow import (
    InvalidTransitionError,
    WorkflowNotFoundError,
    WorkflowPermissionError,
    WorkflowValidationError,
)

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/requests")
def list_requests(x_user: Optional[str] = Header(None)) -> dict:
    created_by = (x_user or "").strip() or "anonymous"
    return {"requests": workflow_service.list_for_user(created_by)}


@router.get("/requests/{request_id}")
def get_request(request_id: str, x_user: Optional[str] = Header(None)) -> dict:
    created_by = (x_user or "").strip() or "anonymous"
    request = workflow_service.get_for_user(request_id, created_by)
    if not request:
        raise HTTPException(status_code=404, detail="The workflow request could not be found.")
    return {"request": request}


@router.post("/requests/{request_id}/confirm")
def confirm_request(
    request_id: str,
    payload: WorkflowConfirmation,
    x_user: Optional[str] = Header(None),
) -> dict:
    created_by = (x_user or "").strip() or "anonymous"
    try:
        request = workflow_service.confirm_draft(
            request_id,
            created_by,
            payload.model_dump(exclude_none=True),
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except WorkflowPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "request": request}


@router.post("/requests/{request_id}/cancel")
def cancel_request(
    request_id: str,
    payload: WorkflowAction,
    x_user: Optional[str] = Header(None),
) -> dict:
    created_by = (x_user or "").strip() or "anonymous"
    try:
        request = workflow_service.cancel(request_id, created_by, payload.comment)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "request": request}


@router.get("/requests/{request_id}/history")
def request_history(request_id: str, x_user: Optional[str] = Header(None)) -> dict:
    created_by = (x_user or "").strip() or "anonymous"
    if workflow_service.get_for_user(request_id, created_by) is None:
        raise HTTPException(status_code=404, detail="The workflow request could not be found.")
    return workflow_service.history(request_id)


@router.post("/requests/{request_id}/feedback")
def add_feedback(
    request_id: str,
    payload: WorkflowFeedbackCreate,
    x_user: Optional[str] = Header(None),
) -> dict:
    created_by = (x_user or "").strip() or "anonymous"
    try:
        feedback = workflow_service.add_feedback(
            request_id,
            created_by,
            payload.rating,
            payload.comment,
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "feedback": feedback}
