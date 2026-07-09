import shutil
import sqlite3
import unittest
from datetime import date
from pathlib import Path

from workflow import (
    InvalidTransitionError,
    WorkflowInterpreter,
    WorkflowService,
    WorkflowValidationError,
)


class WorkflowServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "workflow.db"
        self.service = WorkflowService(
            str(self.db_path),
            interpreter=WorkflowInterpreter(today_provider=lambda: date(2030, 4, 1)),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_explicit_action_creates_draft_but_does_not_submit(self) -> None:
        result = self.service.prepare_draft(
            "I need vacation from 2030-04-01 to 2030-04-03",
            applicant="demo-user",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["type"], "pto")
        self.assertEqual(result["start_date"], "2030-04-01")
        self.assertEqual(result["end_date"], "2030-04-03")
        self.assertEqual(result["duration_days"], 3)
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["applicant"], "demo-user")
        self.assertEqual(result["approver"], "Manager")
        self.assertEqual(result["validation_errors"], [])

    def test_confirmation_validates_and_submits_draft(self) -> None:
        draft = self._draft()

        submitted = self.service.confirm_draft(
            draft["id"],
            "demo-user",
            {"comment": "Family vacation"},
        )

        self.assertEqual(submitted["status"], "submitted")
        self.assertEqual(submitted["duration_days"], 3)
        history = self.service.history(draft["id"])
        self.assertEqual(
            [event["to_status"] for event in history["events"]],
            ["draft", "submitted"],
        )

    def test_invalid_calendar_date_cannot_be_confirmed(self) -> None:
        draft = self.service.prepare_draft(
            "I need vacation from 2030-02-31 to 2030-03-02",
            applicant="demo-user",
        )

        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertEqual(draft["status"], "draft")
        self.assertTrue(any("Invalid calendar date" in item for item in draft["validation_errors"]))
        with self.assertRaises(WorkflowValidationError):
            self.service.confirm_draft(draft["id"], "demo-user", {})

    def test_end_date_cannot_be_before_start_date(self) -> None:
        draft = self._draft()

        with self.assertRaises(WorkflowValidationError):
            self.service.confirm_draft(
                draft["id"],
                "demo-user",
                {"start_date": "2030-04-10", "end_date": "2030-04-01"},
            )

    def test_relative_date_is_resolved_to_real_iso_date(self) -> None:
        draft = self.service.prepare_draft(
            "I want sick leave tomorrow",
            applicant="demo-user",
        )

        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertEqual(draft["type"], "sick_leave")
        self.assertEqual(draft["start_date"], "2030-04-02")
        self.assertEqual(draft["end_date"], "2030-04-02")

    def test_policy_questions_never_create_requests(self) -> None:
        questions = [
            "Tell me about the vacation policy",
            "How do I request vacation?",
            "Can I request PTO next month?",
            "I need to know the sick leave policy",
            "I want information about annual leave",
            "What is the process for requesting time off?",
        ]

        for question in questions:
            with self.subTest(question=question):
                self.assertIsNone(self.service.prepare_draft(question, "demo-user"))
        self.assertEqual(self.service.list_for_user("demo-user"), [])

    def test_state_machine_blocks_invalid_transition(self) -> None:
        draft = self._draft()
        submitted = self.service.confirm_draft(draft["id"], "demo-user", {})

        with self.assertRaises(InvalidTransitionError):
            self.service.transition(submitted["id"], "approved")

        in_review = self.service.transition(submitted["id"], "in_review")
        approved = self.service.transition(in_review["id"], "approved")
        completed = self.service.transition(approved["id"], "completed")
        self.assertEqual(completed["status"], "completed")
        with self.assertRaises(InvalidTransitionError):
            self.service.transition(completed["id"], "in_review")

    def test_applicant_can_cancel_and_event_is_recorded(self) -> None:
        draft = self._draft()

        cancelled = self.service.cancel(draft["id"], "demo-user", "Plans changed")

        self.assertEqual(cancelled["status"], "cancelled")
        event = self.service.history(draft["id"])["events"][-1]
        self.assertEqual(event["from_status"], "draft")
        self.assertEqual(event["to_status"], "cancelled")
        self.assertEqual(event["details"]["comment"], "Plans changed")

    def test_manager_comment_and_feedback_create_events(self) -> None:
        draft = self._draft()
        self.service.add_manager_comment(draft["id"], "manager-1", "Please add context.")
        feedback = self.service.add_feedback(draft["id"], "demo-user", 5, "Clear flow")

        history = self.service.history(draft["id"])
        self.assertEqual(history["comments"][0]["body"], "Please add context.")
        self.assertEqual(feedback["rating"], 5)
        self.assertEqual(
            [event["event_type"] for event in history["events"]],
            ["draft_created", "comment_added", "feedback_added"],
        )

    def test_schema_contains_all_stage_two_entities(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        self.assertTrue(
            {
                "users",
                "workflow_requests",
                "request_events",
                "request_comments",
                "feedback",
            }.issubset(tables)
        )

    def test_stage_one_database_is_migrated_without_losing_request(self) -> None:
        legacy_path = self.temp_dir / "legacy.db"
        with sqlite3.connect(legacy_path) as conn:
            conn.execute(
                """
                CREATE TABLE workflow_requests (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    period_or_date TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_to TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO workflow_requests
                VALUES ('legacy-1', 'PTO', 'demo-user', 'tomorrow', 'Legacy request',
                        'pending', 'Manager', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.commit()

        migrated = WorkflowService(str(legacy_path))
        requests = migrated.list_for_user("demo-user")

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["id"], "legacy-1")
        self.assertEqual(requests[0]["type"], "pto")
        self.assertEqual(requests[0]["status"], "submitted")
        self.assertEqual(
            migrated.history("legacy-1")["events"][0]["event_type"],
            "legacy_request_migrated",
        )

    def _draft(self) -> dict:
        result = self.service.prepare_draft(
            "I need vacation from 2030-04-01 to 2030-04-03",
            applicant="demo-user",
        )
        assert result is not None
        return result


if __name__ == "__main__":
    unittest.main()
