from __future__ import annotations

from api.schemas import ChatResponse, Message, SourceChunk
from api.v1_schemas import V1ChatRequest
from services.chat_models import ChatOutcome, ChatQuery, ChatTurn


def to_chat_query(payload: V1ChatRequest) -> ChatQuery:
    return ChatQuery(
        messages=[
            ChatTurn(role=message.role, content=message.content) for message in payload.messages
        ],
        top_k=payload.top_k if payload.top_k is not None else 4,
        min_similarity=(payload.min_similarity if payload.min_similarity is not None else 0.25),
    )


def to_chat_response(
    outcome: ChatOutcome,
    *,
    show_sources: bool,
    conversation_id: str | None = None,
) -> ChatResponse:
    return ChatResponse(
        message=Message(role="assistant", content=outcome.content),
        intent=outcome.intent.value,
        language=outcome.language,
        outcome_code=outcome.outcome_code,
        sources=(
            [
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
            ]
            if show_sources
            else []
        ),
        workflow_request=outcome.workflow_request,
        conversation_id=conversation_id,
    )
