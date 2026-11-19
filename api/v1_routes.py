from __future__ import annotations

import time
from typing import Iterator

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from api.chat_adapter import handle_chat, handle_saved_chat
from api.chat_stream import stream_events
from api.request_routes import router as request_router
from api.schemas import ChatRequest, ChatResponse, SystemPromptUpdate
from api.v1_dependencies import current_identity, require_roles
from api.v1_schemas import (
    AISettingsTestRequest,
    AISettingsUpdate,
    FeedbackCreate,
    LoginRequest,
    QualityReviewAction,
)
from services.auth_service import DemoIdentity
from services.runtime import Runtime, get_runtime

router = APIRouter(prefix="/api/v1")
router.include_router(request_router)


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "api_version": "v1"}


@router.post("/auth/login")
def login(payload: LoginRequest, runtime: Runtime = Depends(get_runtime)) -> dict:
    token, identity = runtime.auth_service.login(payload.username, payload.password)
    runtime.conversation_service.record_user(identity)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": runtime.auth_service.ttl_seconds,
        "user": identity.public_dict(),
    }


@router.get("/me")
def me(
    identity: DemoIdentity = Depends(current_identity), runtime: Runtime = Depends(get_runtime)
) -> dict:
    return {"user": identity.public_dict()}


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
) -> ChatResponse:
    return handle_saved_chat(runtime.conversation_service, payload, identity)


@router.post("/chat/stream")
def stream_chat(
    payload: ChatRequest,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    response = handle_saved_chat(runtime.conversation_service, payload, identity)
    return StreamingResponse(
        _stream_chat_response(response),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/documents")
def list_documents(
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return {"documents": runtime.document_service.list_documents()}


@router.post("/documents", status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return {"document": runtime.document_service.upload(file.filename or "", file.file)}


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: str,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> FileResponse:
    path = runtime.document_service.download_path(document_id)
    return FileResponse(path=path, filename=path.name)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    runtime.document_service.delete(document_id)
    return {"status": "deleted", "document_id": document_id, "index_refreshed": True}


@router.post("/documents/{document_id}/index")
def index_document(
    document_id: str,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return {"status": "indexed", "document": runtime.document_service.index(document_id)}


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
def add_feedback(
    payload: FeedbackCreate,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    if payload.request_id:
        feedback = runtime.workflow_service.add_feedback(
            payload.request_id,
            identity.id,
            payload.rating,
            payload.comment,
        )
    else:
        feedback = runtime.workflow_service.add_assistant_feedback(
            identity.id,
            payload.rating,
            payload.comment,
            payload.question,
            payload.answer,
        )
    return {"feedback": feedback}


@router.get("/admin/feedback")
def admin_feedback(
    sentiment: str = "all",
    limit: int = 200,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    items = runtime.workflow_service.list_assistant_feedback(sentiment=sentiment, limit=limit)
    return {"feedback": items}


@router.get("/admin/metrics")
def admin_metrics(
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return {"metrics": runtime.quality_service.metrics()}


@router.get("/admin/unanswered")
def unanswered_questions(
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return {"questions": runtime.quality_service.unanswered()}


@router.post("/admin/quality/{item_id}")
def review_quality_item(
    item_id: str,
    payload: QualityReviewAction,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    review = runtime.workflow_service.review_quality_item(item_id, payload.action)
    return {"review": review}


@router.get("/admin/ai-settings")
def get_ai_settings(
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return runtime.ai_settings_service.get()


@router.put("/admin/ai-settings")
def update_ai_settings(
    payload: AISettingsUpdate,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return runtime.ai_settings_service.save(payload.settings.model_dump(), payload.system_prompt)


@router.post("/admin/ai-settings/test")
def test_ai_settings(
    payload: AISettingsTestRequest,
    identity: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    started = time.perf_counter()
    response = handle_chat(
        runtime.chat_service,
        ChatRequest(messages=[{"role": "user", "content": payload.question}]),
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
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return {"system_prompt": runtime.ai_settings_service.get_prompt()}


@router.put("/admin/system-prompt")
def update_system_prompt(
    payload: SystemPromptUpdate,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    runtime.ai_settings_service.save_prompt(payload.system_prompt)
    return {"status": "ok"}


@router.get("/admin/logs")
def get_logs(
    limit: int = 100,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return {"logs": runtime.quality_service.read_logs(limit)}


def _stream_chat_response(response: ChatResponse) -> Iterator[str]:
    return stream_events(
        response.message.content,
        start={"intent": response.intent, "language": response.language},
        complete={
            "conversation_id": response.conversation_id,
            "sources": [source.model_dump() for source in response.sources or []],
            "workflow_request": response.workflow_request.model_dump()
            if response.workflow_request
            else None,
        },
    )
