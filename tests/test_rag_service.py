import unittest
from unittest.mock import Mock

from rag.nlp import Intent
from services.chat_fallbacks import ChatFallbackPolicy
from services.chat_models import ChatQuery, ChatTurn, RoutingDecision
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
        self.knowledge_index = Mock()
        self.rag_service = RAGService(
            llm_service=FailingLLM(),
            fallback_policy=ChatFallbackPolicy(),
            knowledge_index=self.knowledge_index,
        )

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

        self.knowledge_index.get_retriever.return_value = retriever

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
        self.knowledge_index.get_retriever.return_value = retriever

        outcome = self.rag_service.answer_with_retrieval(query, decision)

        self.assertEqual(outcome.intent, Intent.WORK)
        self.assertEqual(outcome.sources[0].title, "Office Guide")

    def test_general_guidance_is_available_only_when_strict_grounding_is_disabled(self) -> None:
        llm = RecordingLLM()
        service = RAGService(
            llm_service=llm,
            fallback_policy=ChatFallbackPolicy(),
            knowledge_index=Mock(
                ensure=Mock(),
                get_retriever=Mock(return_value=Mock(query=Mock(return_value=[]))),
            ),
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
