import unittest
from unittest.mock import Mock, patch

from openai import OpenAIError

from services.llm_service import LLMService, LLMServiceError
from services.openai_client import create_openai_client


class LLMServiceTests(unittest.TestCase):
    def test_generate_uses_single_responses_api_model(self) -> None:
        client = Mock()
        client.responses.create.return_value = Mock(output_text="Grounded answer")
        service = LLMService(
            model="gpt-5-nano-2025-08-07",
            client_factory=lambda: client,
        )
        messages = [{"role": "user", "content": "Question"}]

        result = service.generate(messages)

        self.assertEqual(result, "Grounded answer")
        client.responses.create.assert_called_once_with(
            model="gpt-5-nano-2025-08-07",
            input=messages,
            max_output_tokens=512,
            store=False,
        )
        self.assertFalse(client.chat.completions.create.called)

    def test_generate_rejects_empty_response(self) -> None:
        client = Mock()
        client.responses.create.return_value = Mock(output_text="")
        service = LLMService(model="test-model", client_factory=lambda: client)

        with self.assertRaises(LLMServiceError):
            service.generate([{"role": "user", "content": "Question"}])

    def test_generate_rejects_incomplete_response(self) -> None:
        client = Mock()
        client.responses.create.return_value = Mock(
            output_text="Truncated answer",
            status="incomplete",
        )
        service = LLMService(model="test-model", client_factory=lambda: client)

        with self.assertRaisesRegex(LLMServiceError, "did not complete"):
            service.generate([{"role": "user", "content": "Question"}])

    def test_stream_rejects_failed_event_after_partial_text(self) -> None:
        client = self._streaming_client(
            Mock(type="response.output_text.delta", delta="Partial"),
            Mock(type="response.failed"),
        )
        service = LLMService(model="test-model", client_factory=lambda: client)

        generated = service.stream_generate([{"role": "user", "content": "Question"}])
        self.assertEqual(next(generated), "Partial")
        with self.assertRaisesRegex(LLMServiceError, "did not complete"):
            next(generated)

    def test_stream_rejects_error_event_after_partial_text(self) -> None:
        client = self._streaming_client(
            Mock(type="response.output_text.delta", delta="Partial"),
            Mock(type="error"),
        )
        service = LLMService(model="test-model", client_factory=lambda: client)

        generated = service.stream_generate([{"role": "user", "content": "Question"}])
        self.assertEqual(next(generated), "Partial")
        with self.assertRaisesRegex(LLMServiceError, "did not complete"):
            next(generated)

    def test_stream_requires_completion_event_after_text(self) -> None:
        client = self._streaming_client(
            Mock(type="response.output_text.delta", delta="Partial"),
        )
        service = LLMService(model="test-model", client_factory=lambda: client)

        generated = service.stream_generate([{"role": "user", "content": "Question"}])
        self.assertEqual(next(generated), "Partial")
        with self.assertRaisesRegex(LLMServiceError, "ended before completion"):
            next(generated)

    def test_stream_accepts_text_followed_by_completion_event(self) -> None:
        client = self._streaming_client(
            Mock(type="response.output_text.delta", delta="Complete answer"),
            Mock(type="response.completed"),
        )
        service = LLMService(model="test-model", client_factory=lambda: client)

        self.assertEqual(
            list(service.stream_generate([{"role": "user", "content": "Question"}])),
            ["Complete answer"],
        )

    @patch("services.openai_client.OpenAI")
    def test_client_uses_configured_timeout_and_retries(self, openai_cls: Mock) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-api-key"}):
            create_openai_client()

        kwargs = openai_cls.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "test-api-key")
        self.assertGreater(kwargs["timeout"], 0)
        self.assertGreaterEqual(kwargs["max_retries"], 0)

    def test_placeholder_api_key_is_treated_as_unconfigured(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "your_openai_api_key"}):
            with self.assertRaises(OpenAIError):
                create_openai_client()

    @staticmethod
    def _streaming_client(*events: Mock) -> Mock:
        client = Mock()
        stream = Mock()
        stream.__enter__ = Mock(return_value=iter(events))
        stream.__exit__ = Mock(return_value=None)
        client.responses.stream.return_value = stream
        return client


if __name__ == "__main__":
    unittest.main()
