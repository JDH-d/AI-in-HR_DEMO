from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.schemas import WorkflowCommentCreate
from api.v1_dependencies import Services, current_identity, require_roles
from api.v1_schemas import DecisionRequest, RequestSubmit, StructuredRequestCreate
from services.auth_service import DemoIdentity
from services.runtime import ServiceContainer
from workflow import (
    InvalidTransitionError,
    WorkflowNotFoundError,
    WorkflowPermissionError,
    WorkflowValidationError,
)

router = APIRouter(prefix="/api/v1", tags=["requests"])


@router.get("/requests")
def list_requests(
    services: Services,
    identity: DemoIdentity = Depends(current_identity),
) -> dict:
    if identity.role == "employee":
        requests = services.workflow.list_for_user(identity.id)
    elif identity.role == "manager":
        requests = services.workflow.list_for_manager(identity.id, limit=500)
    else:
        requests = services.workflow.list_all(limit=500)
    return {"requests": requests}


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_request(
    payload: StructuredRequestCreate,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        request = services.workflow.create_structured_draft(
            request_type=payload.type,
            start_date=payload.start_date,
            end_date=payload.end_date,
            comment=payload.comment,
            applicant=identity.id,
            approver=identity.manager_id or "manager.demo",
            details=payload.details,
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    return {"request": request}


@router.get("/requests/{request_id}")
def get_request(
    request_id: str,
    services: Services,
    identity: DemoIdentity = Depends(current_identity),
) -> dict:
    request = _request_for_identity(request_id, identity, services)
    history = services.workflow.history(request_id)
    return {
        "request": request,
        "events": history["events"],
        "comments": history["comments"],
    }


@router.post("/requests/{request_id}/submit")
def submit_request(
    request_id: str,
    payload: RequestSubmit,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        request = services.workflow.confirm_draft(
            request_id,
            identity.id,
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
    return {"request": request}


@router.post("/requests/{request_id}/cancel")
def cancel_request(
    request_id: str,
    payload: DecisionRequest,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        request = services.workflow.cancel(request_id, identity.id, payload.comment)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"request": request}


@router.post("/requests/{request_id}/approve")
def approve_request(
    request_id: str,
    payload: DecisionRequest,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("manager")),
) -> dict:
    return {
        "request": _manager_decision(
            request_id,
            "approved",
            identity,
            payload.comment,
            services,
        )
    }


@router.post("/requests/{request_id}/decline")
def decline_request(
    request_id: str,
    payload: DecisionRequest,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("manager")),
) -> dict:
    return {
        "request": _manager_decision(
            request_id,
            "declined",
            identity,
            payload.comment,
            services,
        )
    }


@router.post("/requests/{request_id}/acknowledge")
def acknowledge_request(
    request_id: str,
    payload: DecisionRequest,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("manager")),
) -> dict:
    return {
        "request": _manager_decision(
            request_id,
            "acknowledged",
            identity,
            payload.comment,
            services,
        )
    }


@router.post("/requests/{request_id}/comments", status_code=status.HTTP_201_CREATED)
def add_manager_comment(
    request_id: str,
    payload: WorkflowCommentCreate,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("manager")),
) -> dict:
    _request_for_identity(request_id, identity, services)
    try:
        comment = services.workflow.add_manager_comment(
            request_id,
            identity.id,
            payload.body,
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    return {"comment": comment}


def _request_for_identity(
    request_id: str,
    identity: DemoIdentity,
    services: ServiceContainer,
) -> dict:
    if identity.role == "employee":
        request = services.workflow.get_for_user(request_id, identity.id)
    elif identity.role == "manager":
        request = services.workflow.get_for_manager(request_id, identity.id)
    else:
        request = services.workflow.get_any(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="The workflow request could not be found.")
    return request


def _manager_decision(
    request_id: str,
    target: str,
    identity: DemoIdentity,
    comment: str,
    services: ServiceContainer,
) -> dict:
    try:
        return services.workflow.manager_decision(
            request_id,
            identity.id,
            target,
            comment,
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
