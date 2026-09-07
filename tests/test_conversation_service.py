from __future__ import annotations

import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from services.conversation_service import ConversationNotFoundError, ConversationService


class ConversationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = ConversationService(Path(self.temp_dir.name) / "peopleflow.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_backend_id_is_stable_across_restart_and_empty_history(self) -> None:
        backend_id = self.service.backend_id
        self.assertEqual(str(uuid.UUID(backend_id)), backend_id)
        self.assertEqual(uuid.UUID(backend_id).version, 4)
        reopened = ConversationService(self.service.db_path)
        self.assertEqual(reopened.backend_id, backend_id)
        self.assertEqual(reopened.list_for_user("employee.demo"), [])
        detail = reopened.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="A temporary conversation",
            assistant_content="A temporary answer",
        )
        reopened.delete_for_user(detail["conversation"]["id"], "employee.demo")
        self.assertEqual(ConversationService(self.service.db_path).backend_id, backend_id)

    def test_new_database_has_its_own_backend_id(self) -> None:
        other = ConversationService(Path(self.temp_dir.name) / "other.db")
        self.assertNotEqual(self.service.backend_id, other.backend_id)

    def test_backend_metadata_upgrade_preserves_existing_history(self) -> None:
        detail = self.service.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="Existing history",
            assistant_content="Existing answer",
            sources=[{"title": "Policy"}],
        )
        # Simulate a pre-identity database using only this test's temporary data.
        with closing(sqlite3.connect(self.service.db_path)) as conn:
            conn.execute("DROP TABLE conversation_metadata")
            conn.commit()
        upgraded = ConversationService(self.service.db_path)
        self.assertEqual(
            upgraded.get_for_user(detail["conversation"]["id"], "employee.demo"), detail
        )
        self.assertEqual(ConversationService(self.service.db_path).backend_id, upgraded.backend_id)

    def test_concurrent_initializers_share_one_persisted_backend_id(self) -> None:
        path = Path(self.temp_dir.name) / "concurrent.db"
        with ThreadPoolExecutor(max_workers=4) as workers:
            identities = list(workers.map(lambda _: ConversationService(path).backend_id, range(4)))
        self.assertEqual(len(set(identities)), 1)
        self.assertEqual(ConversationService(path).backend_id, identities[0])

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

    def test_delete_removes_messages_and_updates_history_metrics(self) -> None:
        detail = self.service.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="When is payroll processed?",
            assistant_content="Twice per month.",
            outcome_code="grounded",
        )
        retained = self.service.record_exchange(
            "another.employee",
            conversation_id=None,
            user_content="What can you help with?",
            assistant_content="Company policy questions and requests.",
        )
        conversation_id = detail["conversation"]["id"]

        self.assertTrue(self.service.delete_for_user(conversation_id, "employee.demo"))

        self.assertIsNone(self.service.get_for_user(conversation_id, "employee.demo"))
        self.assertEqual(self.service.list_for_user("employee.demo"), [])
        self.assertEqual(
            self.service.get_for_user(retained["conversation"]["id"], "another.employee"),
            retained,
        )
        self.assertEqual(self.service.metrics(), {"questions": 1, "grounded_answers": 0})
        with closing(sqlite3.connect(self.service.db_path)) as conn:
            message_count = conn.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
        self.assertEqual(message_count, 0)

    def test_delete_does_not_expose_or_remove_other_users_history(self) -> None:
        detail = self.service.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="When is payroll processed?",
            assistant_content="Twice per month.",
        )
        conversation_id = detail["conversation"]["id"]

        self.assertFalse(self.service.delete_for_user(conversation_id, "another.employee"))
        self.assertFalse(self.service.delete_for_user("missing-conversation", "employee.demo"))
        self.assertEqual(self.service.get_for_user(conversation_id, "employee.demo"), detail)

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

        self.assertTrue(reopened.delete_for_user(conversation_id, "employee.demo"))
        after_delete = ConversationService(new_path, legacy_db_path=legacy_path)
        self.assertEqual(after_delete.list_for_user("employee.demo"), [])
        self.assertEqual(after_delete.metrics(), {"questions": 0, "grounded_answers": 0})

    def test_existing_history_is_not_reimported_after_its_last_chat_is_deleted(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy-workflow.db"
        legacy = ConversationService(legacy_path)
        legacy.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="Old history",
            assistant_content="Old answer.",
        )
        current = self.service.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="Current history",
            assistant_content="Current answer.",
        )
        upgraded = ConversationService(self.service.db_path, legacy_db_path=legacy_path)

        self.assertTrue(upgraded.delete_for_user(current["conversation"]["id"], "employee.demo"))
        reopened = ConversationService(self.service.db_path, legacy_db_path=legacy_path)

        self.assertEqual(reopened.list_for_user("employee.demo"), [])


if __name__ == "__main__":
    unittest.main()
