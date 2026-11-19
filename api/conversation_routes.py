from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.chat_stream import stream_events
from api.v1_dependencies import require_roles
from services.auth_service import DemoIdentity
from services.runtime import Runtime, get_runtime

router = APIRouter(prefix="/api/v1/conversations")


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None
    title: str = Field("New conversation", min_length=1, max_length=120)


class ConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=16000)
    request_id: UUID

    @field_validator("content")
    @classmethod
    def nonempty(cls, value: str):
        if not value.strip():
            raise ValueError("Message cannot be blank.")
        return value.strip()


@router.get("")
def list_conversations(
    q: str = Query("", max_length=200),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.conversation_service.list(identity, q, limit, offset)


@router.post("", status_code=201)
def create_conversation(
    payload: ConversationCreate,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
):
    return {
        "conversation": runtime.conversation_service.create(
            identity, str(payload.id) if payload.id else None, payload.title
        )
    }


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: UUID,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.conversation_service.get(identity, str(conversation_id))


@router.patch("/{conversation_id}")
def rename_conversation(
    conversation_id: UUID,
    payload: ConversationRename,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
):
    return {
        "conversation": runtime.conversation_service.rename(
            identity, str(conversation_id), payload.title
        )
    }


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: UUID,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
):
    runtime.conversation_service.delete(identity, str(conversation_id))
    return {"status": "deleted"}


@router.post("/{conversation_id}/messages/stream")
def send_message(
    conversation_id: UUID,
    payload: ConversationMessage,
    identity: DemoIdentity = Depends(require_roles("employee")),
    runtime: Runtime = Depends(get_runtime),
):
    result = runtime.conversation_service.send(
        identity, str(conversation_id), payload.content, str(payload.request_id)
    )
    return StreamingResponse(
        stream_events(
            result["message"]["content"],
            start={"conversation": result["conversation"], "user_message": result["user_message"]},
            complete=result,
        ),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )
