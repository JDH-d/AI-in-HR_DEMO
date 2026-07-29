import unittest

import requests

from services.slack_notification_service import SlackNotificationService


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class SlackNotificationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = {
            "id": "a31f99c2d6e94aa6",
            "type": "pto",
            "type_label": "PTO",
            "start_date": "2030-04-10",
            "end_date": "2030-04-12",
            "applicant": "employee.demo",
            "status": "in_review",
        }

    def test_builds_english_block_message_with_web_link(self) -> None:
        service = SlackNotificationService(
            enabled=True,
            webhook_url="https://example.test/slack-webhook",
            public_web_base_url="http://127.0.0.1:5173",
        )

        payload = service.build_message(self.request, "Demo Employee")

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["blocks"][0]["text"]["text"], "New request #a31f99c2")
        fields = [field["text"] for field in payload["blocks"][1]["fields"]]
        self.assertIn("*Type:*\nPTO", fields)
        self.assertIn("*Dates:*\nApr 10-12, 2030", fields)
        self.assertIn("*Employee:*\nDemo Employee", fields)
        self.assertIn("*Status:*\nIN REVIEW", fields)
        button = payload["blocks"][2]["elements"][0]
        self.assertEqual(button["text"]["text"], "Open in Web")
        self.assertEqual(
            button["url"],
            "http://127.0.0.1:5173/manager?request=a31f99c2d6e94aa6",
        )

    def test_ignores_drafts(self) -> None:
        service = SlackNotificationService(
            enabled=True,
            webhook_url="https://example.test/slack-webhook",
            public_web_base_url="http://127.0.0.1:5173",
        )
        self.request["status"] = "draft"

        self.assertIsNone(service.build_message(self.request, "Demo Employee"))

    def test_disabled_notifications_make_no_http_request(self) -> None:
        calls: list[dict] = []

        def post_request(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            return _Response(200)

        service = SlackNotificationService(
            enabled=False,
            webhook_url="https://example.test/slack-webhook",
            public_web_base_url="http://127.0.0.1:5173",
            post_request=post_request,
        )

        self.assertFalse(service.notify_request(self.request, "Demo Employee"))
        self.assertEqual(calls, [])

    def test_http_failure_is_reported_without_raising(self) -> None:
        def post_request(*args, **kwargs):
            raise requests.Timeout("demo timeout")

        service = SlackNotificationService(
            enabled=True,
            webhook_url="https://example.test/slack-webhook",
            public_web_base_url="http://127.0.0.1:5173",
            post_request=post_request,
        )

        self.assertFalse(service.notify_request(self.request, "Demo Employee"))


if __name__ == "__main__":
    unittest.main()
