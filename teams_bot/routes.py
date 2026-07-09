from __future__ import annotations

from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from services.runtime import chat_service

from .bot import TeamsPersonalChatBot
from .config import TeamsBotSettings
from .history import TeamsConversationHistory


router = APIRouter()
settings = TeamsBotSettings.from_env()
history_store = TeamsConversationHistory(settings.history_db)
adapter = BotFrameworkAdapter(
    BotFrameworkAdapterSettings(
        settings.app_id,
        settings.app_password,
        channel_auth_tenant=settings.tenant_id or None,
    )
)
bot = TeamsPersonalChatBot(
    chat_service=chat_service,
    history=history_store,
    max_context_messages=settings.max_context_messages,
    max_source_count=settings.max_source_count,
)


async def _on_turn_error(turn_context: TurnContext, error: Exception) -> None:
    await turn_context.send_activity(
        "The assistant hit an unexpected error while processing this message."
    )


adapter.on_turn_error = _on_turn_error


@router.get("/teams/health")
def teams_health() -> dict:
    return {
        "status": "ok",
        "enabled": settings.enabled,
        "configured": bool(settings.app_id and settings.app_password),
    }


@router.post("/api/messages")
async def teams_messages(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    if not settings.enabled:
        raise HTTPException(status_code=404, detail="Teams bot endpoint is disabled.")

    body = await request.json()
    activity = Activity().deserialize(body)
    invoke_response = await adapter.process_activity(
        activity,
        authorization or "",
        bot.on_turn,
    )
    if invoke_response:
        return JSONResponse(
            content=invoke_response.body,
            status_code=invoke_response.status,
        )
    return Response(status_code=201)

