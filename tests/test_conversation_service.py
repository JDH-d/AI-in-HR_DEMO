from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.conversation_service import ConversationNotFoundError, ConversationService


class ConversationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = ConversationService(Path(self.temp_dir.name) / "peopleflow.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_exchange_is_persisted_and_first_question_becomes_title(self) -> None:
        detail = self.service.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="How far in advance should I request vacation for my trip?",
            assistant_content="Submit the request at least two weeks ahead.",
            sources=[{"title": "PTO Policy", "section": "Notice"}],
        )

        self.assertEqual(detail["conversation"]["message_count"], 2)
        self.assertEqual(
            detail["conversation"]["title"],
            "How far in advance should I request vacation for my…",
        )
        self.assertEqual(
            [message["role"] for message in detail["messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(detail["messages"][1]["sources"][0]["title"], "PTO Policy")
        self.assertEqual(
            self.service.list_for_user("employee.demo")[0]["id"],
            detail["conversation"]["id"],
        )

    def test_history_stays_empty_until_a_complete_exchange_is_recorded(self) -> None:

        self.assertEqual(self.service.list_for_user("employee.demo"), [])

    def test_history_is_scoped_to_its_owner(self) -> None:
        detail = self.service.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="When is payroll processed?",
            assistant_content="Twice per month.",
        )
        conversation_id = detail["conversation"]["id"]

        self.assertIsNone(self.service.get_for_user(conversation_id, "another.employee"))
        self.assertEqual(self.service.list_for_user("another.employee"), [])
        with self.assertRaises(ConversationNotFoundError):
            self.service.record_exchange(
                "another.employee",
                conversation_id=conversation_id,
                user_content="Show me that conversation",
                assistant_content="No.",
            )

    def test_workflow_context_round_trips_with_the_assistant_message(self) -> None:
        detail = self.service.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="I need vacation from 2030-04-10 to 2030-04-12",
            assistant_content="I prepared a request draft.",
            workflow_request={"id": "request-1", "type": "pto", "status": "draft"},
        )

        self.assertEqual(detail["messages"][1]["workflow"]["id"], "request-1")
        self.assertEqual(detail["messages"][1]["workflow_request_id"], "request-1")

    def test_metrics_count_all_questions_and_grounded_answers(self) -> None:
        self.service.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="When is payroll processed?",
            assistant_content="Twice per month.",
            sources=[],
            outcome_code="grounded",
        )

        self.assertEqual(
            self.service.metrics(),
            {"questions": 1, "grounded_answers": 1},
        )

    def test_history_is_imported_from_the_legacy_workflow_database_once(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy-workflow.db"
        legacy = ConversationService(legacy_path)
        original = legacy.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="When is payroll processed?",
            assistant_content="Twice per month.",
            sources=[{"title": "Payroll FAQ"}],
        )
        new_path = Path(self.temp_dir.name) / "conversations.db"

        migrated = ConversationService(new_path, legacy_db_path=legacy_path)
        self.assertEqual(migrated.metrics()["grounded_answers"], 1)
        reopened = ConversationService(new_path, legacy_db_path=legacy_path)

        conversation_id = original["conversation"]["id"]
        self.assertEqual(
            migrated.get_for_user(conversation_id, "employee.demo")["messages"],
            reopened.get_for_user(conversation_id, "employee.demo")["messages"],
        )
        self.assertEqual(len(reopened.list_for_user("employee.demo")), 1)
        self.assertEqual(reopened.metrics()["grounded_answers"], 1)


if __name__ == "__main__":
    unittest.main()
