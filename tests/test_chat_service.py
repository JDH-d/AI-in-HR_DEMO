from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from rag.index import build_index_items
from rag.nlp import Intent
from rag.retriever import Retriever
from services.chat_fallbacks import ChatFallbackPolicy
from services.chat_models import ChatQuery, ChatTurn, RoutingDecision
from services.chat_service import ChatService
from services.document_reader import load_documents
from services.llm_service import LLMServiceError
from services.rag_service import RAGService
from workflow import WorkflowService


class FailingLLM:
    def generate(self, prompt_messages: list[dict]) -> str:
        raise LLMServiceError("LLM unavailable")

    def stream_generate(self, prompt_messages: list[dict]):
        raise LLMServiceError("LLM unavailable")
        yield ""  # pragma: no cover


class StreamingLLM(FailingLLM):
    def stream_generate(self, prompt_messages: list[dict]):
        yield "Grounded "
        yield "answer"


class EmptyStreamingLLM(FailingLLM):
    def stream_generate(self, prompt_messages: list[dict]):
        if False:
            yield ""


class PartialFailingLLM(FailingLLM):
    def stream_generate(self, prompt_messages: list[dict]):
        yield "Incomplete"
        raise LLMServiceError("connection dropped")


class StaticKnowledgeIndex:
    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever
        self.ensure_calls = 0

    def ensure(self) -> None:
        self.ensure_calls += 1

    def get_retriever(self) -> Retriever:
        return self.retriever


class FailingKnowledgeIndex(StaticKnowledgeIndex):
    def ensure(self) -> None:
        raise RuntimeError("index unavailable")


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
        outcome_code: str = "unknown",
    ) -> None:
        self.entries.append(
            {
                "user": user_text,
                "assistant": assistant_text,
                "intent": intent,
                "language": language,
                "sources": sources,
                "outcome_code": outcome_code,
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
            "# Payroll\n\n## How often are salaries paid?\n\n"
            "Salaries are paid twice per month. Payroll is processed on the 15th and last day.",
            encoding="utf-8",
        )
        retriever = Retriever(
            build_index_items(load_documents(self.docs_dir), include_embeddings=False)
        )
        self.knowledge_index = StaticKnowledgeIndex(retriever)
        self.log_service = RecordingLogService()
        self.service = self._build_service(FailingLLM())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _build_service(self, llm, *, knowledge_index=None) -> ChatService:
        active_index = knowledge_index or self.knowledge_index
        rag_service = RAGService(
            llm_service=llm,
            fallback_policy=ChatFallbackPolicy(),
            knowledge_index=active_index,
        )
        return ChatService(
            workflow_service=WorkflowService(str(self.temp_dir / "workflow.db")),
            llm_service=llm,
            log_service=self.log_service,
            rag_service=rag_service,
        )

    @staticmethod
    def _query(content: str, *earlier: ChatTurn) -> ChatQuery:
        return ChatQuery(messages=[*earlier, ChatTurn(role="user", content=content)])

    def test_workflow_request_takes_priority_over_topic_selection(self) -> None:
        query = self._query("I need vacation from 2030-04-01 to 2030-04-03")

        with patch.object(
            self.service.router,
            "route",
            return_value=RoutingDecision(
                language="en",
                intent=Intent.WORK,
                topic_selection="PTO, vacation, and sick leave",
                explicit_topic_choice=True,
                prior_topic=None,
            ),
        ):
            outcome = self.service.respond(query, created_by="demo-user")

        self.assertEqual(outcome.intent, Intent.WORK)
        self.assertIn("I've prepared a PTO draft", outcome.content)
        self.assertIsNotNone(outcome.workflow_request)
        assert outcome.workflow_request is not None
        self.assertEqual(outcome.workflow_request["status"], "draft")
        self.assertEqual(outcome.outcome_code, "workflow")

    def test_policy_question_does_not_create_workflow_draft(self) -> None:
        outcome = self.service.respond(
            self._query("How do I request vacation?"),
            created_by="demo-user",
        )

        self.assertIsNone(outcome.workflow_request)
        self.assertEqual(self.service.workflow_service.list_for_user("demo-user"), [])

    def test_request_usage_question_gives_a_clear_next_step_without_retrieval(self) -> None:
        for question in (
            "How can I request time off?",
            "How do I request vacation?",
            "What is the process for requesting PTO?",
        ):
            with self.subTest(question=question):
                outcome = self.service.respond(self._query(question), created_by="demo-user")
                self.assertIn("start and end dates", outcome.content)
                self.assertIn("review", outcome.content)
                self.assertIn("only when you send it", outcome.content)
                self.assertIsNone(outcome.workflow_request)
        self.assertEqual(self.knowledge_index.ensure_calls, 0)
        self.assertEqual(self.service.workflow_service.list_for_user("demo-user"), [])

    def test_sick_leave_usage_explains_review_without_medical_details(self) -> None:
        outcome = self.service.respond(
            self._query("How do I report sick leave?"), created_by="demo-user"
        )
        self.assertIn("Medical details aren't needed", outcome.content)
        self.assertIn("only after you review and send", outcome.content)
        self.assertIsNone(outcome.workflow_request)

    def test_policy_constraints_still_use_company_documents(self) -> None:
        self.service.respond(
            self._query("How far in advance should I request vacation?"), created_by="demo-user"
        )
        self.assertEqual(self.knowledge_index.ensure_calls, 1)
        self.assertEqual(self.service.workflow_service.list_for_user("demo-user"), [])

    def test_slack_pto_example_returns_the_shared_draft_with_no_submission(self) -> None:
        outcome = self.service.respond(
            self._query("I want PTO from 2026-09-21 to 2026-09-23. Planned time off."),
            created_by="demo-user",
        )
        draft = outcome.workflow_request
        assert draft is not None
        self.assertEqual((draft["start_date"], draft["end_date"]), ("2026-09-21", "2026-09-23"))
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["validation_errors"], [])
        self.assertNotIn(draft["id"], outcome.content)
        history = self.service.workflow_service.history(draft["id"])
        self.assertEqual([event["to_status"] for event in history["events"]], ["draft"])

    def test_abandoned_workflow_stream_discards_its_private_draft(self) -> None:
        updates = self.service.stream(
            self._query("I need vacation from 2030-04-01 to 2030-04-03"),
            created_by="demo-user",
        )

        first = next(updates)
        self.assertEqual(first.kind, "token")
        self.assertEqual(len(self.service.workflow_service.list_for_user("demo-user")), 1)

        updates.close()

        self.assertEqual(self.service.workflow_service.list_for_user("demo-user"), [])

    def test_completed_workflow_stream_keeps_its_draft(self) -> None:
        updates = list(
            self.service.stream(
                self._query("I need vacation from 2030-04-01 to 2030-04-03"),
                created_by="demo-user",
            )
        )

        self.assertEqual(updates[-1].kind, "complete")
        self.assertEqual(len(self.service.workflow_service.list_for_user("demo-user")), 1)

    def test_hr_support_shortcut_returns_fixed_demo_handoff(self) -> None:
        outcome = self.service.respond(
            self._query("I need help from HR"),
            created_by="demo-user",
        )

        self.assertEqual(outcome.intent, Intent.WORK)
        self.assertEqual(
            outcome.content,
            "Contacting HR is a simulated interaction in this demo. No HR ticket has been sent. "
            "I can help with company policies, time off, and sick leave.",
        )
        self.assertEqual(outcome.sources, [])
        self.assertIsNone(outcome.workflow_request)
        self.assertEqual(outcome.outcome_code, "handoff_demo")

    def test_explicit_topic_selection_returns_guided_response(self) -> None:
        outcome = self.service.respond(self._query("2"), created_by="demo-user")

        self.assertEqual(outcome.intent, Intent.WORK)
        self.assertIn("You selected Salary and payroll.", outcome.content)
        self.assertIn("How often are salaries paid?", outcome.content)
        self.assertNotIn("Salaries are paid twice per month.", outcome.content)

    def test_follow_up_question_uses_prior_selected_topic_and_history(self) -> None:
        query = self._query(
            "How often are they paid?",
            ChatTurn(role="user", content="2"),
            ChatTurn(role="assistant", content=self.GUIDED_SALARY_REPLY),
        )

        outcome = self.service.respond(query, created_by="demo-user")

        self.assertEqual(outcome.intent, Intent.WORK)
        self.assertIn("Salaries are paid twice per month.", outcome.content)
        self.assertEqual(outcome.outcome_code, "grounded")

    def test_ambiguous_follow_up_asks_for_a_specific_question(self) -> None:
        query = self._query(
            "Can you explain?",
            ChatTurn(role="user", content="2"),
            ChatTurn(role="assistant", content=self.GUIDED_SALARY_REPLY),
        )

        outcome = self.service.respond(query, created_by="demo-user")

        self.assertIn(
            "I can help with Salary and payroll, but I need a more specific question.",
            outcome.content,
        )
        self.assertNotIn("Payroll is processed on the 15th", outcome.content)

    def test_irrelevant_invalid_message_does_not_reuse_prior_topic_or_log(self) -> None:
        query = self._query(
            "Tell me a joke",
            ChatTurn(role="user", content="2"),
            ChatTurn(role="assistant", content=self.GUIDED_SALARY_REPLY),
        )

        outcome = self.service.respond(query, created_by="demo-user")

        self.assertEqual(outcome.intent, Intent.INVALID)
        self.assertIn("I can assist only with supported workplace topics", outcome.content)
        self.assertNotIn("Salaries are paid", outcome.content)
        self.assertEqual(self.log_service.entries, [])

    def test_preview_mode_creates_no_request_and_writes_no_log(self) -> None:
        outcome = self.service.respond(
            self._query("I need vacation from 2030-04-01 to 2030-04-03"),
            created_by="knowledge-admin",
            log_outcome=False,
            allow_workflow=False,
        )

        self.assertIsNone(outcome.workflow_request)
        self.assertEqual(
            self.service.workflow_service.list_for_user("knowledge-admin"),
            [],
        )
        self.assertEqual(self.log_service.entries, [])

    def test_index_bootstrap_failure_returns_service_fallback(self) -> None:
        service = self._build_service(
            FailingLLM(),
            knowledge_index=FailingKnowledgeIndex(self.knowledge_index.retriever),
        )

        outcome = service.respond(
            self._query("How often are salaries paid?"),
            created_by="demo-user",
        )

        self.assertEqual(outcome.intent, Intent.WORK)
        self.assertIn("The assistant service is temporarily unavailable.", outcome.content)
        self.assertEqual(outcome.sources, [])
        self.assertEqual(outcome.outcome_code, "unavailable")

    def test_stream_for_rag_answer_forwards_real_model_deltas(self) -> None:
        service = self._build_service(StreamingLLM())

        updates = list(
            service.stream(
                self._query("How often are salaries paid?"),
                created_by="demo-user",
            )
        )

        self.assertEqual(
            [update.content for update in updates if update.kind == "token"],
            ["Grounded ", "answer"],
        )
        self.assertEqual(updates[-1].kind, "complete")
        assert updates[-1].outcome is not None
        self.assertEqual(updates[-1].outcome.content, "Grounded answer")

    def test_partial_stream_failure_replaces_incomplete_model_text(self) -> None:
        service = self._build_service(PartialFailingLLM())

        updates = list(
            service.stream(
                self._query("How often are salaries paid?"),
                created_by="demo-user",
            )
        )

        self.assertEqual(updates[0].content, "Incomplete")
        self.assertEqual(updates[1].kind, "replace")
        self.assertIn("Salaries are paid twice per month.", updates[1].content)
        assert updates[-1].outcome is not None
        self.assertEqual(updates[-1].outcome.content, updates[1].content)

    def test_empty_model_stream_uses_grounded_fallback(self) -> None:
        service = self._build_service(EmptyStreamingLLM())

        updates = list(
            service.stream(
                self._query("How often are salaries paid?"),
                created_by="demo-user",
            )
        )

        self.assertEqual(updates[0].kind, "token")
        self.assertIn("Salaries are paid twice per month.", updates[0].content)
        assert updates[-1].outcome is not None
        self.assertEqual(updates[-1].outcome.content, updates[0].content)


if __name__ == "__main__":
    unittest.main()
