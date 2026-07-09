import os
import unittest
from unittest.mock import MagicMock, patch

from web_ui.api_client import (
    DemoAPIClient,
    extract_assistant_sources,
    extract_workflow_request,
)
from web_ui.demo_prompts import DEMO_PROMPTS, iter_demo_prompts
from web_ui.streamlit_app import (
    MAX_CONTEXT_MESSAGES,
    _build_chat_message_markup,
    _build_messages_payload,
    _build_typing_message_markup,
)


class WebUIHelperTests(unittest.TestCase):
    def test_extract_assistant_sources_reads_chat_response_sources(self) -> None:
        data = {
            "message": {"role": "assistant", "content": "Salaries are paid twice per month."},
            "sources": [
                {
                    "source": "Payroll_FAQ.md",
                    "title": "Payroll and Pay Practices Handbook",
                    "section": "How often are salaries paid?",
                    "category": "Payroll",
                    "version": "2026.1",
                    "excerpt": "Salaries are paid twice per month.",
                    "score": 0.873,
                }
            ],
        }

        sources = extract_assistant_sources(data)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source"], "Payroll_FAQ.md")
        self.assertEqual(sources[0]["title"], "Payroll and Pay Practices Handbook")
        self.assertEqual(sources[0]["section"], "How often are salaries paid?")
        self.assertAlmostEqual(sources[0]["score"], 0.873)

    def test_extract_assistant_sources_ignores_invalid_payload(self) -> None:
        sources = extract_assistant_sources({"message": {"content": "Hello"}})
        self.assertEqual(sources, [])

    def test_extract_workflow_request_reads_draft(self) -> None:
        request = extract_workflow_request(
            {
                "workflow_request": {
                    "id": "request-1",
                    "type": "pto",
                    "status": "draft",
                }
            }
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request["status"], "draft")

    def test_extract_workflow_request_ignores_invalid_payload(self) -> None:
        self.assertIsNone(extract_workflow_request({"workflow_request": {}}))

    def test_build_messages_payload_keeps_latest_valid_turns(self) -> None:
        history = []
        for idx in range(MAX_CONTEXT_MESSAGES + 3):
            history.append({"role": "user", "content": f"user-{idx}"})
        history.append({"role": "tool", "content": "ignore-me"})
        history.append({"role": "assistant", "content": "assistant-final", "sources": []})

        payload = _build_messages_payload(history, "new-question")

        self.assertEqual(len(payload), MAX_CONTEXT_MESSAGES)
        self.assertEqual(payload[-1], {"role": "user", "content": "new-question"})
        self.assertNotIn({"role": "tool", "content": "ignore-me"}, payload)

    def test_build_chat_message_markup_aligns_user_to_the_right(self) -> None:
        markup = _build_chat_message_markup(
            "user",
            "Hello <world>",
            "data:image/png;base64,user",
        )

        self.assertIn('class="chat-row user-row"', markup)
        self.assertIn('class="chat-stack user-stack"', markup)
        self.assertIn('class="user-bubble">Hello &lt;world&gt;</div>', markup)
        self.assertNotIn("\n", markup)

    def test_build_chat_message_markup_renders_assistant_sources(self) -> None:
        markup = _build_chat_message_markup(
            "assistant",
            "Payroll answer",
            "data:image/png;base64,assistant",
            sources=[
                {
                    "source": "Payroll_FAQ.md",
                    "title": "Payroll and Pay Practices Handbook",
                    "section": "How often are salaries paid?",
                    "category": "Payroll",
                    "version": "2026.1",
                    "score": 0.87,
                    "excerpt": "Employees are paid twice per month.",
                }
            ],
        )

        self.assertIn('class="chat-row assistant-row"', markup)
        self.assertIn("Sources used", markup)
        self.assertIn("Payroll and Pay Practices Handbook", markup)
        self.assertIn("How often are salaries paid?", markup)
        self.assertNotIn("Payroll_FAQ.md#0", markup)
        self.assertIn("Employees are paid twice per month.", markup)
        self.assertNotIn("0.87", markup)

    def test_build_chat_message_markup_can_render_typing_cursor(self) -> None:
        markup = _build_chat_message_markup(
            "assistant",
            "Streaming answer",
            "data:image/png;base64,assistant",
            show_cursor=True,
        )

        self.assertIn("typing-caret", markup)

    def test_build_typing_message_markup_renders_typing_bubble(self) -> None:
        markup = _build_typing_message_markup("data:image/png;base64,assistant")

        self.assertIn("typing-bubble", markup)
        self.assertIn("typing-dots", markup)

    def test_demo_prompt_pack_has_expected_size_and_coverage(self) -> None:
        prompts = iter_demo_prompts(DEMO_PROMPTS)

        self.assertEqual(len(prompts), 25)
        self.assertEqual(len(prompts), len(set(prompts)))
        self.assertEqual(len(DEMO_PROMPTS), 7)
        self.assertIn("Hello", prompts)
        self.assertIn("Hi there", prompts)
        self.assertIn("Write me a poem about dragons.", prompts)
        self.assertIn("What's the weather in Los Angeles today?", prompts)

    def test_demo_api_client_reads_api_base_url_at_init_time(self) -> None:
        original_api_base_url = os.environ.get("API_BASE_URL")
        try:
            os.environ["API_BASE_URL"] = "http://127.0.0.1:8016"
            client = DemoAPIClient()
        finally:
            if original_api_base_url is None:
                os.environ.pop("API_BASE_URL", None)
            else:
                os.environ["API_BASE_URL"] = original_api_base_url

        self.assertEqual(client.api_base_url, "http://127.0.0.1:8016")

    @patch("web_ui.api_client.requests.Session")
    def test_demo_api_client_disables_env_proxies_for_loopback_urls(
        self, session_factory: MagicMock
    ) -> None:
        session = MagicMock()
        session.request.return_value = object()
        session_factory.return_value = session

        client = DemoAPIClient(api_base_url="http://127.0.0.1:8016")
        client.request("GET", "/health")

        self.assertFalse(session.trust_env)
        session.request.assert_called_once()
        session.close.assert_called_once()

    @patch("web_ui.api_client.requests.Session")
    def test_demo_api_client_keeps_env_proxies_for_remote_urls(
        self, session_factory: MagicMock
    ) -> None:
        session = MagicMock()
        session.request.return_value = object()
        session_factory.return_value = session

        client = DemoAPIClient(api_base_url="https://demo.example.com")
        client.request("GET", "/health")

        self.assertTrue(session.trust_env)
        session.request.assert_called_once()
        session.close.assert_called_once()

    @patch("web_ui.api_client.requests.Session")
    def test_chat_uses_v1_bearer_auth_without_x_user(self, session_factory: MagicMock) -> None:
        session = MagicMock()
        session.request.return_value = object()
        session_factory.return_value = session

        client = DemoAPIClient(api_base_url="http://127.0.0.1:8016")
        client.chat([{"role": "user", "content": "Hello"}], "signed-token")

        args, kwargs = session.request.call_args
        self.assertEqual(args[1], "http://127.0.0.1:8016/api/v1/chat")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer signed-token")
        self.assertNotIn("X-User", kwargs["headers"])


if __name__ == "__main__":
    unittest.main()
