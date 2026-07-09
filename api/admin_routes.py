from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.dependencies import require_admin
from api.schemas import SystemPromptUpdate, WorkflowCommentCreate, WorkflowStatusUpdate
from rag.index import rebuild_index
from rag.prompts import load_system_prompt, save_system_prompt
from services.runtime import document_service, log_service, workflow_service
from workflow import (
    InvalidTransitionError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/admin/system-prompt")
def admin_get_system_prompt(_: None = Depends(require_admin)) -> dict:
    return {"system_prompt": load_system_prompt()}


@router.put("/admin/system-prompt")
def admin_update_system_prompt(
    payload: SystemPromptUpdate, _: None = Depends(require_admin)
) -> dict:
    save_system_prompt(payload.system_prompt)
    return {"status": "ok"}


@router.get("/admin/documents")
def admin_list_documents(_: None = Depends(require_admin)) -> dict:
    return {"documents": document_service.list_documents()}


@router.post("/admin/documents")
def admin_upload_document(file: UploadFile = File(...), _: None = Depends(require_admin)) -> dict:
    name = document_service.save_upload(file)
    return {"status": "ok", "name": name}


@router.delete("/admin/documents/{doc_name:path}")
def admin_delete_document(doc_name: str, _: None = Depends(require_admin)) -> dict:
    document_service.delete_document(doc_name)
    return {"status": "ok"}


@router.post("/admin/rebuild-index")
def admin_rebuild_index(_: None = Depends(require_admin)) -> dict:
    try:
        rebuild_index()
    except (RuntimeError, OSError, ValueError) as exc:
        logger.warning("Admin index rebuild failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Index rebuild failed. Check document readability and OpenAI configuration.",
        ) from exc
    return {"status": "ok"}


@router.get("/admin/logs")
def admin_logs(limit: int = 100, _: None = Depends(require_admin)) -> dict:
    return {"logs": log_service.read(limit)}


@router.get("/admin/requests")
def admin_list_requests(limit: int = 200, _: None = Depends(require_admin)) -> dict:
    return {"requests": workflow_service.list_all(limit=limit)}


@router.put("/admin/requests/{request_id}/status")
def admin_update_request_status(
    request_id: str,
    payload: WorkflowStatusUpdate,
    _: None = Depends(require_admin),
) -> dict:
    try:
        updated = workflow_service.transition(
            request_id,
            payload.status,
            actor="admin",
            comment=payload.comment,
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "request": updated}


@router.get("/admin/requests/{request_id}/history")
def admin_request_history(request_id: str, _: None = Depends(require_admin)) -> dict:
    try:
        return workflow_service.history(request_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/admin/requests/{request_id}/comments")
def admin_add_request_comment(
    request_id: str,
    payload: WorkflowCommentCreate,
    _: None = Depends(require_admin),
) -> dict:
    try:
        comment = workflow_service.add_manager_comment(
            request_id,
            payload.author.strip() or "Manager",
            payload.body,
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "comment": comment}
