from __future__ import annotations

from fastapi import HTTPException

from api.chat_adapter import to_chat_query, to_chat_response
from api.schemas import ChatResponse
from api.v1_schemas import V1ChatRequest
from services.chat_service import ChatValidationError
from services.runtime import ServiceContainer


def execute_chat(
    payload: V1ChatRequest,
    actor_id: str,
    services: ServiceContainer,
    *,
    settings_override: dict[str, bool] | None = None,
    system_prompt_override: str | None = None,
    log_outcome: bool = True,
    allow_workflow: bool = True,
) -> ChatResponse:
    configuration = services.ai_settings.get_configuration()
    settings = settings_override if settings_override is not None else configuration["settings"]
    system_prompt = (
        system_prompt_override
        if system_prompt_override is not None
        else configuration["system_prompt"]
    )
    try:
        outcome = services.chat.respond(
            to_chat_query(payload),
            created_by=actor_id,
            settings=settings,
            system_prompt=system_prompt,
            log_outcome=log_outcome,
            allow_workflow=allow_workflow,
        )
    except ChatValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_chat_response(
        outcome,
        show_sources=settings.get("show_sources", True),
    )
