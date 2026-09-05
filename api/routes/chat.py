from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from api.chat_adapter import to_chat_query, to_chat_response
from api.chat_execution import execute_chat
from api.schemas import ChatResponse
from api.v1_dependencies import Services, require_roles
from api.v1_schemas import V1ChatRequest
from services.auth_service import DemoIdentity
from services.chat_models import ChatQuery
from services.chat_service import ChatValidationError
from services.conversation_service import ConversationNotFoundError
from services.runtime import ServiceContainer

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = logging.getLogger(__name__)


@router.get("/conversations")
def list_conversations(
    services: Services,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    return {"conversations": services.conversations.list_for_user(identity.id)}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    conversation = services.conversations.get_for_user(conversation_id, identity.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="The conversation could not be found.")
    for message in conversation["messages"]:
        workflow_request_id = message.pop("workflow_request_id", None)
        if workflow_request_id:
            message["workflow"] = services.workflow.get_for_user(
                workflow_request_id,
                identity.id,
            )
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> Response:
    if not services.conversations.delete_for_user(conversation_id, identity.id):
        raise HTTPException(status_code=404, detail="The conversation could not be found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: V1ChatRequest,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> ChatResponse:
    request = _with_conversation_context(payload, identity.id, services)
    response = execute_chat(request, identity.id, services)
    response.conversation_id = _store_conversation_exchange(
        payload,
        response,
        identity.id,
        services,
    )
    return response


@router.post("/chat/stream")
def stream_chat(
    payload: V1ChatRequest,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> StreamingResponse:
    request = _with_conversation_context(payload, identity.id, services)
    query = to_chat_query(request)
    if query.latest_user_message is None:
        raise HTTPException(status_code=400, detail="The request must include a user message.")
    return StreamingResponse(
        _stream_chat_response(query, payload, identity.id, services),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def _with_conversation_context(
    payload: V1ChatRequest,
    owner_id: str,
    services: ServiceContainer,
) -> V1ChatRequest:
    latest_user = next(
        (message for message in reversed(payload.messages) if message.role == "user"),
        None,
    )
    if latest_user is None or not latest_user.content.strip():
        raise HTTPException(status_code=400, detail="The request must include a user message.")
    if not payload.conversation_id:
        return V1ChatRequest(
            messages=[latest_user],
            top_k=payload.top_k,
            min_similarity=payload.min_similarity,
        )

    conversation = services.conversations.get_for_user(payload.conversation_id, owner_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="The conversation could not be found.")
    history = [
        {"role": message["role"], "content": message["content"]}
        for message in conversation["messages"]
        if message["role"] in {"user", "assistant"}
    ]
    if latest_user is not None:
        history.append(latest_user.model_dump())
    return V1ChatRequest(
        messages=history,
        top_k=payload.top_k,
        min_similarity=payload.min_similarity,
        conversation_id=payload.conversation_id,
    )


def _store_conversation_exchange(
    payload: V1ChatRequest,
    response: ChatResponse,
    owner_id: str,
    services: ServiceContainer,
) -> str:
    user_content = next(
        (message.content for message in reversed(payload.messages) if message.role == "user"),
        "",
    ).strip()
    if not user_content:
        raise HTTPException(status_code=400, detail="The request must include a user message.")
    workflow_request = (
        response.workflow_request.model_dump() if response.workflow_request is not None else None
    )
    try:
        detail = services.conversations.record_exchange(
            owner_id,
            conversation_id=payload.conversation_id,
            user_content=user_content,
            assistant_content=response.message.content,
            sources=[source.model_dump() for source in response.sources or []],
            workflow_request=workflow_request,
            outcome_code=response.outcome_code,
        )
    except ConversationNotFoundError as exc:
        if workflow_request:
            services.workflow.discard_unshared_draft(workflow_request["id"], owner_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, sqlite3.Error, ValueError) as exc:
        if workflow_request:
            services.workflow.discard_unshared_draft(workflow_request["id"], owner_id)
        logger.exception("Conversation exchange could not be stored")
        raise HTTPException(status_code=503, detail="The conversation could not be saved.") from exc
    return str(detail["conversation"]["id"])


def _stream_chat_response(
    query: ChatQuery,
    payload: V1ChatRequest,
    owner_id: str,
    services: ServiceContainer,
) -> Iterator[str]:
    yield json.dumps({"type": "start"}) + "\n"
    configuration = services.ai_settings.get_configuration()
    settings = configuration["settings"]
    try:
        with closing(
            services.chat.stream(
                query,
                created_by=owner_id,
                settings=settings,
                system_prompt=configuration["system_prompt"],
            )
        ) as updates:
            for update in updates:
                if update.kind in {"token", "replace"}:
                    yield json.dumps({"type": update.kind, "content": update.content}) + "\n"
                    continue
                if update.outcome is None:
                    continue
                response = to_chat_response(
                    update.outcome,
                    show_sources=settings.get("show_sources", True),
                )
                response.conversation_id = _store_conversation_exchange(
                    payload,
                    response,
                    owner_id,
                    services,
                )
                yield (
                    json.dumps(
                        {
                            "type": "complete",
                            "intent": response.intent,
                            "language": response.language,
                            "outcome_code": response.outcome_code,
                            "sources": [source.model_dump() for source in response.sources or []],
                            "workflow_request": (
                                response.workflow_request.model_dump()
                                if response.workflow_request is not None
                                else None
                            ),
                            "conversation_id": response.conversation_id,
                        }
                    )
                    + "\n"
                )
    except ChatValidationError as exc:
        yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
    except HTTPException as exc:
        yield json.dumps({"type": "error", "message": str(exc.detail)}) + "\n"
