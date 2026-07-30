from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import requests

from services.auth_service import DEMO_IDENTITIES, DemoIdentity
from services.request_decision_service import decide_request
from workflow import (
    InvalidTransitionError,
    WorkflowNotFoundError,
    WorkflowPermissionError,
    WorkflowService,
    WorkflowValidationError,
)

from .slack_notification_service import SlackNotificationService

logger = logging.getLogger(__name__)

APPROVE_ACTION_ID = "approve_request"
DECLINE_ACTION_ID = "decline_request"
DECLINE_VIEW_CALLBACK_ID = "decline_request_modal"
DECLINE_REASON_BLOCK_ID = "decline_reason_block"
DECLINE_REASON_ACTION_ID = "decline_reason"
ALREADY_DECIDED_MESSAGE = "This request has already been decided."
REQUEST_NOT_FOUND_MESSAGE = "Request not found."
MANAGER_NOT_ALLOWED_MESSAGE = "You are not allowed to manage this request."
DECLINE_REASON_REQUIRED_MESSAGE = (
    "Please enter a reason for declining this request."
)
PostRequest = Callable[..., requests.Response]


class SlackActionService:
    def __init__(
        self,
        *,
        enabled: bool,
        bot_token: str,
        app_token: str,
        manager_user_ids: list[str],
        workflow_service: WorkflowService,
        notification_service: SlackNotificationService,
        handler_factory: Callable[[Any, str], Any] | None = None,
        post_request: PostRequest = requests.post,
        response_timeout_seconds: float = 3.0,
    ) -> None:
        self.enabled = enabled
        self.bot_token = bot_token.strip()
        self.app_token = app_token.strip()
        self.manager_user_ids = frozenset(
            user_id.strip() for user_id in manager_user_ids if user_id.strip()
        )
        self.workflow_service = workflow_service
        self.notification_service = notification_service
        self._handler_factory = handler_factory
        self._post_request = post_request
        self.response_timeout_seconds = response_timeout_seconds
        self._handler: Any | None = None

    def start(self) -> bool:
        if not self.enabled:
            return False
        if self._handler is not None:
            return True
        if not self.bot_token or not self.app_token or not self.manager_user_ids:
            logger.warning(
                "Slack actions are enabled, but their local configuration is incomplete."
            )
            return False

        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler

            bolt_app = App(
                token=self.bot_token,
                token_verification_enabled=False,
            )
            bolt_app.action(APPROVE_ACTION_ID)(self.handle_approve)
            bolt_app.action(DECLINE_ACTION_ID)(self.handle_decline)
            bolt_app.view(DECLINE_VIEW_CALLBACK_ID)(
                self.handle_decline_submission
            )
            factory = self._handler_factory or SocketModeHandler
            handler = factory(bolt_app, self.app_token)
            handler.connect()
            self._handler = handler
        except Exception as exc:
            logger.warning(
                "Slack Socket Mode could not start (%s).",
                type(exc).__name__,
            )
            return False

        logger.info("Slack request actions are connected through Socket Mode.")
        return True

    def stop(self) -> None:
        handler = self._handler
        self._handler = None
        if handler is None:
            return
        try:
            handler.close()
        except Exception as exc:
            logger.warning(
                "Slack Socket Mode could not close cleanly (%s).",
                type(exc).__name__,
            )

    def handle_approve(self, ack, body: dict, client, **_: Any) -> None:
        ack()
        context = self._action_context(body)
        if context is None:
            self._post_ephemeral(
                client,
                body,
                "This Slack action is missing request context. Open the request in Web.",
            )
            return
        request_id, slack_user_id, channel_id, message_ts, response_url = context
        identity = self._manager_identity(slack_user_id)
        if identity is None:
            self._post_ephemeral(
                client,
                body,
                MANAGER_NOT_ALLOWED_MESSAGE,
            )
            return

        try:
            request = decide_request(
                self.workflow_service,
                request_id=request_id,
                target="approved",
                identity=identity,
            )
        except InvalidTransitionError:
            try:
                current = self._read_request(request_id)
            except WorkflowNotFoundError:
                self._post_ephemeral(client, body, REQUEST_NOT_FOUND_MESSAGE)
                return
            self._update_original_message(
                client,
                body,
                channel_id,
                response_url,
                current,
            )
            self._post_ephemeral(client, body, ALREADY_DECIDED_MESSAGE)
            return
        except (
            WorkflowNotFoundError,
            WorkflowPermissionError,
            WorkflowValidationError,
        ) as exc:
            self._post_ephemeral(client, body, self._decision_error_message(exc))
            return

        self._update_original_message(
            client,
            body,
            channel_id,
            response_url,
            request,
        )

    def handle_decline(self, ack, body: dict, client, **_: Any) -> None:
        ack()
        context = self._action_context(body)
        if context is None:
            self._post_ephemeral(
                client,
                body,
                "This Slack action is missing request context. Open the request in Web.",
            )
            return
        request_id, slack_user_id, channel_id, message_ts, response_url = context
        if self._manager_identity(slack_user_id) is None:
            self._post_ephemeral(
                client,
                body,
                MANAGER_NOT_ALLOWED_MESSAGE,
            )
            return

        trigger_id = str(body.get("trigger_id") or "").strip()
        if not trigger_id:
            self._post_ephemeral(
                client,
                body,
                "Slack could not open the decline form. Open the request in Web.",
            )
            return

        metadata = json.dumps(
            {
                "request_id": request_id,
                "channel_id": channel_id,
                "message_ts": message_ts,
                "response_url": response_url,
            },
            separators=(",", ":"),
        )
        try:
            client.views_open(
                trigger_id=trigger_id,
                view=self._decline_modal(metadata),
            )
        except Exception as exc:
            logger.warning(
                "Slack decline modal could not open for request %s (%s).",
                request_id[:8],
                type(exc).__name__,
            )
            self._post_ephemeral(
                client,
                body,
                "Slack could not open the decline form. Open the request in Web.",
            )

    def handle_decline_submission(
        self,
        ack,
        body: dict,
        client,
        view: dict | None = None,
        **_: Any,
    ) -> None:
        submitted_view = view or body.get("view") or {}
        slack_user_id = str((body.get("user") or {}).get("id") or "").strip()
        identity = self._manager_identity(slack_user_id)
        if identity is None:
            ack(
                response_action="errors",
                errors={
                    DECLINE_REASON_BLOCK_ID: MANAGER_NOT_ALLOWED_MESSAGE
                },
            )
            return

        reason = str(
            (
                (
                    (submitted_view.get("state") or {}).get("values") or {}
                ).get(DECLINE_REASON_BLOCK_ID)
                or {}
            ).get(DECLINE_REASON_ACTION_ID, {}).get("value")
            or ""
        ).strip()
        if not reason:
            ack(
                response_action="errors",
                errors={
                    DECLINE_REASON_BLOCK_ID: DECLINE_REASON_REQUIRED_MESSAGE
                },
            )
            return

        metadata = self._parse_private_metadata(submitted_view)
        if metadata is None:
            ack(
                response_action="errors",
                errors={
                    DECLINE_REASON_BLOCK_ID: (
                        "This Slack action is missing request context. "
                        "Open the request in Web."
                    )
                },
            )
            return
        request_id, channel_id, message_ts, response_url = metadata

        try:
            request = decide_request(
                self.workflow_service,
                request_id=request_id,
                target="declined",
                identity=identity,
                comment=reason,
            )
        except (
            InvalidTransitionError,
            WorkflowNotFoundError,
            WorkflowPermissionError,
            WorkflowValidationError,
        ) as exc:
            ack(
                response_action="errors",
                errors={
                    DECLINE_REASON_BLOCK_ID: self._decision_error_message(exc)
                },
            )
            return

        ack()
        self._update_original_message(
            client,
            body,
            channel_id,
            response_url,
            request,
        )

    def _manager_identity(self, slack_user_id: str) -> DemoIdentity | None:
        if slack_user_id not in self.manager_user_ids:
            return None
        identity = DEMO_IDENTITIES["manager"]
        return identity if identity.role == "manager" else None

    @staticmethod
    def _action_context(
        body: dict,
    ) -> tuple[str, str, str, str, str] | None:
        actions = body.get("actions") or []
        action = actions[0] if actions else {}
        request_id = str(action.get("value") or "").strip()
        slack_user_id = str((body.get("user") or {}).get("id") or "").strip()
        channel_id = str((body.get("channel") or {}).get("id") or "").strip()
        message_ts = str((body.get("message") or {}).get("ts") or "").strip()
        response_url = str(body.get("response_url") or "").strip()
        if not all(
            (request_id, slack_user_id, channel_id, message_ts, response_url)
        ):
            return None
        return request_id, slack_user_id, channel_id, message_ts, response_url

    @staticmethod
    def _parse_private_metadata(
        view: dict,
    ) -> tuple[str, str, str, str] | None:
        try:
            metadata = json.loads(str(view.get("private_metadata") or ""))
        except json.JSONDecodeError:
            return None
        request_id = str(metadata.get("request_id") or "").strip()
        channel_id = str(metadata.get("channel_id") or "").strip()
        message_ts = str(metadata.get("message_ts") or "").strip()
        response_url = str(metadata.get("response_url") or "").strip()
        if not all((request_id, channel_id, message_ts, response_url)):
            return None
        return request_id, channel_id, message_ts, response_url

    @staticmethod
    def _decline_modal(private_metadata: str) -> dict:
        return {
            "type": "modal",
            "callback_id": DECLINE_VIEW_CALLBACK_ID,
            "private_metadata": private_metadata,
            "title": {
                "type": "plain_text",
                "text": "Decline request",
                "emoji": True,
            },
            "submit": {
                "type": "plain_text",
                "text": "Decline",
                "emoji": True,
            },
            "close": {
                "type": "plain_text",
                "text": "Cancel",
                "emoji": True,
            },
            "blocks": [
                {
                    "type": "input",
                    "block_id": DECLINE_REASON_BLOCK_ID,
                    "optional": True,
                    "label": {
                        "type": "plain_text",
                        "text": "Reason",
                        "emoji": True,
                    },
                    "element": {
                        "type": "plain_text_input",
                        "action_id": DECLINE_REASON_ACTION_ID,
                        "multiline": True,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Explain why this request is declined",
                            "emoji": True,
                        },
                    },
                }
            ],
        }

    def _update_original_message(
        self,
        client,
        body: dict,
        channel_id: str,
        response_url: str,
        request: dict,
    ) -> None:
        employee_name = self._display_name_for(str(request.get("applicant") or ""))
        payload = self.notification_service.build_message(request, employee_name)
        if payload is None:
            self._post_ephemeral(
                client,
                body,
                "The decision was saved, but Slack could not refresh this card.",
            )
            return
        try:
            response = self._post_request(
                response_url,
                json={
                    "replace_original": True,
                    "text": payload["text"],
                    "blocks": payload["blocks"],
                },
                timeout=self.response_timeout_seconds,
            )
            if not 200 <= response.status_code < 300:
                raise requests.HTTPError(
                    f"Slack response URL returned HTTP {response.status_code}"
                )
        except requests.RequestException as exc:
            logger.warning(
                "Slack card could not refresh for request %s (%s).",
                str(request.get("id") or "unknown")[:8],
                type(exc).__name__,
            )
            failure_body = {
                **body,
                "channel": {"id": channel_id},
            }
            self._post_ephemeral(
                client,
                failure_body,
                (
                    "The decision was saved in PeopleFlow, but Slack could not "
                    "refresh this card. Open it in Web to see the current status."
                ),
            )

    def _read_request(self, request_id: str) -> dict:
        return self.workflow_service.history(request_id)["request"]

    @staticmethod
    def _post_ephemeral(client, body: dict, text: str) -> None:
        channel_id = str((body.get("channel") or {}).get("id") or "").strip()
        slack_user_id = str((body.get("user") or {}).get("id") or "").strip()
        if not channel_id or not slack_user_id:
            return
        try:
            client.chat_postEphemeral(
                channel=channel_id,
                user=slack_user_id,
                text=text,
            )
        except Exception as exc:
            logger.warning(
                "Slack could not show an action result (%s).",
                type(exc).__name__,
            )

    @staticmethod
    def _decision_error_message(exc: Exception) -> str:
        if isinstance(exc, InvalidTransitionError):
            return ALREADY_DECIDED_MESSAGE
        if isinstance(exc, WorkflowNotFoundError):
            return REQUEST_NOT_FOUND_MESSAGE
        if isinstance(exc, WorkflowPermissionError):
            return MANAGER_NOT_ALLOWED_MESSAGE
        if isinstance(exc, WorkflowValidationError):
            return str(exc)
        return "PeopleFlow could not process this Slack action."

    @staticmethod
    def _display_name_for(identity_id: str) -> str:
        identity = next(
            (item for item in DEMO_IDENTITIES.values() if item.id == identity_id),
            None,
        )
        return identity.display_name if identity else identity_id
