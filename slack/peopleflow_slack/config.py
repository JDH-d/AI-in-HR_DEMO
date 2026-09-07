from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT.parent


def _seconds(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        raise ValueError(f"{name} must be a number of seconds.") from None


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)
    app_token: str = field(repr=False)
    employee_user_id: str
    team_id: str
    api_url: str = "http://127.0.0.1:8000"
    password: str = field(default="demo-password", repr=False)
    poll_interval: float = 8.0
    api_timeout: float = 90.0
    state_path: Path = ROOT / ".state" / "slack.db"
    app_id: str = ""

    @classmethod
    def load(cls, env_path: Path | None = None) -> Settings:
        load_dotenv(env_path or PROJECT_ROOT / ".env", override=False, encoding="utf-8-sig")
        api_url = os.getenv("PEOPLEFLOW_API_URL", "http://127.0.0.1:8000").rstrip("/")
        launcher = os.getenv("PEOPLEFLOW_LAUNCHER_STATE", "").strip()
        if not launcher and not os.getenv("PEOPLEFLOW_API_URL"):
            default_state = PROJECT_ROOT / ".demo_state" / "demo_processes.json"
            if default_state.is_file():
                launcher = str(default_state)
        if launcher:
            try:
                launcher_data = json.loads(Path(launcher).read_text(encoding="utf-8-sig"))
                if not isinstance(launcher_data, dict) or not isinstance(
                    launcher_data.get("api_url"), str
                ):
                    raise ValueError("Invalid launcher state.")
                api_url = launcher_data["api_url"]
            except (OSError, ValueError, KeyError):
                raise ValueError(
                    "Cannot read PEOPLEFLOW_LAUNCHER_STATE; check the launcher path."
                ) from None
        value = cls(
            bot_token=os.getenv("SLACK_BOT_TOKEN", "").strip(),
            app_token=os.getenv("SLACK_APP_TOKEN", "").strip(),
            employee_user_id=os.getenv("SLACK_EMPLOYEE_USER_ID", "").strip(),
            team_id=os.getenv("SLACK_TEAM_ID", "").strip(),
            app_id=os.getenv("SLACK_APP_ID", "").strip(),
            api_url=api_url.rstrip("/"),
            password=os.getenv(
                "PEOPLEFLOW_DEMO_PASSWORD", os.getenv("DEMO_LOGIN_PASSWORD", "demo-password")
            ),
            poll_interval=_seconds("POLL_INTERVAL_SECONDS", "8"),
            api_timeout=_seconds("API_TIMEOUT_SECONDS", "90"),
        )
        value.validate()
        return value

    def validate(self) -> None:
        if not self.bot_token.startswith("xoxb-"):
            raise ValueError("Set SLACK_BOT_TOKEN in the root .env to your bot token (xoxb-...).")
        if not self.app_token.startswith("xapp-"):
            raise ValueError(
                "Set SLACK_APP_TOKEN in the root .env to your Socket Mode token (xapp-...)."
            )
        if not re.fullmatch(r"[UW][A-Z0-9]+", self.employee_user_id):
            raise ValueError("Set SLACK_EMPLOYEE_USER_ID to the demo employee's Slack member ID.")
        if not re.fullmatch(r"T[A-Z0-9]+", self.team_id):
            raise ValueError("Set SLACK_TEAM_ID to the installed workspace ID.")
        if self.app_id and not re.fullmatch(r"A[A-Z0-9]+", self.app_id):
            raise ValueError("SLACK_APP_ID must be the installed app's ID.")
        try:
            parsed = urlparse(self.api_url)
            valid_url = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
                and (parsed.port is None or 1 <= parsed.port <= 65535)
            )
        except (TypeError, ValueError):
            valid_url = False
        if not valid_url:
            raise ValueError(
                "PEOPLEFLOW_API_URL must be an HTTP(S) API origin without credentials, query, "
                "or fragment."
            )
        if not isinstance(self.password, str) or not self.password:
            raise ValueError("Set a non-empty PeopleFlow demo password.")
        if (
            isinstance(self.poll_interval, bool)
            or not isinstance(self.poll_interval, (int, float))
            or not math.isfinite(self.poll_interval)
            or not 2 <= self.poll_interval <= 300
        ):
            raise ValueError("POLL_INTERVAL_SECONDS must be between 2 and 300.")
        if (
            isinstance(self.api_timeout, bool)
            or not isinstance(self.api_timeout, (int, float))
            or not math.isfinite(self.api_timeout)
            or not 5 <= self.api_timeout <= 300
        ):
            raise ValueError("API_TIMEOUT_SECONDS must be between 5 and 300.")
