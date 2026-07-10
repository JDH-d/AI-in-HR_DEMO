from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Iterator

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from api.schemas import ChatResponse, SystemPromptUpdate, WorkflowCommentCreate
from api.v1_dependencies import current_identity, require_roles
from api.v1_schemas import (
    DecisionRequest,
    FeedbackCreate,
    LoginRequest,
    RequestSubmit,
    StructuredRequestCreate,
    V1ChatRequest,
)
from rag.index import rebuild_index
from rag.prompts import load_system_prompt, save_system_prompt
from services.auth_service import AuthenticationError, DemoIdentity
from services.runtime import (
    auth_service,
    chat_service,
    document_service,
    log_service,
    workflow_service,
)
from workflow import (
    InvalidTransitionError,
    WorkflowNotFoundError,
    WorkflowPermissionError,
    WorkflowValidationError,
)

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "api_version": "v1"}


@router.post("/auth/login")
def login(payload: LoginRequest) -> dict:
    try:
        token, identity = auth_service.login(payload.username, payload.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": auth_service.ttl_seconds,
        "user": identity.public_dict(),
    }


@router.get("/me")
def me(identity: DemoIdentity = Depends(current_identity)) -> dict:
    return {"user": identity.public_dict()}


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: V1ChatRequest,
    identity: DemoIdentity = Depends(current_identity),
) -> ChatResponse:
    return chat_service.handle_chat(payload, created_by=identity.id)


@router.post("/chat/stream")
def stream_chat(
    payload: V1ChatRequest,
    identity: DemoIdentity = Depends(current_identity),
) -> StreamingResponse:
    response = chat_service.handle_chat(payload, created_by=identity.id)
    return StreamingResponse(
        _stream_chat_response(response),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/requests")
def list_requests(identity: DemoIdentity = Depends(current_identity)) -> dict:
    if identity.role == "employee":
        requests = workflow_service.list_for_user(identity.id)
    else:
        requests = workflow_service.list_all(limit=500)
    return {"requests": requests}


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_request(
    payload: StructuredRequestCreate,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        request = workflow_service.create_structured_draft(
            request_type=payload.type,
            start_date=payload.start_date,
            end_date=payload.end_date,
            comment=payload.comment,
            applicant=identity.id,
            approver=payload.approver or identity.manager_id or "manager.demo",
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    return {"request": request}


@router.get("/requests/{request_id}")
def get_request(
    request_id: str,
    identity: DemoIdentity = Depends(current_identity),
) -> dict:
    request = _request_for_identity(request_id, identity)
    history = workflow_service.history(request_id)
    return {
        "request": request,
        "events": history["events"],
        "comments": history["comments"],
    }


@router.post("/requests/{request_id}/submit")
def submit_request(
    request_id: str,
    payload: RequestSubmit,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        request = workflow_service.confirm_draft(
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
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        request = workflow_service.cancel(request_id, identity.id, payload.comment)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"request": request}


@router.post("/requests/{request_id}/approve")
def approve_request(
    request_id: str,
    payload: DecisionRequest,
    identity: DemoIdentity = Depends(require_roles("manager")),
) -> dict:
    return {"request": _manager_decision(request_id, "approved", identity, payload.comment)}


@router.post("/requests/{request_id}/decline")
def decline_request(
    request_id: str,
    payload: DecisionRequest,
    identity: DemoIdentity = Depends(require_roles("manager")),
) -> dict:
    return {"request": _manager_decision(request_id, "declined", identity, payload.comment)}


@router.post("/requests/{request_id}/comments", status_code=status.HTTP_201_CREATED)
def add_manager_comment(
    request_id: str,
    payload: WorkflowCommentCreate,
    identity: DemoIdentity = Depends(require_roles("manager")),
) -> dict:
    _request_for_identity(request_id, identity)
    try:
        comment = workflow_service.add_manager_comment(
            request_id,
            identity.id,
            payload.body,
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    return {"comment": comment}


@router.get("/documents")
def list_documents(
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    return {"documents": document_service.list_documents()}


@router.post("/documents", status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    name = document_service.save_upload(file)
    document = next(
        (item for item in document_service.list_documents() if item["name"] == name),
        None,
    )
    return {"document": document or {"id": document_service.document_id(name), "name": name}}


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: str,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> FileResponse:
    document = document_service.find_by_id(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="The document could not be found.")
    path = document_service.resolve_path(document["name"])
    return FileResponse(path=path, filename=path.name)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    document = document_service.find_by_id(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="The document could not be found.")
    path = document_service.resolve_path(document["name"])
    original = path.read_bytes()
    document_service.delete_document(document["name"])
    try:
        rebuild_index()
    except (RuntimeError, OSError, ValueError) as exc:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)
        logger.warning("Document deletion rolled back document_id=%s error=%s", document_id, exc)
        raise HTTPException(
            status_code=503,
            detail="The document could not be removed from the knowledge index. Deletion was rolled back.",
        ) from exc
    document_service.remove_index_status(document_id)
    return {"status": "deleted", "document_id": document_id, "index_refreshed": True}


@router.post("/documents/{document_id}/index")
def index_document(
    document_id: str,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    document = document_service.find_by_id(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="The document could not be found.")
    document_service.record_index_result(document_id, "indexing")
    try:
        rebuild_index()
    except (RuntimeError, OSError, ValueError) as exc:
        error = f"{type(exc).__name__}: {str(exc)[:180]}"
        document_service.record_index_result(document_id, "error", error)
        logger.warning("Document index rebuild failed document_id=%s error=%s", document_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Index rebuild failed. Check document readability and OpenAI configuration.",
        ) from exc
    document_service.record_index_result(document_id, "indexed")
    return {
        "status": "indexed",
        "document": document_service.find_by_id(document_id) or document,
    }


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
def add_feedback(
    payload: FeedbackCreate,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        if payload.request_id:
            feedback = workflow_service.add_feedback(
                payload.request_id,
                identity.id,
                payload.rating,
                payload.comment,
            )
        else:
            feedback = workflow_service.add_assistant_feedback(
                identity.id,
                payload.rating,
                payload.comment,
                payload.question,
                payload.answer,
            )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"feedback": feedback}


@router.get("/admin/feedback")
def admin_feedback(
    sentiment: str = "all",
    limit: int = 200,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    try:
        items = workflow_service.list_assistant_feedback(sentiment=sentiment, limit=limit)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    return {"feedback": items}


@router.get("/admin/metrics")
def admin_metrics(
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    metrics = workflow_service.metrics()
    logs = log_service.read(1000)
    question_count = len(logs)
    grounded_count = sum(1 for entry in logs if entry.get("sources"))
    unanswered = _unanswered_entries(logs)
    total_feedback = metrics["feedback"] + metrics["assistant_feedback"]
    metrics.update(
        {
            "documents": len(document_service.list_documents()),
            "chat_logs": question_count,
            "questions": question_count,
            "grounded_answers": grounded_count,
            "grounded_answer_rate": round(
                (grounded_count / question_count * 100) if question_count else 0.0,
                1,
            ),
            "unanswered_questions": len(unanswered),
            "positive_feedback_rate": round(
                (metrics["positive_feedback"] / total_feedback * 100) if total_feedback else 0.0,
                1,
            ),
            "requests_created": metrics["total_requests"],
            "requests_approved": metrics["requests_by_status"].get("approved", 0),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"metrics": metrics}


@router.get("/admin/unanswered")
def unanswered_questions(
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    return {"questions": _unanswered_entries(log_service.read(1000))}


@router.get("/admin/system-prompt")
def get_system_prompt(
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    return {"system_prompt": load_system_prompt()}


@router.put("/admin/system-prompt")
def update_system_prompt(
    payload: SystemPromptUpdate,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    save_system_prompt(payload.system_prompt)
    return {"status": "ok"}


@router.get("/admin/logs")
def get_logs(
    limit: int = 100,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    return {"logs": log_service.read(limit)}


def _request_for_identity(request_id: str, identity: DemoIdentity) -> dict:
    if identity.role == "employee":
        request = workflow_service.get_for_user(request_id, identity.id)
    else:
        request = next(
            (item for item in workflow_service.list_all(limit=1000) if item["id"] == request_id),
            None,
        )
    if request is None:
        raise HTTPException(status_code=404, detail="The workflow request could not be found.")
    return request


def _manager_decision(
    request_id: str,
    target: str,
    identity: DemoIdentity,
    comment: str,
) -> dict:
    if target == "declined" and not comment.strip():
        raise HTTPException(
            status_code=422,
            detail="A manager comment is required when declining a request.",
        )
    request = _request_for_identity(request_id, identity)
    if request["status"] != "in_review":
        raise HTTPException(
            status_code=409,
            detail=f"Request in status {request['status']} cannot be {target}.",
        )
    try:
        return workflow_service.transition(
            request_id,
            target,
            actor=identity.id,
            comment=comment,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _stream_chat_response(response: ChatResponse) -> Iterator[str]:
    yield (
        json.dumps(
            {
                "type": "start",
                "intent": response.intent,
                "language": response.language,
            }
        )
        + "\n"
    )
    words = response.message.content.split()
    for start in range(0, len(words), 4):
        chunk = " ".join(words[start : start + 4])
        if start + 4 < len(words):
            chunk += " "
        yield json.dumps({"type": "token", "content": chunk}) + "\n"
        time.sleep(0.012)
    yield (
        json.dumps(
            {
                "type": "complete",
                "sources": [source.model_dump() for source in response.sources or []],
                "workflow_request": (
                    response.workflow_request.model_dump()
                    if response.workflow_request is not None
                    else None
                ),
            }
        )
        + "\n"
    )


def _unanswered_entries(logs: list[dict]) -> list[dict]:
    unanswered: list[dict] = []
    for entry in reversed(logs):
        assistant = str(entry.get("assistant", ""))
        if entry.get("intent") != "invalid" and "could not find a reliable answer" not in assistant:
            continue
        unanswered.append(
            {
                "timestamp": entry.get("ts"),
                "question": entry.get("user", "Question text was not retained"),
                "assistant": assistant,
                "intent": entry.get("intent"),
            }
        )
    return unanswered[:50]
