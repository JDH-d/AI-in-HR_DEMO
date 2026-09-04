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
        conversation = self.service.create("employee.demo")

        detail = self.service.append_exchange(
            conversation["id"],
            "employee.demo",
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
        self.assertEqual(self.service.list_for_user("employee.demo")[0]["id"], conversation["id"])

    def test_empty_conversations_do_not_clutter_recent_history(self) -> None:
        self.service.create("employee.demo")

        self.assertEqual(self.service.list_for_user("employee.demo"), [])

    def test_history_is_scoped_to_its_owner(self) -> None:
        conversation = self.service.create("employee.demo")
        self.service.append_exchange(
            conversation["id"],
            "employee.demo",
            user_content="When is payroll processed?",
            assistant_content="Twice per month.",
        )

        self.assertIsNone(self.service.get_for_user(conversation["id"], "another.employee"))
        self.assertEqual(self.service.list_for_user("another.employee"), [])
        with self.assertRaises(ConversationNotFoundError):
            self.service.append_exchange(
                conversation["id"],
                "another.employee",
                user_content="Show me that conversation",
                assistant_content="No.",
            )

    def test_workflow_context_round_trips_with_the_assistant_message(self) -> None:
        conversation = self.service.create("employee.demo")

        detail = self.service.append_exchange(
            conversation["id"],
            "employee.demo",
            user_content="I need vacation from 2030-04-10 to 2030-04-12",
            assistant_content="I prepared a request draft.",
            workflow_request={"id": "request-1", "type": "pto", "status": "draft"},
        )

        self.assertEqual(detail["messages"][1]["workflow"]["id"], "request-1")


if __name__ == "__main__":
    unittest.main()
