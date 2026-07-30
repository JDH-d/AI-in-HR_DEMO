from __future__ import annotations

import logging
from calendar import month_abbr
from datetime import date
from typing import Callable
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

PostRequest = Callable[..., requests.Response]


class SlackNotificationService:
    def __init__(
        self,
        *,
        enabled: bool,
        actions_enabled: bool = False,
        webhook_url: str,
        public_web_base_url: str,
        timeout_seconds: float = 3.0,
        post_request: PostRequest = requests.post,
    ) -> None:
        self.enabled = enabled
        self.actions_enabled = actions_enabled
        self.webhook_url = webhook_url.strip()
        self.public_web_base_url = public_web_base_url.strip().rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._post_request = post_request

    def notify_request(self, request: dict, employee_name: str) -> bool:
        if not self.enabled:
            return False
        if not self.webhook_url:
            logger.warning("Slack notifications are enabled, but no webhook is configured.")
            return False

        payload = self.build_message(request, employee_name)
        if payload is None:
            return False

        try:
            response = self._post_request(
                self.webhook_url,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Slack notification failed for request %s (%s).",
                _short_id(request),
                type(exc).__name__,
            )
            return False

        if not 200 <= response.status_code < 300:
            logger.warning(
                "Slack notification failed for request %s (HTTP %s).",
                _short_id(request),
                response.status_code,
            )
            return False
        return True

    def build_message(self, request: dict, employee_name: str) -> dict | None:
        status = str(request.get("status", "")).strip().lower()
        if status not in {"in_review", "approved", "declined"}:
            return None

        request_id = _short_id(request)
        status_label = status.replace("_", " ").upper()
        type_label = str(request.get("type_label") or request.get("type") or "Request")
        dates = _format_dates(request.get("start_date"), request.get("end_date"))
        employee = employee_name.strip() or str(request.get("applicant") or "Unknown employee")
        title = (
            f"New request #{request_id}"
            if status == "in_review"
            else f"Request #{request_id} {status.replace('_', ' ')}"
        )
        open_url = self._request_url(str(request.get("id", "")))

        fields = [
            {"type": "mrkdwn", "text": f"*Type:*\n{_escape_mrkdwn(type_label)}"},
            {"type": "mrkdwn", "text": f"*Dates:*\n{_escape_mrkdwn(dates)}"},
            {"type": "mrkdwn", "text": f"*Employee:*\n{_escape_mrkdwn(employee)}"},
            {"type": "mrkdwn", "text": f"*Status:*\n{status_label}"},
        ]
        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title, "emoji": True},
            },
            {"type": "section", "fields": fields},
        ]
        action_elements: list[dict] = []
        full_request_id = str(request.get("id", "")).strip()
        if status == "in_review" and self.actions_enabled and full_request_id:
            action_elements.extend(
                [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Approve",
                            "emoji": True,
                        },
                        "style": "primary",
                        "value": full_request_id,
                        "action_id": "approve_request",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Decline",
                            "emoji": True,
                        },
                        "style": "danger",
                        "value": full_request_id,
                        "action_id": "decline_request",
                    },
                ]
            )
        if open_url:
            action_elements.append(
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Open in Web",
                        "emoji": True,
                    },
                    "url": open_url,
                    "action_id": "open_request_in_web",
                }
            )
        if action_elements:
            blocks.append({"type": "actions", "elements": action_elements})

        return {
            "text": (
                f"{title} | Type: {type_label} | Dates: {dates} | "
                f"Employee: {employee} | Status: {status_label}"
            ),
            "blocks": blocks,
        }

    def _request_url(self, request_id: str) -> str:
        if not self.public_web_base_url or not request_id:
            return ""
        query = urlencode({"request": request_id})
        return f"{self.public_web_base_url}/manager?{query}"


def _short_id(request: dict) -> str:
    return str(request.get("id") or "unknown")[:8]


def _format_dates(start_value: object, end_value: object) -> str:
    start = _parse_date(start_value)
    end = _parse_date(end_value)
    if start is None and end is None:
        return "Not specified"
    if start is None:
        return _format_date(end)
    if end is None or end == start:
        return _format_date(start)
    if start.year == end.year and start.month == end.month:
        return f"{month_abbr[start.month]} {start.day}-{end.day}, {start.year}"
    if start.year == end.year:
        return (
            f"{month_abbr[start.month]} {start.day}-{month_abbr[end.month]} {end.day}, {start.year}"
        )
    return f"{_format_date(start)}-{_format_date(end)}"


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _format_date(value: date | None) -> str:
    if value is None:
        return "Not specified"
    return f"{month_abbr[value.month]} {value.day}, {value.year}"


def _escape_mrkdwn(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
