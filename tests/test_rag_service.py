import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rag.nlp import Intent
from services.chat_fallbacks import ChatFallbackPolicy
from services.chat_models import ChatQuery, ChatTurn, RoutingDecision
from services.document_service import DocumentService
from services.llm_service import LLMServiceError
from services.rag_service import RAGService


class FailingLLM:
    def generate(self, prompt_messages: list[dict]) -> str:
        raise LLMServiceError("LLM unavailable")


class RecordingLLM:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def generate(self, prompt_messages: list[dict]) -> str:
        self.messages = prompt_messages
        return "General guidance only; confirm the company-specific rule with HR."


class RAGServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_test_runs" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        (self.temp_dir / "documents").mkdir(parents=True, exist_ok=True)
        self.rag_service = RAGService(
            llm_service=FailingLLM(),
            document_service=DocumentService(self.temp_dir / "documents"),
            fallback_policy=ChatFallbackPolicy(),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_answer_with_retrieval_uses_extractive_fallback_when_llm_is_unavailable(self) -> None:
        query = ChatQuery(messages=[ChatTurn(role="user", content="How often are salaries paid?")])
        decision = RoutingDecision(
            language="en",
            intent=Intent.WORK,
            topic_selection=None,
            explicit_topic_choice=False,
            prior_topic=None,
        )
        retriever = Mock()
        retriever.query.return_value = [
            {
                "source": "Payroll_FAQ.md",
                "document_id": "payroll-faq",
                "title": "Payroll and Pay Practices Handbook",
                "category": "Payroll",
                "version": "2026.1",
                "section": "How often are salaries paid?",
                "chunk_id": 0,
                "text": "Salaries are paid on the fifteenth and the last business day of the month. Direct deposit is the standard payment method.",
                "excerpt": "Salaries are paid on the fifteenth and the last business day of the month.",
                "score": 0.82,
            }
        ]

        with (
            patch("services.rag_service.ensure_index"),
            patch("services.rag_service.get_retriever", return_value=retriever),
        ):
            outcome = self.rag_service.answer_with_retrieval(query, decision)

        self.assertIn(
            "Salaries are paid on the fifteenth and the last business day of the month.",
            outcome.content,
        )
        self.assertEqual(len(outcome.sources), 1)
        self.assertEqual(outcome.sources[0].source, "Payroll_FAQ.md")
        self.assertEqual(outcome.sources[0].section, "How often are salaries paid?")

    def test_invalid_router_intent_becomes_work_when_documents_match(self) -> None:
        query = ChatQuery(
            messages=[ChatTurn(role="user", content="What is the office dress code?")]
        )
        decision = RoutingDecision(
            language="en",
            intent=Intent.INVALID,
            topic_selection=None,
            explicit_topic_choice=False,
            prior_topic=None,
        )
        retriever = Mock()
        retriever.query.return_value = [
            {
                "source": "Office_Guide.md",
                "document_id": "office-guide",
                "title": "Office Guide",
                "category": "Workplace",
                "version": "2026.1",
                "section": "Dress Code",
                "chunk_id": 0,
                "text": "Employees should use business casual attire for customer meetings.",
                "excerpt": "Employees should use business casual attire for customer meetings.",
                "score": 0.76,
            }
        ]
        self.rag_service.index_ensurer = lambda: None
        self.rag_service.retriever_provider = lambda: retriever

        outcome = self.rag_service.answer_with_retrieval(query, decision)

        self.assertEqual(outcome.intent, Intent.WORK)
        self.assertEqual(outcome.sources[0].title, "Office Guide")

    def test_general_guidance_is_available_only_when_strict_grounding_is_disabled(self) -> None:
        llm = RecordingLLM()
        service = RAGService(
            llm_service=llm,
            document_service=DocumentService(self.temp_dir / "documents"),
            fallback_policy=ChatFallbackPolicy(),
            index_ensurer=lambda: None,
            retriever_provider=lambda: Mock(query=Mock(return_value=[])),
        )
        query = ChatQuery(
            messages=[ChatTurn(role="user", content="What is the relocation process?")]
        )
        decision = RoutingDecision(
            language="en",
            intent=Intent.WORK,
            topic_selection=None,
            explicit_topic_choice=False,
            prior_topic=None,
        )

        strict = service.answer_with_retrieval(
            query,
            decision,
            settings={"strict_grounding": True},
        )
        general = service.answer_with_retrieval(
            query,
            decision,
            settings={
                "strict_grounding": False,
                "concise_answers": False,
                "ask_clarifying_questions": False,
                "suggest_next_steps": False,
            },
            system_prompt="Custom preview behavior",
        )

        self.assertIn("could not find a reliable answer", strict.content)
        self.assertEqual(
            general.content,
            "General guidance only; confirm the company-specific rule with HR.",
        )
        system_text = llm.messages[0]["content"][0]["text"]
        self.assertIn("Custom preview behavior", system_text)
        self.assertIn("not confirmed company policy", system_text)


if __name__ == "__main__":
    unittest.main()
