"""Official bot APIs for verified one-to-one DMs; never fall back to a channel."""

import hashlib
import http.client
import json
import re
import socket
import uuid
from dataclasses import dataclass, field

from integrations.network import ProxyConfigurationError, https_connection
from integrations.notification_transport import DeliveryResult, _delay

_MAX_RESPONSE_BYTES = 65536


@dataclass(frozen=True)
class DirectMessageTarget:
    provider: str
    token: str = field(repr=False)

    @property
    def configured(self) -> bool:
        if not isinstance(self.token, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]{1,512}", self.token
        ):
            return False
        return (self.provider == "slack" and self.token.startswith("xoxb-")) or (
            self.provider == "discord" and not self.token.startswith("xox")
        )


def _valid_user(provider: str, user_id: str) -> bool:
    if not isinstance(user_id, str):
        return False
    pattern = r"[UW][A-Z0-9]{2,31}" if provider == "slack" else r"[1-9][0-9]{5,24}"
    return re.fullmatch(pattern, user_id) is not None


class DirectMessageTransport:
    def __init__(self, timeout: float = 10, connection_factory=None):
        self.timeout = timeout
        self.connection_factory = connection_factory or http.client.HTTPSConnection

    def _post(self, target: DirectMessageTarget, path: str, payload: dict):
        connection = None
        try:
            slack = target.provider == "slack"
            connection = https_connection(
                "slack.com" if slack else "discord.com",
                timeout=self.timeout,
                connection_factory=self.connection_factory,
            )
            connection.set_debuglevel(0)
            connection.request(
                "POST",
                path,
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": ("Bearer " if slack else "Bot ") + target.token,
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "PeopleFlow-Notifications/2.2",
                },
            )
            response = connection.getresponse()
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                return None, DeliveryResult(error_code="unexpected_response")
            try:
                data = json.loads(body)
                if not isinstance(data, dict):
                    data = {}
            except (ValueError, UnicodeError):
                data = {}
            retry_after = max(
                _delay(response.getheader("Retry-After")), _delay(data.get("retry_after"))
            )
            if response.status == 429 or (slack and data.get("error") == "ratelimited"):
                return None, DeliveryResult(
                    retryable=True, error_code="rate_limited", retry_after=retry_after
                )
            if (
                response.status == 408
                or response.status >= 500
                or (
                    slack
                    and data.get("error")
                    in {"internal_error", "fatal_error", "service_unavailable"}
                )
            ):
                return None, DeliveryResult(
                    retryable=True, error_code="provider_unavailable", retry_after=retry_after
                )
            if response.status not in {200, 201} or (slack and data.get("ok") is not True):
                # Never return provider bodies/error messages: these can echo credentials or content.
                if not slack and data.get("code") == 50007:
                    return None, DeliveryResult(error_code="direct_messages_disabled")
                recipient_error = data.get("error") in {
                    "user_not_found",
                    "user_not_visible",
                    "cannot_dm_bot",
                    "channel_not_found",
                }
                return None, DeliveryResult(
                    error_code="recipient_unavailable" if recipient_error else "bot_rejected"
                )
            pause = (
                _delay(response.getheader("X-RateLimit-Reset-After"))
                if response.getheader("X-RateLimit-Remaining") == "0"
                else 0
            )
            return data, DeliveryResult(retry_after=pause)
        except ProxyConfigurationError:
            return None, DeliveryResult(error_code="proxy_configuration")
        except (TimeoutError, socket.timeout):
            return None, DeliveryResult(retryable=True, error_code="timeout")
        except (OSError, http.client.HTTPException):
            return None, DeliveryResult(retryable=True, error_code="network")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    # A cleanup failure must not turn confirmed delivery into a retry.
                    pass

    def send(
        self, target: DirectMessageTarget, user_id: str, payload: dict, delivery_id: str
    ) -> DeliveryResult:
        if not target.configured:
            return DeliveryResult(error_code="configuration")
        if not _valid_user(target.provider, user_id):
            return DeliveryResult(error_code="recipient_unavailable")
        if (
            not isinstance(payload, dict)
            or not isinstance(delivery_id, str)
            or not 1 <= len(delivery_id) <= 128
        ):
            return DeliveryResult(error_code="configuration")
        slack = target.provider == "slack"
        opened, result = self._post(
            target,
            "/api/conversations.open" if slack else "/api/v10/users/@me/channels",
            {"users": user_id, "return_im": True} if slack else {"recipient_id": user_id},
        )
        if opened is None:
            return result
        if slack:
            channel = opened.get("channel")
            if not isinstance(channel, dict) or not (
                isinstance(channel.get("id"), str)
                and re.fullmatch(r"D[A-Z0-9]{2,31}", channel["id"])
                and channel.get("is_im") is True
                and channel.get("user") == user_id
                and not channel.get("is_mpim", False)
            ):
                return DeliveryResult(error_code="recipient_unavailable")
            channel_id = channel["id"]
            message = {key: payload[key] for key in ("text", "blocks") if key in payload}
            message.update(
                {
                    "channel": channel_id,
                    "client_msg_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, "peopleflow:slack:" + delivery_id)
                    ),
                    "unfurl_links": False,
                    "unfurl_media": False,
                    "parse": "none",
                }
            )
            path = "/api/chat.postMessage"
        else:
            recipients = opened.get("recipients")
            if not (
                opened.get("type") == 1
                and isinstance(opened.get("id"), str)
                and re.fullmatch(r"[1-9][0-9]{5,24}", opened["id"])
                and isinstance(recipients, list)
                and len(recipients) == 1
                and isinstance(recipients[0], dict)
                and recipients[0].get("id") == user_id
            ):
                return DeliveryResult(error_code="recipient_unavailable")
            channel_id = opened["id"]
            message = {key: payload[key] for key in ("content", "embeds") if key in payload}
            message.update(
                {
                    "allowed_mentions": {"parse": []},
                    "nonce": hashlib.sha256(
                        ("peopleflow:discord:" + delivery_id).encode()
                    ).hexdigest()[:24],
                    "enforce_nonce": True,
                }
            )
            path = f"/api/v10/channels/{channel_id}/messages"
        sent, result = self._post(target, path, message)
        if sent is None:
            return result
        confirmed = (
            sent.get("channel") == channel_id and bool(sent.get("ts"))
            if slack
            else sent.get("channel_id") == channel_id and bool(sent.get("id"))
        )
        if not confirmed:
            return DeliveryResult(error_code="unexpected_response")
        return DeliveryResult(delivered=True, retry_after=result.retry_after)
