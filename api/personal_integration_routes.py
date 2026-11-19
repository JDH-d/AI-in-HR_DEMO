"""Personal account linking; provider callbacks never accept a role or a destination channel."""

import json
import re
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from api.integration_routes import IntegrationRoute, Provider, no_store
from api.v1_dependencies import require_roles
from domain.notifications import DiscordCommandError, IntegrationError
from services.auth_service import DemoIdentity
from services.runtime import Runtime, get_runtime

router = APIRouter(route_class=IntegrationRoute, dependencies=[Depends(no_store)])
participant = require_roles("employee", "manager")
PERSONAL = "/api/v1/me/integrations"


class ConfirmConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")


@router.get(PERSONAL)
def connections(
    identity: DemoIdentity = Depends(participant), runtime: Runtime = Depends(get_runtime)
):
    return runtime.notification_service.connections(identity)


@router.post(PERSONAL + "/{provider}/link-code")
def link_code(
    provider: Provider,
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.notification_service.link_code(provider, identity)


@router.post(PERSONAL + "/{provider}/confirm")
def confirm(
    provider: Provider,
    payload: ConfirmConnection,
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.notification_service.confirm_connection(provider, identity, payload.challenge_id)


@router.delete(PERSONAL + "/{provider}")
def disconnect(
    provider: Provider,
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.notification_service.disconnect(provider, identity)


@router.post(PERSONAL + "/{provider}/test", status_code=202)
def test_personal(
    provider: Provider,
    identity: DemoIdentity = Depends(participant),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.notification_service.test_notification(provider, identity.role, identity.id)


async def small_body(request):
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 32768:
            raise HTTPException(413, "Command payload is too large.")
    return bytes(chunks)


def accept_code(service, provider, code, user_id, scope):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32}", code or ""):
        return "Generate a link code in Personal notifications in the application, then use /peopleflow link with that code. Roles are assigned by the application."
    try:
        return service.accept_link_code(provider, code, user_id, scope)
    except IntegrationError as exc:
        return str(exc)


@router.post("/api/v1/integrations/slack/commands")
async def slack_command(request: Request, runtime: Runtime = Depends(get_runtime)):
    service = runtime.notification_service
    body = await small_body(request)
    if not service.verify_command(
        "slack",
        body,
        request.headers.get("x-slack-request-timestamp", ""),
        request.headers.get("x-slack-signature", ""),
    ):
        raise HTTPException(401, "Invalid Slack request signature.")
    try:
        data = parse_qs(body.decode("utf-8"), max_num_fields=30, strict_parsing=True)
        if any(len(values) != 1 for values in data.values()):
            raise ValueError
        fields = {key: values[0] for key, values in data.items()}
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid Slack command.") from None
    user_id = fields.get("user_id", "")
    if (
        fields.get("team_id") != service.slack_team_id
        or fields.get("command") != "/peopleflow"
        or not re.fullmatch(r"[UW][A-Z0-9]+", user_id)
    ):
        raise HTTPException(403, "This Slack account or workspace is not supported.")
    parts = fields.get("text", "").strip().split()
    code = parts[1] if len(parts) == 2 and parts[0] == "link" else ""
    return {
        "response_type": "ephemeral",
        "text": accept_code(service, "slack", code, user_id, service.slack_team_id),
    }


@router.post("/api/v1/integrations/discord/interactions")
async def discord_interaction(request: Request, runtime: Runtime = Depends(get_runtime)):
    service = runtime.notification_service
    body = await small_body(request)
    if not service.verify_command(
        "discord",
        body,
        request.headers.get("x-signature-timestamp", ""),
        request.headers.get("x-signature-ed25519", ""),
    ):
        raise HTTPException(401, "Invalid Discord request signature.")
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid Discord interaction.") from None
    try:
        return service.handle_discord_interaction(data)
    except DiscordCommandError as exc:
        raise HTTPException(exc.status, exc.detail) from None
