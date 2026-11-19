from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response

from api.request_schemas import (
    BulkStartReview,
    RequestAction,
    RequestAssignment,
    RequestAttention,
    RequestCategory,
    RequestComment,
    RequestPriority,
    RequestStatus,
    RequestUpdate,
    StructuredRequestCreate,
)
from api.v1_dependencies import require_roles
from domain.request_policy import POLICY_VERSION, PRIORITIES, PROCEDURE, STATUSES
from domain.workflow import TYPE_LABELS
from services.auth_service import DEMO_IDENTITIES, DemoIdentity
from services.request_service import MAX_ATTACHMENT_BYTES
from services.runtime import Runtime, get_runtime


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(no_store)])
participant = require_roles("employee", "manager")


@router.get("/request-options")
def request_options(_: DemoIdentity = Depends(participant)):
    return {
        "categories": TYPE_LABELS,
        "priorities": PRIORITIES,
        "statuses": STATUSES,
        "procedure": PROCEDURE,
        "policy_version": POLICY_VERSION,
        "managers": [
            {"id": item.id, "display_name": item.display_name}
            for item in DEMO_IDENTITIES.values()
            if item.role == "manager"
        ],
    }


@router.get("/requests")
def list_requests(
    status: RequestStatus | None = None,
    category: RequestCategory | None = None,
    priority: RequestPriority | None = None,
    assignee: str | None = Query(None, max_length=200),
    attention: RequestAttention = "all",
    q: str = Query("", max_length=200),
    sort: str = Query("updated_at", pattern="^(created_at|updated_at|number|title|priority)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return runtime.workflow_service.list_visible(
        identity.id,
        identity.role,
        status=status,
        category=category,
        priority=priority,
        assignee=assignee,
        attention=attention,
        q=q,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/manager/overview")
def manager_overview(
    identity: DemoIdentity = Depends(require_roles("manager")),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.workflow_service.manager_overview(identity.id, identity.role)


@router.get("/manager/activity")
def manager_activity(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    identity: DemoIdentity = Depends(require_roles("manager")),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.workflow_service.manager_activity(
        identity.id, identity.role, limit=limit, offset=offset
    )


@router.post("/manager/bulk-start-review")
def bulk_start_review(
    payload: BulkStartReview,
    identity: DemoIdentity = Depends(require_roles("manager")),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.workflow_service.bulk_start_review(
        identity.id,
        identity.role,
        [item.model_dump() for item in payload.items],
    )


@router.post("/requests", status_code=201)
def create_request(
    payload: StructuredRequestCreate,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
):
    values = payload.model_dump(exclude={"creation_key"})
    values["request_type"] = values.pop("type")
    return {
        "request": runtime.workflow_service.create_structured_draft(
            **values,
            applicant=identity.id,
            approver=identity.manager_id or "",
            creation_key=str(payload.creation_key) if payload.creation_key else None,
        )
    }


@router.get("/requests/{request_id}")
def get_request(
    request_id: str,
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.workflow_service.detail(request_id, identity.id, identity.role)


@router.patch("/requests/{request_id}")
def edit_request(
    request_id: str,
    payload: RequestUpdate,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
):
    fields = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
    return {
        "request": runtime.workflow_service.edit_draft(
            request_id, identity.id, fields, payload.expected_revision
        )
    }


@router.post("/requests/{request_id}/submit")
def submit_request(
    request_id: str,
    payload: RequestUpdate,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
):
    fields = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
    return {
        "request": runtime.workflow_service.confirm_draft(
            request_id, identity.id, fields, revision=payload.expected_revision
        )
    }


@router.post("/requests/{request_id}/actions/{action}")
def request_action(
    request_id: str,
    action: str,
    payload: RequestAction,
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
):
    return {
        "request": runtime.workflow_service.act(
            request_id,
            identity.id,
            identity.role,
            action,
            payload.expected_revision,
            comment=payload.comment,
            basis=payload.basis,
            fair_review_confirmed=payload.fair_review_confirmed,
        )
    }


@router.post("/requests/{request_id}/comments", status_code=201)
def add_comment(
    request_id: str,
    payload: RequestComment,
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.workflow_service.comment(
        request_id, identity.id, identity.role, payload.body, payload.expected_revision
    )


@router.post("/requests/{request_id}/assign")
def assign_request(
    request_id: str,
    payload: RequestAssignment,
    identity: DemoIdentity = Depends(require_roles("manager")),
    runtime: Runtime = Depends(get_runtime),
):
    return {
        "request": runtime.workflow_service.assign(
            request_id, identity.id, payload.assignee, payload.comment, payload.expected_revision
        )
    }


@router.post("/requests/{request_id}/attachments", status_code=201)
def upload_attachment(
    request_id: str,
    expected_revision: int = Form(..., ge=1),
    file: UploadFile = File(...),
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
):
    try:
        return runtime.workflow_service.attach(
            request_id,
            identity.id,
            identity.role,
            file.filename or "",
            file.file.read(MAX_ATTACHMENT_BYTES + 1),
            expected_revision,
        )
    finally:
        file.file.close()


@router.get("/requests/{request_id}/attachments/{attachment_id}")
def download_attachment(
    request_id: str,
    attachment_id: str,
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
):
    item = runtime.workflow_service.attachment(
        request_id, attachment_id, identity.id, identity.role
    )
    return Response(
        item["content"],
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(item["filename"], safe=""),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "no-store",
        },
    )
