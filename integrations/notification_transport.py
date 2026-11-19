"""Shared payloads and delivery results for private bot notifications."""

import math
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit


def public_app_url(value: str) -> str:
    try:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.hostname in {"hooks.slack.com", "discord.com"}
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.port == 0
            or re.search(r'[\s<>"\\]', value)
        ):
            return ""
        return value.rstrip("/")
    except ValueError:
        return ""


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool = False
    retryable: bool = False
    error_code: str = ""
    retry_after: float = 0


def notification_payload(provider: str, event: dict, base_url: str) -> dict:
    audience = event.get("audience", "manager").title()
    if event["kind"] == "test":
        title = f"PeopleFlow AI · {audience} · Test notification"
        description = (
            "Personal notification delivery is connected. No request was created or changed."
        )
        link = base_url + "/requests"
    else:
        number = f"REQ-{event['number']:06d}"
        names = {
            "new_request": "New request ready for review",
            "information_requested": "More information needed from you",
            "information_provided": "Employee response ready for review",
            "reconsideration_requested": "Reconsideration requested",
            "assigned": "Request assigned to you",
            "cancelled": "Request cancelled by its author",
        }
        title = (
            f"PeopleFlow AI · {audience} · {names.get(event['kind'], 'Request update')} · {number}"
        )

        def label(value):
            return value.replace("_", " ").title()

        instruction = (
            "Your manager needs more information. Open your request to read the question and reply."
            if event["kind"] == "information_requested"
            else "Open your assigned request to review the current details and available actions."
        )
        description = f"{instruction}\nStatus: {label(event['to_status'])}\n{event['occurred_at']}"
        link = base_url + "/requests?request=" + quote(event["request_id"], safe="")
    if provider == "slack":
        return {
            "text": f"{title}\n{description}\n{link}",
            "unfurl_links": False,
            "unfurl_media": False,
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "plain_text", "text": title + "\n" + description},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"<{link}|Open request workspace>"},
                },
            ],
        }
    return {
        "allowed_mentions": {"parse": []},
        "embeds": [{"title": title, "description": description, "url": link}],
    }


def _delay(value) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else 0
    except (TypeError, ValueError):
        return 0
