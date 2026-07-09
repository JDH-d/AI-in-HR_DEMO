import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from api.schemas import ChatRequest, Message
from rag.index import build_index_items
from rag.nlp import Intent
from rag.retriever import Retriever
from services.chat_fallbacks import ChatFallbackPolicy
from services.chat_models import RoutingDecision
from services.chat_service import ChatService
from services.document_reader import load_documents
from services.document_service import DocumentService
from services.llm_service import LLMServiceError
from services.rag_service import RAGService
from workflow import WorkflowService


class FailingLLM:
    def generate(self, prompt_messages: list[dict]) -> str:
        raise LLMServiceError("LLM unavailable")


class RecordingLogService:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append_chat(
        self,
        user_text: str,
        assistant_text: str,
        intent: str,
        language: str,
        sources: list[dict] | None = None,
    ) -> None:
        self.entries.append(
            {
                "user": user_text,
                "assistant": assistant_text,
                "intent": intent,
                "language": language,
                "sources": sources,
            }
        )


class ChatServiceTests(unittest.TestCase):
    GUIDED_SALARY_REPLY = (
        "You selected Salary and payroll. What would you like to know?\n"
        "Examples:\n"
        "- How often are salaries paid?\n"
        "- When is payroll processed?\n"
        "- Who should I contact about a payroll issue?"
    )

    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_test_runs" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir = self.temp_dir / "documents"
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        (self.docs_dir / "Payroll_FAQ.md").write_text(
            "Salaries are paid twice per month.\nPayroll is processed on the 15th and last day.",
            encoding="utf-8",
        )
        self.workflow_db = self.temp_dir / "workflow.db"
        self.document_service = DocumentService(self.docs_dir)
        self.log_service = RecordingLogService()
        retriever = Retriever(
            build_index_items(load_documents(self.docs_dir), include_embeddings=False)
        )
        rag_service = RAGService(
            llm_service=FailingLLM(),
            document_service=self.document_service,
            fallback_policy=ChatFallbackPolicy(),
            index_ensurer=lambda: None,
            retriever_provider=lambda: retriever,
        )
        self.service = ChatService(
            workflow_service=WorkflowService(str(self.workflow_db)),
            llm_service=FailingLLM(),
            log_service=self.log_service,
            document_service=self.document_service,
            rag_service=rag_service,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_workflow_request_takes_priority_over_topic_selection(self) -> None:
        request = ChatRequest(
            messages=[
                Message(
                    role="user",
                    content="I need vacation from 2030-04-01 to 2030-04-03",
                )
            ]
        )

        with (
            patch.object(
                self.service.router,
                "route",
                return_value=RoutingDecision(
                    language="en",
                    intent=Intent.WORK,
                    topic_selection="PTO, vacation, and sick leave",
                    explicit_topic_choice=True,
                    prior_topic=None,
                ),
            ),
            patch.object(
                self.service.rag_service,
                "generate_with_fallback",
                return_value="guided response",
            ) as generate_with_fallback,
        ):
            response = self.service.handle_chat(request, created_by="demo-user")

        self.assertEqual(response.intent, "work")
        self.assertIn("I prepared request draft", response.message.content)
        self.assertIsNotNone(response.workflow_request)
        assert response.workflow_request is not None
        self.assertEqual(response.workflow_request.status, "draft")
        generate_with_fallback.assert_not_called()

    def test_policy_question_does_not_create_workflow_draft(self) -> None:
        request = ChatRequest(messages=[Message(role="user", content="How do I request vacation?")])

        response = self.service.handle_chat(request, created_by="demo-user")

        self.assertIsNone(response.workflow_request)
        self.assertEqual(self.service.workflow_service.list_for_user("demo-user"), [])

    def test_explicit_topic_selection_returns_guided_response(self) -> None:
        request = ChatRequest(messages=[Message(role="user", content="2")])

        response = self.service.handle_chat(request, created_by="demo-user")

        self.assertEqual(response.intent, "work")
        self.assertIn("You selected Salary and payroll.", response.message.content)
        self.assertIn("How often are salaries paid?", response.message.content)
        self.assertNotIn("Salaries are paid twice per month.", response.message.content)

    def test_follow_up_question_uses_prior_selected_topic(self) -> None:
        request = ChatRequest(
            messages=[
                Message(role="user", content="2"),
                Message(role="assistant", content=self.GUIDED_SALARY_REPLY),
                Message(role="user", content="How often are they paid?"),
            ]
        )

        response = self.service.handle_chat(request, created_by="demo-user")

        self.assertEqual(response.intent, "work")
        self.assertIn("Salaries are paid twice per month.", response.message.content)

    def test_ambiguous_follow_up_does_not_dump_full_document(self) -> None:
        request = ChatRequest(
            messages=[
                Message(role="user", content="2"),
                Message(role="assistant", content=self.GUIDED_SALARY_REPLY),
                Message(role="user", content="Can you explain?"),
            ]
        )

        response = self.service.handle_chat(request, created_by="demo-user")

        self.assertEqual(response.intent, "work")
        self.assertIn(
            "I can help with Salary and payroll, but I need a more specific question.",
            response.message.content,
        )
        self.assertNotIn("Payroll is processed on the 15th and last day.", response.message.content)

    def test_irrelevant_invalid_message_does_not_reuse_prior_topic(self) -> None:
        request = ChatRequest(
            messages=[
                Message(role="user", content="2"),
                Message(role="assistant", content=self.GUIDED_SALARY_REPLY),
                Message(role="user", content="Tell me a joke"),
            ]
        )

        response = self.service.handle_chat(request, created_by="demo-user")

        self.assertEqual(response.intent, "invalid")
        self.assertIn("I can assist only with supported workplace topics", response.message.content)
        self.assertNotIn("Salaries are paid", response.message.content)

    def test_rag_bootstrap_failure_returns_service_fallback(self) -> None:
        request = ChatRequest(
            messages=[Message(role="user", content="How often are salaries paid?")]
        )

        original_ensurer = self.service.rag_service.index_ensurer
        self.service.rag_service.index_ensurer = Mock(side_effect=RuntimeError("boom"))
        try:
            response = self.service.handle_chat(request, created_by="demo-user")
        finally:
            self.service.rag_service.index_ensurer = original_ensurer

        self.assertEqual(response.intent, "work")
        self.assertIn("The assistant service is temporarily unavailable.", response.message.content)
        self.assertEqual(response.sources, [])


if __name__ == "__main__":
    unittest.main()
