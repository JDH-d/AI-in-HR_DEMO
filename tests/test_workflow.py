import shutil
import sqlite3
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from domain.workflow import (
    InvalidTransitionError,
    WorkflowInterpreter,
    WorkflowValidationError,
)
from services.workflow_service import WorkflowService


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

    def test_confirmation_validates_and_sends_draft_for_review(self) -> None:
        draft = self._draft()

        in_review = self.service.confirm_draft(
            draft["id"],
            "demo-user",
            {"comment": "Family vacation"},
        )

        self.assertEqual(in_review["status"], "submitted")
        self.assertEqual(in_review["duration_days"], 3)
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
            self.service.act(
                draft["id"], "Manager", "manager", "complete", submitted["revision"], comment="Done"
            )
        review = self.service.act(
            draft["id"], "Manager", "manager", "start_review", submitted["revision"]
        )
        approved = self.service.act(
            draft["id"],
            "Manager",
            "manager",
            "approve",
            review["revision"],
            comment="Coverage checked",
            basis="Leave policy",
            fair_review_confirmed=True,
        )
        with self.assertRaises(InvalidTransitionError):
            self.service.act(
                draft["id"], "Manager", "manager", "start_review", approved["revision"]
            )

    def test_applicant_can_cancel_and_event_is_recorded(self) -> None:
        draft = self._draft()

        cancelled = self.service.act(
            draft["id"],
            "demo-user",
            "employee",
            "cancel",
            draft["revision"],
            comment="Plans changed",
        )

        self.assertEqual(cancelled["status"], "cancelled")
        event = self.service.history(draft["id"])["events"][-1]
        self.assertEqual(event["from_status"], "draft")
        self.assertEqual(event["to_status"], "cancelled")
        self.assertEqual(event["details"]["comment"], "Plans changed")

    def test_manager_comment_and_feedback_create_events(self) -> None:
        draft = self._draft()
        submitted = self.service.confirm_draft(draft["id"], "demo-user", {})
        self.service.comment(
            draft["id"], "Manager", "manager", "Please add context.", submitted["revision"]
        )
        feedback = self.service.add_feedback(draft["id"], "demo-user", 5, "Clear flow")

        history = self.service.history(draft["id"])
        self.assertEqual(history["comments"][0]["body"], "Please add context.")
        self.assertEqual(feedback["rating"], 5)
        self.assertEqual(
            [event["event_type"] for event in history["events"]],
            ["draft_created", "status_changed", "comment_added", "feedback_added"],
        )

    def test_schema_contains_all_stage_two_entities(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            feedback_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(assistant_feedback)").fetchall()
            }

        self.assertTrue(
            {
                "users",
                "workflow_requests",
                "request_events",
                "request_comments",
                "feedback",
                "quality_reviews",
            }.issubset(tables)
        )
        self.assertIn("answer", feedback_columns)

    def test_quality_review_actions_are_persisted_and_replaceable(self) -> None:
        first = self.service.review_quality_item("gap-123", "ignored")
        second = self.service.review_quality_item("gap-123", "resolved")

        self.assertEqual(first["action"], "ignored")
        self.assertEqual(second["action"], "resolved")
        self.assertEqual(self.service.reviewed_quality_item_ids(), {"gap-123"})

        with self.assertRaises(WorkflowValidationError):
            self.service.review_quality_item("gap-456", "archive")

    def test_stage_one_database_is_migrated_without_losing_request(self) -> None:
        legacy_path = self.temp_dir / "legacy.db"
        with closing(sqlite3.connect(legacy_path)) as conn, conn:
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
        self.assertEqual(requests[0]["status"], "in_review")
        self.assertEqual(
            migrated.history("legacy-1")["events"][0]["event_type"],
            "legacy_request_migrated",
        )

    def test_old_submitted_and_completed_states_and_events_are_preserved(self):
        for status in ("submitted", "completed", "declined"):
            path = self.temp_dir / (status + ".db")
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute(
                    "CREATE TABLE workflow_requests (id TEXT PRIMARY KEY, type TEXT, start_date TEXT, end_date TEXT, duration_days INTEGER, comment TEXT, applicant TEXT, approver TEXT, status TEXT, created_at TEXT, updated_at TEXT)"
                )
                conn.execute(
                    "INSERT INTO workflow_requests VALUES ('old', 'document', NULL, NULL, NULL, 'Keep content', 'demo-user', 'Manager', ?, '2020', '2020')",
                    (status,),
                )
                conn.execute(
                    "CREATE TABLE request_events (id TEXT PRIMARY KEY, request_id TEXT, event_type TEXT, from_status TEXT, to_status TEXT, actor TEXT, details TEXT, created_at TEXT)"
                )
                conn.execute(
                    "INSERT INTO request_events VALUES ('original', 'old', 'status_changed', 'in_review', ?, 'Manager', ?, '2020')",
                    (status, '{"comment":"Original reason"}'),
                )
                conn.execute("PRAGMA user_version=2")
            service = WorkflowService(str(path))
            self.assertEqual(service.history("old")["events"][0]["to_status"], status)
            self.assertEqual(
                service.history("old")["events"][0]["details"]["comment"], "Original reason"
            )
            self.assertEqual(
                service.get_for_user("old", "demo-user")["status"],
                "rejected" if status == "declined" else status,
            )
            before = service.history("old")
            self.assertEqual(WorkflowService(str(path)).history("old"), before)

    def _draft(self) -> dict:
        result = self.service.prepare_draft(
            "I need vacation from 2030-04-01 to 2030-04-03",
            applicant="demo-user",
        )
        assert result is not None
        return result


if __name__ == "__main__":
    unittest.main()
