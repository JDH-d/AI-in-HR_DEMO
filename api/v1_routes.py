from __future__ import annotations

import hashlib
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
    AISettingsTestRequest,
    AISettingsUpdate,
    DecisionRequest,
    FeedbackCreate,
    LoginRequest,
    QualityReviewAction,
    RequestSubmit,
    StructuredRequestCreate,
    V1ChatRequest,
)
from rag.index import rebuild_index
from rag.prompts import DEFAULT_SYSTEM_PROMPT, load_system_prompt, save_system_prompt
from services.auth_service import AuthenticationError, DemoIdentity
from services.conversation_service import (
    ConversationNotFoundError,
    ConversationValidationError,
)
from services.runtime import (
    ai_settings_service,
    auth_service,
    chat_service,
    conversation_service,
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


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    return {"conversation": conversation_service.create(identity.id)}


@router.get("/conversations")
def list_conversations(
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    return {"conversations": conversation_service.list_for_user(identity.id)}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        return conversation_service.get_for_user(conversation_id, identity.id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        deleted = conversation_service.delete_for_user(conversation_id, identity.id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True, "conversation": deleted}


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: V1ChatRequest,
    identity: DemoIdentity = Depends(current_identity),
) -> ChatResponse:
    return _handle_chat(payload, identity)


@router.post("/chat/stream")
def stream_chat(
    payload: V1ChatRequest,
    identity: DemoIdentity = Depends(current_identity),
) -> StreamingResponse:
    response = _handle_chat(payload, identity)
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
    if document and ai_settings_service.get()["auto_index_uploads"]:
        document = _rebuild_document_index(document["id"], document)
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
    indexed = _rebuild_document_index(document_id, document)
    return {"status": "indexed", "document": indexed}


def _rebuild_document_index(document_id: str, document: dict) -> dict:
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
    return document_service.find_by_id(document_id) or document


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
    workplace_logs = [entry for entry in logs if entry.get("intent") == "work"]
    question_count = len(workplace_logs)
    grounded_count = sum(1 for entry in workplace_logs if entry.get("sources"))
    unanswered = _unanswered_entries(
        workplace_logs,
        workflow_service.reviewed_quality_item_ids(),
    )
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
    reviewed = workflow_service.reviewed_quality_item_ids()
    return {"questions": _unanswered_entries(log_service.read(1000), reviewed)}


@router.post("/admin/quality/{item_id}")
def review_quality_item(
    item_id: str,
    payload: QualityReviewAction,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    try:
        review = workflow_service.review_quality_item(item_id, payload.action)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    return {"review": review}


@router.get("/admin/ai-settings")
def get_ai_settings(
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    return {
        "settings": ai_settings_service.get(),
        "system_prompt": load_system_prompt(),
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
    }


@router.put("/admin/ai-settings")
def update_ai_settings(
    payload: AISettingsUpdate,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    settings = ai_settings_service.save(payload.settings.model_dump())
    save_system_prompt(payload.system_prompt)
    return {
        "settings": settings,
        "system_prompt": load_system_prompt(),
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
    }


@router.post("/admin/ai-settings/test")
def test_ai_settings(
    payload: AISettingsTestRequest,
    identity: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    started = time.perf_counter()
    response = chat_service.handle_chat(
        V1ChatRequest(messages=[{"role": "user", "content": payload.question}]),
        created_by=identity.id,
        settings_override=payload.settings.model_dump(),
        system_prompt_override=payload.system_prompt,
        log_outcome=False,
        allow_workflow=False,
    )
    return {
        "answer": response.message.content,
        "intent": response.intent,
        "sources": [source.model_dump() for source in response.sources or []],
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


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


def _handle_chat(payload: V1ChatRequest, identity: DemoIdentity) -> ChatResponse:
    if payload.conversation_id:
        if identity.role != "employee":
            raise HTTPException(
                status_code=403,
                detail="Only employees can save conversation history.",
            )
        try:
            conversation_service.get_for_user(payload.conversation_id, identity.id)
        except ConversationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    response = chat_service.handle_chat(payload, created_by=identity.id)
    if not payload.conversation_id:
        return response

    latest_user_message = next(
        (message for message in reversed(payload.messages) if message.role == "user"),
        None,
    )
    if latest_user_message is None:
        return response
    try:
        conversation_service.append_exchange(
            payload.conversation_id,
            identity.id,
            user_text=latest_user_message.content,
            assistant_text=response.message.content,
            sources=[source.model_dump() for source in response.sources or []],
            workflow_request=(
                response.workflow_request.model_dump()
                if response.workflow_request is not None
                else None
            ),
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConversationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response


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


def _unanswered_entries(logs: list[dict], reviewed_ids: set[str] | None = None) -> list[dict]:
    unanswered: list[dict] = []
    reviewed = reviewed_ids or set()
    for entry in reversed(logs):
        assistant = str(entry.get("assistant", ""))
        if entry.get("intent") != "work":
            continue
        if entry.get("sources"):
            continue
        if "could not find a reliable answer" not in assistant:
            continue
        question = str(entry.get("user", "Question text was not retained"))
        item_id = hashlib.sha256(f"{entry.get('ts', '')}\n{question}".encode("utf-8")).hexdigest()[
            :16
        ]
        if item_id in reviewed:
            continue
        unanswered.append(
            {
                "id": item_id,
                "timestamp": entry.get("ts"),
                "question": question,
                "assistant": assistant,
            }
        )
    return unanswered[:50]
