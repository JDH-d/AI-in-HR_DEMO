"""Discord command parsing after HTTP signature or authenticated Gateway verification."""

import re

from domain.notifications import DiscordCommandError, IntegrationError


def process_discord_interaction(service, data):
    """Use only with provider-authenticated payloads; never a public JSON entrypoint."""
    if not isinstance(data, dict):
        raise DiscordCommandError(400, "Invalid Discord interaction.")
    if data.get("application_id") != service.discord_application_id:
        raise DiscordCommandError(403, "This Discord application is not supported.")
    if not service.configured("discord"):
        raise DiscordCommandError(
            503, "The Discord bot is not configured. Contact the administrator."
        )
    if data.get("type") == 1:
        return {"type": 1}
    member = data.get("member") or {}
    if not isinstance(member, dict):
        raise DiscordCommandError(400, "Invalid Discord member.")
    user = member.get("user") or data.get("user") or {}
    user_id = user.get("id", "") if isinstance(user, dict) else ""
    command = data.get("data") or {}
    if (
        data.get("type") != 2
        or not isinstance(command, dict)
        or command.get("name") != "peopleflow"
        or not re.fullmatch(r"[0-9]{1,25}", str(user_id))
    ):
        raise DiscordCommandError(400, "Unsupported Discord command.")
    options = command.get("options", [])
    code = ""
    if isinstance(options, list) and len(options) == 1 and isinstance(options[0], dict):
        sub = options[0]
        args = sub.get("options", [])
        if (
            sub.get("name") == "link"
            and isinstance(args, list)
            and len(args) == 1
            and isinstance(args[0], dict)
            and args[0].get("name") == "code"
            and isinstance(args[0].get("value"), str)
        ):
            code = args[0]["value"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{32}", code):
        content = "Generate a link code in Personal notifications in the application, then use /peopleflow link with that code. Roles are assigned by the application."
    else:
        try:
            content = service.accept_link_code(
                "discord", code, str(user_id), service.discord_application_id
            )
        except IntegrationError as exc:
            content = str(exc)
    return {
        "type": 4,
        "data": {"flags": 64, "allowed_mentions": {"parse": []}, "content": content},
    }
