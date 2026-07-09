from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core import settings


def _getenv(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _getint(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = _getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


@dataclass(frozen=True)
class TeamsBotSettings:
    app_id: str
    app_password: str
    tenant_id: str
    history_db: Path
    max_context_messages: int
    max_source_count: int
    enabled: bool

    @classmethod
    def from_env(cls) -> "TeamsBotSettings":
        app_id = _getenv("MicrosoftAppId", "MICROSOFT_APP_ID", "TEAMS_BOT_APP_ID")
        app_password = _getenv(
            "MicrosoftAppPassword",
            "MICROSOFT_APP_PASSWORD",
            "TEAMS_BOT_APP_PASSWORD",
        )
        tenant_id = _getenv(
            "MicrosoftAppTenantId",
            "MICROSOFT_APP_TENANT_ID",
            "TEAMS_BOT_TENANT_ID",
        )
        history_db = settings._resolve_path(  # pylint: disable=protected-access
            _getenv("TEAMS_BOT_HISTORY_DB", default="data/teams_conversations.db")
        )
        return cls(
            app_id=app_id,
            app_password=app_password,
            tenant_id=tenant_id,
            history_db=history_db,
            max_context_messages=_getint("TEAMS_BOT_MAX_CONTEXT", 12, 1, 64),
            max_source_count=_getint("TEAMS_BOT_MAX_SOURCES", 3, 0, 10),
            enabled=_getenv("TEAMS_BOT_ENABLED", default="true").lower()
            not in {"0", "false", "no", "off"},
        )

