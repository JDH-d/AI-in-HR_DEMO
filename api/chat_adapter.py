from __future__ import annotations

from uuid import uuid4

from api.schemas import ChatRequest, ChatResponse, Message, SourceChunk
from domain.chat import ChatQuery, ChatTurn
from domain.errors import ChatInputError
from services.auth_service import DemoIdentity
from services.chat_service import ChatService
from services.conversation_service import ConversationService


def handle_saved_chat(
    service: ConversationService, req: ChatRequest, identity: DemoIdentity
) -> ChatResponse:
    if not req.messages or req.messages[-1].role != "user" or not req.messages[-1].content.strip():
        raise ChatInputError("The last message must be a nonempty user message.")
    conversation_id = (
        str(req.conversation_id) if req.conversation_id else service.create(identity)["id"]
    )
    result = service.send(
        identity,
        conversation_id,
        req.messages[-1].content,
        str(req.request_id or uuid4()),
        top_k=req.top_k or 4,
        min_similarity=req.min_similarity if req.min_similarity is not None else 0.25,
    )
    message = result["message"]
    return ChatResponse(
        message=Message(role="assistant", content=message["content"]),
        intent=message["intent"],
        language=message["language"],
        sources=message.get("sources", []),
        workflow_request=message.get("workflow"),
        conversation_id=conversation_id,
    )


def handle_chat(
    service: ChatService,
    req: ChatRequest,
    created_by: str,
    *,
    settings_override: dict[str, bool] | None = None,
    system_prompt_override: str | None = None,
    log_outcome: bool = True,
    allow_workflow: bool = True,
) -> ChatResponse:
    query = ChatQuery(
        messages=[ChatTurn(role=message.role, content=message.content) for message in req.messages],
        top_k=req.top_k or 4,
        min_similarity=req.min_similarity if req.min_similarity is not None else 0.25,
    )
    outcome = service.respond(
        query,
        created_by=created_by,
        settings=settings_override,
        system_prompt=system_prompt_override,
        log_outcome=log_outcome,
        allow_workflow=allow_workflow,
    )
    return ChatResponse(
        message=Message(role="assistant", content=outcome.content),
        intent=outcome.intent.value,
        language=outcome.language,
        sources=[
            SourceChunk(
                source=source.source,
                title=source.title,
                section=source.section,
                category=source.category,
                version=source.version,
                excerpt=source.excerpt,
                score=source.score,
            )
            for source in outcome.sources
        ],
        workflow_request=outcome.workflow_request,
    )
