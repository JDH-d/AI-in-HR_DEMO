import shutil
import unittest
from pathlib import Path

from api.schemas import ChatResponse, Message, SourceChunk
from teams_bot.bot import TeamsPersonalChatBot
from teams_bot.formatting import format_chat_response, normalize_teams_text
from teams_bot.history import TeamsConversationHistory


class RecordingChatService:
    def __init__(self) -> None:
        self.calls: list[tuple[list[Message], str]] = []

    def handle_chat(self, req, created_by: str) -> ChatResponse:
        self.calls.append((req.messages, created_by))
        return ChatResponse(
            message=Message(role="assistant", content="Salaries are paid twice per month."),
            intent="work",
            language="en",
            sources=[
                SourceChunk(
                    source="documents/Payroll_FAQ.md",
                    chunk_id=2,
                    text="Salaries are paid twice per month.",
                    score=0.83,
                )
            ],
        )


class TeamsFormattingTests(unittest.TestCase):
    def test_normalize_teams_text_removes_html_tags(self) -> None:
        self.assertEqual(
            normalize_teams_text("<div>How&nbsp;often are salaries paid?</div>"),
            "How often are salaries paid?",
        )

    def test_format_chat_response_appends_document_sources(self) -> None:
        response = ChatResponse(
            message=Message(role="assistant", content="Use payroll policy."),
            intent="work",
            language="en",
            sources=[
                SourceChunk(
                    source="documents/Payroll_FAQ.md",
                    chunk_id=4,
                    text="Payroll policy text",
                    score=0.72,
                )
            ],
        )

        formatted = format_chat_response(response)

        self.assertIn("Use payroll policy.", formatted)
        self.assertIn("**Sources**", formatted)
        self.assertIn("Payroll_FAQ.md - chunk 4, score 0.72", formatted)


class TeamsBotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_test_runs" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.history = TeamsConversationHistory(self.temp_dir / "teams_history.db")
        self.chat_service = RecordingChatService()
        self.bot = TeamsPersonalChatBot(
            chat_service=self.chat_service,
            history=self.history,
            max_context_messages=4,
            max_source_count=2,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_respond_uses_chat_service_and_stores_history(self) -> None:
        response = await self.bot._respond("tenant:conversation:user", "aad-user", "Question?")

        self.assertIn("Salaries are paid twice per month.", response)
        self.assertIn("Payroll_FAQ.md", response)
        self.assertEqual(len(self.chat_service.calls), 1)
        messages, created_by = self.chat_service.calls[0]
        self.assertEqual(created_by, "aad-user")
        self.assertEqual([(m.role, m.content) for m in messages], [("user", "Question?")])

        stored = self.history.load("tenant:conversation:user", 4)
        self.assertEqual(
            [(message.role, message.content) for message in stored],
            [
                ("user", "Question?"),
                ("assistant", "Salaries are paid twice per month."),
            ],
        )

    async def test_respond_reuses_prior_turn_context(self) -> None:
        await self.bot._respond("tenant:conversation:user", "aad-user", "First?")
        await self.bot._respond("tenant:conversation:user", "aad-user", "Follow up?")

        messages, _ = self.chat_service.calls[-1]
        self.assertEqual(
            [(message.role, message.content) for message in messages],
            [
                ("user", "First?"),
                ("assistant", "Salaries are paid twice per month."),
                ("user", "Follow up?"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
