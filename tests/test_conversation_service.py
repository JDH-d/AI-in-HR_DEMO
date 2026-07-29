import shutil
import unittest
from pathlib import Path

from services.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
)


class ConversationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "workflow.db"
        self.service = ConversationService(str(self.db_path))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_exchange_survives_service_restart_with_evidence_and_workflow(self) -> None:
        conversation = self.service.create("employee.one")
        source = {
            "source": "Vacation_Policy.md",
            "title": "Vacation Policy",
            "section": "Partial days",
            "category": "leave",
            "version": "1.0",
            "excerpt": "Partial-day PTO is supported.",
            "score": 0.91,
        }
        workflow = {
            "id": "request-1",
            "type": "pto",
            "status": "draft",
        }

        self.service.append_exchange(
            conversation["id"],
            "employee.one",
            user_text="Can I request a half day?",
            assistant_text="Yes. Partial-day PTO is supported.",
            sources=[source],
            workflow_request=workflow,
        )
        restarted = ConversationService(str(self.db_path))
        restored = restarted.get_for_user(conversation["id"], "employee.one")

        self.assertEqual(restored["conversation"]["title"], "Can I request a half day?")
        self.assertEqual(
            [message["role"] for message in restored["messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(restored["messages"][1]["sources"], [source])
        self.assertEqual(restored["messages"][1]["workflow_request"], workflow)

    def test_empty_conversations_are_not_listed_and_title_comes_from_content(self) -> None:
        empty = self.service.create("employee.one")
        self.assertEqual(self.service.list_for_user("employee.one"), [])

        self.service.append_exchange(
            empty["id"],
            "employee.one",
            user_text="  How   does parental leave work?  ",
            assistant_text="Here is the policy.",
        )
        conversations = self.service.list_for_user("employee.one")

        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0]["title"], "How does parental leave work?")

    def test_users_cannot_read_or_write_each_others_conversations(self) -> None:
        conversation = self.service.create("employee.one")

        with self.assertRaises(ConversationNotFoundError):
            self.service.get_for_user(conversation["id"], "employee.two")
        with self.assertRaises(ConversationNotFoundError):
            self.service.append_exchange(
                conversation["id"],
                "employee.two",
                user_text="Show me another user's chat.",
                assistant_text="This must never be stored.",
            )

        restored = self.service.get_for_user(conversation["id"], "employee.one")
        self.assertEqual(restored["messages"], [])


if __name__ == "__main__":
    unittest.main()
