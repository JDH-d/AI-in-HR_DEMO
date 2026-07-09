import unittest
from unittest.mock import Mock, patch

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

    @patch("services.openai_client.OpenAI")
    def test_client_uses_configured_timeout_and_retries(self, openai_cls: Mock) -> None:
        create_openai_client()

        kwargs = openai_cls.call_args.kwargs
        self.assertGreater(kwargs["timeout"], 0)
        self.assertGreaterEqual(kwargs["max_retries"], 0)


if __name__ == "__main__":
    unittest.main()
