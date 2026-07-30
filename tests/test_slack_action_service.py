import shutil
import unittest
from copy import deepcopy
from pathlib import Path

import requests

from services.slack_action_service import (
    DECLINE_REASON_ACTION_ID,
    DECLINE_REASON_BLOCK_ID,
    DECLINE_VIEW_CALLBACK_ID,
    SlackActionService,
)
from services.slack_notification_service import SlackNotificationService
from workflow import WorkflowService


class _Ack:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


class _Response:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class _SlackClient:
    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.ephemeral_messages: list[dict] = []
        self.opened_views: list[dict] = []

    def chat_update(self, **kwargs) -> None:
        self.updates.append(kwargs)

    def chat_postEphemeral(self, **kwargs) -> None:
        self.ephemeral_messages.append(kwargs)

    def views_open(self, **kwargs) -> None:
        self.opened_views.append(kwargs)


class _SocketHandler:
    def __init__(self, app, app_token: str) -> None:
        self.app = app
        self.app_token = app_token
        self.connected = False
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True


class SlackActionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.workflow = WorkflowService(str(self.temp_dir / "workflow.db"))
        self.request = self._review_request()
        self.response_updates: list[dict] = []
        notifier = SlackNotificationService(
            enabled=True,
            actions_enabled=True,
            webhook_url="https://example.test/slack-webhook",
            public_web_base_url="http://127.0.0.1:5173",
        )
        self.service = SlackActionService(
            enabled=True,
            bot_token="xoxb-test",
            app_token="xapp-test",
            manager_user_ids=["U_MANAGER"],
            workflow_service=self.workflow,
            notification_service=notifier,
            post_request=self._post_response_update,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_authorized_manager_can_approve_and_card_is_updated(self) -> None:
        ack = _Ack()
        client = _SlackClient()

        self.service.handle_approve(
            ack=ack,
            body=self._action_body(),
            client=client,
        )

        self.assertEqual(ack.calls, [((), {})])
        self.assertEqual(self._current_request()["status"], "approved")
        self.assertEqual(client.updates, [])
        self.assertEqual(len(self.response_updates), 1)
        self.assertEqual(
            self.response_updates[0]["url"],
            "https://hooks.slack.com/actions/test-response",
        )
        self.assertTrue(
            self.response_updates[0]["json"]["replace_original"]
        )
        updated_buttons = self.response_updates[0]["json"]["blocks"][2]["elements"]
        self.assertEqual(
            [button["action_id"] for button in updated_buttons],
            ["open_request_in_web"],
        )
        self.assertEqual(client.ephemeral_messages, [])

    def test_non_manager_slack_user_cannot_change_request(self) -> None:
        ack = _Ack()
        client = _SlackClient()
        body = self._action_body()
        body["user"]["id"] = "U_EMPLOYEE"

        self.service.handle_approve(ack=ack, body=body, client=client)

        self.assertEqual(self._current_request()["status"], "in_review")
        self.assertEqual(client.updates, [])
        self.assertEqual(self.response_updates, [])
        self.assertEqual(len(client.ephemeral_messages), 1)
        self.assertIn("not authorized", client.ephemeral_messages[0]["text"])

    def test_decline_button_opens_required_reason_modal(self) -> None:
        ack = _Ack()
        client = _SlackClient()

        self.service.handle_decline(
            ack=ack,
            body=self._action_body(),
            client=client,
        )

        self.assertEqual(ack.calls, [((), {})])
        self.assertEqual(self._current_request()["status"], "in_review")
        self.assertEqual(len(client.opened_views), 1)
        view = client.opened_views[0]["view"]
        self.assertEqual(view["callback_id"], DECLINE_VIEW_CALLBACK_ID)
        reason_input = view["blocks"][0]
        self.assertEqual(reason_input["type"], "input")
        self.assertNotIn("optional", reason_input)

    def test_blank_decline_reason_keeps_modal_open(self) -> None:
        client = _SlackClient()
        view = self._opened_decline_view(client)
        view["state"] = {
            "values": {
                DECLINE_REASON_BLOCK_ID: {
                    DECLINE_REASON_ACTION_ID: {"value": "   "}
                }
            }
        }
        ack = _Ack()

        self.service.handle_decline_submission(
            ack=ack,
            body={"user": {"id": "U_MANAGER"}, "view": view},
            view=view,
            client=client,
        )

        self.assertEqual(self._current_request()["status"], "in_review")
        self.assertEqual(len(ack.calls), 1)
        self.assertEqual(
            ack.calls[0][1]["response_action"],
            "errors",
        )
        self.assertIn(
            DECLINE_REASON_BLOCK_ID,
            ack.calls[0][1]["errors"],
        )

    def test_decline_reason_is_saved_in_existing_web_history(self) -> None:
        client = _SlackClient()
        view = self._opened_decline_view(client)
        view["state"] = {
            "values": {
                DECLINE_REASON_BLOCK_ID: {
                    DECLINE_REASON_ACTION_ID: {
                        "value": "Coverage is unavailable"
                    }
                }
            }
        }
        ack = _Ack()

        self.service.handle_decline_submission(
            ack=ack,
            body={
                "user": {"id": "U_MANAGER"},
                "channel": {"id": "C_REQUESTS"},
                "view": view,
            },
            view=view,
            client=client,
        )

        self.assertEqual(ack.calls, [((), {})])
        self.assertEqual(self._current_request()["status"], "declined")
        history = self.workflow.history(self.request["id"])
        self.assertEqual(
            history["events"][-1]["details"]["comment"],
            "Coverage is unavailable",
        )
        self.assertEqual(len(self.response_updates), 1)

    def test_repeated_decision_is_rejected_without_second_transition(self) -> None:
        client = _SlackClient()
        self.service.handle_approve(
            ack=_Ack(),
            body=self._action_body(),
            client=client,
        )

        self.service.handle_approve(
            ack=_Ack(),
            body=self._action_body(),
            client=client,
        )

        history = self.workflow.history(self.request["id"])
        self.assertEqual(
            [event["to_status"] for event in history["events"]],
            ["draft", "in_review", "approved"],
        )
        self.assertEqual(len(self.response_updates), 2)
        self.assertEqual(client.ephemeral_messages, [])

    def test_slack_update_failure_does_not_rollback_decision(self) -> None:
        client = _SlackClient()

        def failing_post(*args, **kwargs):
            raise requests.Timeout("Slack update unavailable")

        self.service._post_request = failing_post

        self.service.handle_approve(
            ack=_Ack(),
            body=self._action_body(),
            client=client,
        )

        self.assertEqual(self._current_request()["status"], "approved")
        self.assertEqual(len(client.ephemeral_messages), 1)
        self.assertIn("decision was saved", client.ephemeral_messages[0]["text"])

    def test_incomplete_configuration_does_not_start_socket_mode(self) -> None:
        notifier = SlackNotificationService(
            enabled=True,
            actions_enabled=True,
            webhook_url="https://example.test/slack-webhook",
            public_web_base_url="http://127.0.0.1:5173",
        )
        service = SlackActionService(
            enabled=True,
            bot_token="",
            app_token="",
            manager_user_ids=[],
            workflow_service=self.workflow,
            notification_service=notifier,
        )

        self.assertFalse(service.start())

    def test_complete_configuration_starts_and_stops_socket_mode(self) -> None:
        handlers: list[_SocketHandler] = []

        def handler_factory(app, app_token: str) -> _SocketHandler:
            handler = _SocketHandler(app, app_token)
            handlers.append(handler)
            return handler

        notifier = SlackNotificationService(
            enabled=True,
            actions_enabled=True,
            webhook_url="https://example.test/slack-webhook",
            public_web_base_url="http://127.0.0.1:5173",
        )
        service = SlackActionService(
            enabled=True,
            bot_token="xoxb-test",
            app_token="xapp-test",
            manager_user_ids=["U_MANAGER"],
            workflow_service=self.workflow,
            notification_service=notifier,
            handler_factory=handler_factory,
        )

        self.assertTrue(service.start())
        self.assertEqual(len(handlers), 1)
        self.assertTrue(handlers[0].connected)
        service.stop()
        self.assertTrue(handlers[0].closed)

    def _opened_decline_view(self, client: _SlackClient) -> dict:
        self.service.handle_decline(
            ack=_Ack(),
            body=self._action_body(),
            client=client,
        )
        return deepcopy(client.opened_views[0]["view"])

    def _action_body(self) -> dict:
        return {
            "user": {"id": "U_MANAGER"},
            "channel": {"id": "C_REQUESTS"},
            "message": {"ts": "1720000000.000100"},
            "trigger_id": "trigger-123",
            "response_url": "https://hooks.slack.com/actions/test-response",
            "actions": [{"value": self.request["id"]}],
        }

    def _review_request(self) -> dict:
        draft = self.workflow.create_structured_draft(
            request_type="pto",
            start_date="2030-04-10",
            end_date="2030-04-12",
            comment="Family vacation",
            applicant="employee.demo",
            approver="manager.demo",
        )
        return self.workflow.confirm_draft(draft["id"], "employee.demo", {})

    def _current_request(self) -> dict:
        return self.workflow.history(self.request["id"])["request"]

    def _post_response_update(self, url: str, **kwargs) -> _Response:
        self.response_updates.append({"url": url, **kwargs})
        return _Response()


if __name__ == "__main__":
    unittest.main()
