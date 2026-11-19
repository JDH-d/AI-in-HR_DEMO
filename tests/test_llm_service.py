import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import PermissionDeniedError

from integrations.embedding_service import EmbeddingError, EmbeddingService
from integrations.llm_service import LLMService, LLMServiceError
from integrations.openai_client import create_openai_client


class LLMServiceTests(unittest.TestCase):
    def test_generate_uses_single_responses_api_model(self) -> None:
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            status="completed", output_text="Grounded answer"
        )
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
        client.responses.create.return_value = SimpleNamespace(status="completed", output_text="")
        service = LLMService(model="test-model", client_factory=lambda: client)

        with self.assertRaises(LLMServiceError):
            service.generate([{"role": "user", "content": "Question"}])

    def test_selection_budget_override_does_not_change_later_answer_budget(self) -> None:
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(status="completed", output_text="{}")
        service = LLMService("test-model", client_factory=lambda: client)
        messages = [{"role": "user", "content": "Question"}]

        service.generate(messages, max_output_tokens=1536)
        service.generate(messages)

        self.assertEqual(
            client.responses.create.call_args_list[0].kwargs["max_output_tokens"], 1536
        )
        self.assertEqual(client.responses.create.call_args_list[1].kwargs["max_output_tokens"], 512)

    def test_generate_rejects_truncated_text_without_retrying(self) -> None:
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            status="incomplete",
            output_text="Employees must submit their request before",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        )
        service = LLMService(model="test-model", client_factory=lambda: client)

        with self.assertLogs("integrations.llm_service", level="WARNING") as logs:
            with self.assertRaises(LLMServiceError):
                service.generate([{"role": "user", "content": "Question"}])

        self.assertIn("max_output_tokens", " ".join(logs.output))
        client.responses.create.assert_called_once()

    def test_generate_rejects_failed_response_even_with_text(self) -> None:
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            status="failed", output_text="Partial text", incomplete_details=None
        )
        service = LLMService(model="test-model", client_factory=lambda: client)

        with self.assertRaises(LLMServiceError):
            service.generate([{"role": "user", "content": "Question"}])

    def test_model_access_errors_log_safe_metadata_for_both_adapters(self) -> None:
        error = PermissionDeniedError(
            "Do not log this private provider message",
            response=httpx.Response(
                403,
                request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
                headers={"x-request-id": "request-test"},
            ),
            body={"code": "model_not_found", "message": "private-provider-text"},
        )
        client = Mock()
        client.responses.create.side_effect = error
        client.embeddings.create.side_effect = error
        llm = LLMService(model="test-model", client_factory=lambda: client)
        embeddings = EmbeddingService(client_factory=lambda: client)

        with self.assertLogs("integrations", level="WARNING") as logs:
            with self.assertRaises(LLMServiceError):
                llm.generate([{"role": "user", "content": "Private question"}])
            with self.assertRaises(EmbeddingError):
                embeddings.embed(["Private document"])

        self.assertEqual(len(logs.output), 2)
        for record in logs.output:
            self.assertIn("status=403", record)
            self.assertIn("code=model_not_found", record)
            self.assertIn("request-test", record)
            self.assertNotIn("private", record.lower())

    @patch("integrations.openai_client.OpenAI")
    def test_client_uses_configured_timeout_and_retries(self, openai_cls: Mock) -> None:
        with patch("integrations.openai_client.settings.OPENAI_API_KEY", "test-key"):
            create_openai_client()

        kwargs = openai_cls.call_args.kwargs
        self.assertGreater(kwargs["timeout"], 0)
        self.assertGreaterEqual(kwargs["max_retries"], 0)


if __name__ == "__main__":
    unittest.main()
