"""Background delivery orchestration; request business logic never calls a provider."""

import asyncio
import logging
import random
import re
import time

from domain.notifications import ERROR_MESSAGES, PROVIDERS, IntegrationError, IntegrationUnavailable
from integrations.bot_security import verify_discord_signature, verify_slack_signature
from integrations.direct_messages import DirectMessageTarget, DirectMessageTransport
from integrations.discord_commands import process_discord_interaction
from integrations.discord_gateway import DiscordGatewayWorker
from integrations.notification_transport import (
    DeliveryResult,
    notification_payload,
    public_app_url,
)
from services.auth_service import DEMO_IDENTITIES, DemoIdentity
from storage.notification_store import NotificationStore
from storage.personal_notification_store import PersonalNotificationStore

logger = logging.getLogger(__name__)


def _recipient_identity(audience: str, recipient_id: str | None) -> DemoIdentity | None:
    """Resolve the current account, not the primary demo account for its role."""
    if audience not in ("employee", "manager"):
        return None
    return next(
        (
            identity
            for identity in DEMO_IDENTITIES.values()
            if identity.id == recipient_id and identity.role == audience
        ),
        None,
    )


class NotificationService:
    def __init__(
        self,
        db_path,
        *,
        slack_token="",
        discord_token="",
        slack_signing_secret="",
        slack_team_id="",
        discord_public_key="",
        discord_application_id="",
        discord_connection_mode="gateway",
        app_url="",
        transport=None,
        clock=time.time,
    ):
        self.store = NotificationStore(db_path)
        self.targets = {
            "slack": DirectMessageTarget("slack", slack_token),
            "discord": DirectMessageTarget("discord", discord_token),
        }
        self.accounts = PersonalNotificationStore(db_path)
        self.slack_signing_secret = slack_signing_secret
        self.slack_team_id = slack_team_id
        self.discord_public_key = discord_public_key
        self.discord_application_id = discord_application_id
        self.discord_connection_mode = discord_connection_mode
        self.gateway = None
        self.app_url = public_app_url(app_url)
        self.transport = transport or DirectMessageTransport()
        self.clock = clock
        self.ready = False
        self.tasks = []
        self.stopping = None
        self._initialize()

    def _initialize(self):
        try:
            self.store.initialize()
            self.accounts.initialize()
            self.ready = True
        except Exception:
            # Exceptions may contain credentials or private data. Never log their text.
            logger.error("Notification storage unavailable; core workflows remain available")

    def _require_ready(self):
        if not self.ready:
            raise IntegrationUnavailable(
                "Notification storage is temporarily unavailable. Try again later."
            )

    def overview(self):
        self._require_ready()
        items = self.store.overview()
        for item in items:
            item["configured"] = self.configured(item["provider"])
            item["configuration_error"] = (
                ""
                if item["configured"]
                else (
                    "Configure DISCORD_BOT_TOKEN and DISCORD_APPLICATION_ID, then restart. "
                    "DISCORD_CONNECTION_MODE must be gateway or http; HTTP also needs DISCORD_PUBLIC_KEY."
                    if item["provider"] == "discord"
                    else "Configure the Slack bot token, signing secret, workspace ID and APP_PUBLIC_URL, then restart."
                )
            )
            item["recipients"] = {
                role: self.destination(item["provider"], identity.id) is not None
                for role, identity in DEMO_IDENTITIES.items()
                if role in {"employee", "manager"}
            }
            for field in ("last_delivery", "active_delivery"):
                if item[field]:
                    item[field]["error"] = ERROR_MESSAGES.get(item[field].pop("error_code"), "")
        return {"items": items, "app_url": self.app_url}

    def configured(self, provider):
        verification = (
            bool(self.slack_signing_secret and re.fullmatch(r"T[A-Z0-9]+", self.slack_team_id))
            if provider == "slack"
            else bool(
                re.fullmatch(r"[0-9]{1,25}", self.discord_application_id)
                and (
                    self.discord_connection_mode == "gateway"
                    or (
                        self.discord_connection_mode == "http"
                        and re.fullmatch(r"[0-9a-fA-F]{64}", self.discord_public_key)
                    )
                )
            )
        )
        return bool(self.app_url and self.targets[provider].configured and verification)

    def destination(self, provider, user_id):
        link = self.accounts.destination(provider, user_id)
        scope = self.slack_team_id if provider == "slack" else self.discord_application_id
        return link if link and link["external_scope"] == scope else None

    def connections(self, identity):
        self._require_ready()
        states = {item["provider"]: item for item in self.store.overview()}
        items = []
        for provider in PROVIDERS:
            connection = self.accounts.connection(provider, identity.id, self.clock())
            current = self.destination(provider, identity.id) is not None
            items.append(
                {
                    "provider": provider,
                    "configured": self.configured(provider),
                    "enabled": states[provider]["enabled"],
                    **connection,
                    "connected": current,
                    "connection_error": (
                        "The bot workspace or application changed. Disconnect this account and connect again."
                        if connection["external_user_id"] and not current
                        else ""
                    ),
                }
            )
        return {"items": items}

    def link_code(self, provider, identity):
        self._require_ready()
        if not self.configured(provider):
            raise IntegrationError(
                "Ask the administrator to configure this bot first. See the project README for setup."
            )
        result = self.accounts.issue(provider, identity.id, self.clock())
        argument = result["code"] if provider == "slack" else "code:" + result["code"]
        return {**result, "command": "/peopleflow link " + argument}

    def verify_command(self, provider, body, timestamp, signature):
        if not self.configured(provider):
            return False
        verify = verify_slack_signature if provider == "slack" else verify_discord_signature
        key = self.slack_signing_secret if provider == "slack" else self.discord_public_key
        return verify(body, timestamp, signature, key, self.clock())

    def confirm_connection(self, provider, identity, challenge_id):
        self._require_ready()
        if not self.configured(provider):
            raise IntegrationError(
                "The bot configuration changed. Ask the administrator to check it."
            )
        scope = self.slack_team_id if provider == "slack" else self.discord_application_id
        self.accounts.confirm(
            provider, identity.id, challenge_id, self.clock(), expected_scope=scope
        )
        return self.connections(identity)

    def disconnect(self, provider, identity):
        self._require_ready()
        self.accounts.disconnect(provider, identity.id, self.clock())
        return self.connections(identity)

    def accept_link_code(self, provider, code, user_id, scope):
        self._require_ready()
        return self.accounts.claim_code(provider, code, user_id, scope, self.clock())

    def handle_discord_interaction(self, data):
        return process_discord_interaction(self, data)

    def set_enabled(self, provider, enabled, revision, actor):
        self._require_ready()
        if enabled and not self.configured(provider):
            raise IntegrationError(
                "Configure the personal-message bot and command connection on the server before enabling it."
            )
        self.store.set_enabled(provider, enabled, revision, actor, self.clock())
        logger.info(
            "Integration settings provider=%s enabled=%s actor=%s", provider, enabled, actor
        )
        return self.overview()

    def test_notification(self, provider, audience="manager", recipient_id=None):
        self._require_ready()
        if not self.configured(provider):
            raise IntegrationError("Bot configuration is missing or invalid.")
        if recipient_id is None:
            demo = DEMO_IDENTITIES.get(audience)
            recipient_id = demo.id if demo else None
        identity = _recipient_identity(audience, recipient_id)
        if not identity:
            raise IntegrationError("The notification recipient is not available.")
        if not self.destination(provider, identity.id):
            raise IntegrationError(
                f"Connect the {audience.title()} account in Personal notifications first."
            )
        identifier = self.store.enqueue_test(provider, self.clock(), identity.id, identity.role)
        logger.info("Test notification queued provider=%s job=%s", provider, identifier)
        return {"id": identifier, "status": "pending"}

    def run_once(self, provider):
        if not self.ready:
            self._initialize()
        self._require_ready()
        self.store.collect(provider, self.clock())
        if not self.configured(provider):
            return
        job = self.store.claim(provider, self.clock())
        if job is None:
            return
        payload = job["payload"]
        identity = _recipient_identity(payload.get("audience"), payload.get("recipient_id"))
        if not identity or not self.store.is_current_recipient(payload):
            self.store.finish(job, "cancelled", "recipient_unavailable", 0, self.clock(), 0)
            return
        destination = self.destination(provider, identity.id)
        if not destination:
            self.store.finish(job, "failed", "recipient_unlinked", 0, self.clock(), 0)
            return
        try:
            result = self.transport.send(
                self.targets[provider],
                destination["external_user_id"],
                notification_payload(provider, payload, self.app_url),
                job["id"],
            )
        except Exception:
            result = DeliveryResult(retryable=True, error_code="internal")
        now = self.clock()
        retry = result.retryable and job["attempts"] < 5
        status = "delivered" if result.delivered else "pending" if retry else "failed"
        delay = max(result.retry_after, 2 ** job["attempts"] + random.uniform(0, 1)) if retry else 0
        self.store.finish(
            job, status, result.error_code, now + delay, now, max(1.1, result.retry_after)
        )
        logger.log(
            logging.INFO if result.delivered else logging.WARNING,
            "Notification provider=%s job=%s attempt=%s status=%s code=%s",
            provider,
            job["id"],
            job["attempts"],
            status,
            result.error_code,
        )

    def start(self):
        if any(not task.done() for task in self.tasks):
            return
        # Uvicorn configures its own loggers, not the root logger. Keep delivery
        # diagnostics visible without enabling HTTP-client logs that contain URLs.
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
            logger.addHandler(handler)
        self.stopping = asyncio.Event()
        self.tasks = [asyncio.create_task(self._worker(provider)) for provider in PROVIDERS]
        if self.discord_connection_mode == "gateway" and self.configured("discord"):
            try:
                self.gateway = DiscordGatewayWorker(self)
                self.gateway.start()
            except Exception:
                logger.error("Discord Gateway startup failed; core workflows remain available")

    async def _worker(self, provider):
        while not self.stopping.is_set():
            try:
                await asyncio.to_thread(self.run_once, provider)
            except Exception:
                logger.error("Notification worker failed provider=%s code=internal", provider)
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

    async def stop(self):
        if self.stopping:
            self.stopping.set()
        try:
            if self.gateway:
                await self.gateway.stop()
        except Exception:
            logger.error("Discord Gateway cleanup failed; continuing application shutdown")
        finally:
            self.gateway = None
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks = []
