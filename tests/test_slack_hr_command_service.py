import unittest
from unittest.mock import Mock

from api.schemas import ChatResponse, Message, SourceChunk
from services.slack_hr_command_service import (
    SLACK_HR_ERROR_MESSAGE,
    SLACK_HR_USAGE_MESSAGE,
    SlackHRCommandService,
)


class SlackHRCommandServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chat_service = Mock()
        self.service = SlackHRCommandService(self.chat_service)
        self.ack = Mock()
        self.respond = Mock()

    def test_question_uses_existing_chat_service_and_returns_sources(self) -> None:
        self.chat_service.handle_chat.return_value = ChatResponse(
            message=Message(
                role="assistant",
                content="Salaries are paid twice per month.",
            ),
            intent="payroll",
            language="en",
            sources=[
                SourceChunk(
                    source="documents/Payroll_FAQ.md",
                    title="Payroll and Pay Practices Handbook",
                    section="How often are salaries paid?",
                    category="payroll",
                    version="1.0",
                    excerpt="Employees are paid twice per month.",
                    score=0.91,
                ),
                SourceChunk(
                    source="documents/Payroll_FAQ.md",
                    title="Payroll and Pay Practices Handbook",
                    section="Payroll Schedule and Payday Logic",
                    category="payroll",
                    version="1.0",
                    excerpt="Pay dates follow the published payroll calendar.",
                    score=0.84,
                ),
                SourceChunk(
                    source="documents/Payroll_FAQ.md",
                    title="Payroll and Pay Practices Handbook",
                    section="How often are salaries paid?",
                    category="payroll",
                    version="1.0",
                    excerpt="Employees are paid twice per month.",
                    score=0.8,
                ),
            ],
        )

        self.service.handle_command(
            ack=self.ack,
            command={
                "text": "  When are salaries paid?  ",
                "user_id": "U_EMPLOYEE",
            },
            respond=self.respond,
        )

        self.ack.assert_called_once_with()
        self.chat_service.handle_chat.assert_called_once()
        request = self.chat_service.handle_chat.call_args.args[0]
        self.assertEqual(len(request.messages), 1)
        self.assertEqual(request.messages[0].role, "user")
        self.assertEqual(request.messages[0].content, "When are salaries paid?")
        self.assertEqual(
            self.chat_service.handle_chat.call_args.kwargs,
            {
                "created_by": "slack:U_EMPLOYEE",
                "allow_workflow": False,
            },
        )
        response_call = self.respond.call_args.kwargs
        self.assertEqual(response_call["response_type"], "in_channel")
        self.assertIn("Salaries are paid twice per month.", response_call["text"])
        self.assertIn("Question: When are salaries paid?", response_call["text"])
        self.assertNotIn("Payroll_FAQ.md", response_call["text"])
        self.assertEqual(
            [block["type"] for block in response_call["blocks"]],
            ["section", "divider", "section", "divider", "section"],
        )
        block_text = "\n".join(
            block["text"]["text"]
            for block in response_call["blocks"]
            if block["type"] == "section"
        )
        self.assertIn("*Question*\n> When are salaries paid?", block_text)
        self.assertIn("*Answer*\nSalaries are paid twice per month.", block_text)
        self.assertEqual(block_text.count("*Payroll and Pay Practices Handbook*"), 1)
        self.assertEqual(block_text.count("• How often are salaries paid?"), 1)
        self.assertIn("• Payroll Schedule and Payday Logic", block_text)
        self.assertNotIn(".md", block_text)

    def test_response_without_sources_still_shows_question_and_answer(self) -> None:
        self.chat_service.handle_chat.return_value = ChatResponse(
            message=Message(role="assistant", content="Hello. How can I help?"),
            intent="small_talk",
            language="en",
            sources=[],
        )

        self.service.handle_command(
            ack=self.ack,
            command={"text": "Hello", "user_id": "U_EMPLOYEE"},
            respond=self.respond,
        )

        response_call = self.respond.call_args.kwargs
        self.assertEqual(
            [block["type"] for block in response_call["blocks"]],
            ["section", "divider", "section"],
        )
        self.assertNotIn("Sources:", response_call["text"])
        self.assertIn("Question: Hello", response_call["text"])

    def test_empty_question_returns_ephemeral_usage_hint(self) -> None:
        self.service.handle_command(
            ack=self.ack,
            command={"text": "   ", "user_id": "U_EMPLOYEE"},
            respond=self.respond,
        )

        self.ack.assert_called_once_with()
        self.chat_service.handle_chat.assert_not_called()
        self.respond.assert_called_once_with(
            text=SLACK_HR_USAGE_MESSAGE,
            response_type="ephemeral",
        )

    def test_service_error_is_ephemeral_and_hides_technical_details(self) -> None:
        self.chat_service.handle_chat.side_effect = RuntimeError(
            "secret database connection details"
        )

        self.service.handle_command(
            ack=self.ack,
            command={"text": "What is the PTO policy?", "user_id": "U_EMPLOYEE"},
            respond=self.respond,
        )

        self.ack.assert_called_once_with()
        self.respond.assert_called_once_with(
            text=SLACK_HR_ERROR_MESSAGE,
            response_type="ephemeral",
        )
        self.assertNotIn("secret", self.respond.call_args.kwargs["text"])


if __name__ == "__main__":
    unittest.main()
