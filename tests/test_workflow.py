import shutil
import sqlite3
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from workflow import (
    InvalidTransitionError,
    WorkflowInterpreter,
    WorkflowService,
    WorkflowValidationError,
)
from workflow_schema import SCHEMA_VERSION


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
        self.assertEqual(result["approver"], "manager.demo")
        self.assertEqual(result["validation_errors"], [])

    def test_confirmation_validates_and_sends_draft_for_review(self) -> None:
        draft = self._draft()

        in_review = self.service.confirm_draft(
            draft["id"],
            "demo-user",
            {"comment": "Family vacation", "approver": "forged.manager"},
        )

        self.assertEqual(in_review["status"], "in_review")
        self.assertEqual(in_review["duration_days"], 3)
        self.assertEqual(in_review["approver"], "manager.demo")
        history = self.service.history(draft["id"])
        self.assertEqual(
            [event["to_status"] for event in history["events"]],
            ["draft", "in_review"],
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
        self.assertEqual(draft["comment"], "")
        self.assertEqual(draft["details"]["expected_return_date"], "2030-04-03")

    def test_slash_dates_use_us_month_day_order(self) -> None:
        draft = self.service.prepare_draft(
            "I need vacation from 04/10/2030 to 04/12/2030",
            applicant="demo-user",
        )

        assert draft is not None
        self.assertEqual(draft["start_date"], "2030-04-10")
        self.assertEqual(draft["end_date"], "2030-04-12")

    def test_sick_leave_is_reported_without_a_medical_note_or_approval(self) -> None:
        draft = self.service.create_structured_draft(
            request_type="sick_leave",
            start_date="2030-04-01",
            end_date=None,
            comment="",
            applicant="demo-user",
            approver="manager.demo",
            details={
                "expected_return_date": "2030-04-02",
                "expected_return_unknown": False,
                "time_away": "full_day",
                "partial_hours": None,
                "extended_or_recurring": False,
            },
        )

        reported = self.service.confirm_draft(draft["id"], "demo-user", {})
        acknowledged = self.service.manager_decision(
            reported["id"],
            "manager.demo",
            "acknowledged",
        )

        self.assertEqual(reported["status"], "reported")
        self.assertEqual(reported["end_date"], "2030-04-01")
        self.assertEqual(reported["duration_days"], 1)
        self.assertEqual(reported["comment"], "")
        self.assertEqual(acknowledged["status"], "acknowledged")
        self.assertEqual(
            [event["to_status"] for event in self.service.history(draft["id"])["events"]],
            ["draft", "reported", "acknowledged"],
        )

    def test_sick_leave_can_report_an_unknown_return_date(self) -> None:
        draft = self.service.create_structured_draft(
            request_type="sick_leave",
            start_date="2030-04-01",
            end_date="2030-04-05",
            comment="I will update the team when I know more.",
            applicant="demo-user",
            approver="manager.demo",
            details={
                "expected_return_date": None,
                "expected_return_unknown": True,
                "time_away": "full_day",
                "partial_hours": None,
                "extended_or_recurring": True,
            },
        )

        reported = self.service.confirm_draft(draft["id"], "demo-user", {})

        self.assertIsNone(reported["end_date"])
        self.assertIsNone(reported["duration_days"])
        self.assertTrue(reported["details"]["expected_return_unknown"])
        self.assertTrue(reported["details"]["extended_or_recurring"])

    def test_partial_sick_leave_requires_valid_hours(self) -> None:
        with self.assertRaises(WorkflowValidationError):
            self.service.create_structured_draft(
                request_type="sick_leave",
                start_date="2030-04-01",
                end_date=None,
                comment="",
                applicant="demo-user",
                approver="manager.demo",
                details={
                    "expected_return_date": "2030-04-01",
                    "expected_return_unknown": False,
                    "time_away": "partial_day",
                    "partial_hours": 0,
                    "extended_or_recurring": False,
                },
            )

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

    def test_document_language_does_not_create_a_workflow(self) -> None:
        self.assertIsNone(self.service.prepare_draft("I need an employment letter", "demo-user"))
        with self.assertRaises(WorkflowValidationError):
            self.service.create_structured_draft(
                request_type="document",
                start_date=None,
                end_date=None,
                comment="Employment letter",
                applicant="demo-user",
                approver="manager.demo",
            )

    def test_removed_request_type_is_hidden_from_manager_detail_and_list(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO workflow_requests
                (id, type, start_date, end_date, duration_days, comment, applicant, approver,
                 details, status, created_at, updated_at)
                VALUES ('old-document-request', 'document_request', NULL, NULL, NULL,
                        'Legacy letter', 'demo-user', 'manager.demo', '{}', 'in_review',
                        '2030-04-01T09:00:00+00:00', '2030-04-01T09:00:00+00:00')
                """
            )
            conn.commit()

        self.assertIsNone(self.service.get_for_manager("old-document-request", "manager.demo"))
        self.assertEqual(self.service.list_for_manager("manager.demo"), [])

    def test_state_machine_blocks_invalid_transition(self) -> None:
        draft = self._draft()
        in_review = self.service.confirm_draft(draft["id"], "demo-user", {})

        with self.assertRaises(WorkflowValidationError):
            self.service.store.transition(in_review["id"], "completed", "manager.demo")

        approved = self.service.manager_decision(
            in_review["id"],
            "manager.demo",
            "approved",
        )
        with self.assertRaises(InvalidTransitionError):
            self.service.manager_decision(
                approved["id"],
                "manager.demo",
                "approved",
            )

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
        self.service.confirm_draft(draft["id"], "demo-user", {})
        self.service.add_manager_comment(
            draft["id"],
            "manager.demo",
            "Please add context.",
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
        with sqlite3.connect(self.db_path) as conn:
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
                "workflow_requests",
                "request_events",
                "request_comments",
                "feedback",
                "quality_reviews",
            }.issubset(tables)
        )
        self.assertNotIn("users", tables)
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
        self.assertEqual(requests[0]["status"], "in_review")
        self.assertEqual(
            migrated.history("legacy-1")["events"][0]["event_type"],
            "legacy_request_migrated",
        )
        with sqlite3.connect(legacy_path) as conn:
            legacy_tables = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name LIKE 'workflow_requests_legacy_%'
                """
            ).fetchall()
            request_index = conn.execute(
                """
                SELECT tbl_name FROM sqlite_master
                WHERE type = 'index' AND name = 'idx_requests_applicant'
                """
            ).fetchone()

        self.assertEqual(legacy_tables, [])
        self.assertEqual(request_index, ("workflow_requests",))

    def test_legacy_migration_preserves_related_rows_and_foreign_keys(self) -> None:
        legacy_path = self.temp_dir / "legacy-with-history.db"
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE workflow_requests (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    period_or_date TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_to TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE request_events (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    actor TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (request_id) REFERENCES workflow_requests(id) ON DELETE CASCADE
                );
                CREATE TABLE request_comments (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (request_id) REFERENCES workflow_requests(id) ON DELETE CASCADE
                );
                CREATE TABLE feedback (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    comment TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (request_id) REFERENCES workflow_requests(id) ON DELETE CASCADE
                );
                INSERT INTO workflow_requests VALUES
                    ('legacy-1', 'PTO', 'demo-user', 'tomorrow', 'Legacy request',
                     'pending', 'Manager', '2026-01-01T00:00:00+00:00');
                INSERT INTO request_events VALUES
                    ('event-1', 'legacy-1', 'comment_added', 'pending', 'pending',
                     'manager.demo', '{}', '2026-01-01T01:00:00+00:00');
                INSERT INTO request_comments VALUES
                    ('comment-1', 'legacy-1', 'manager.demo', 'Existing note',
                     '2026-01-01T01:00:00+00:00');
                INSERT INTO feedback VALUES
                    ('feedback-1', 'legacy-1', 'demo-user', 5, 'Useful',
                     '2026-01-01T02:00:00+00:00');
                """
            )

        migrated = WorkflowService(str(legacy_path))
        history = migrated.history("legacy-1")

        self.assertEqual(len(history["events"]), 2)
        self.assertIn("event-1", {event["id"] for event in history["events"]})
        self.assertIn(
            "legacy_request_migrated",
            {event["event_type"] for event in history["events"]},
        )
        self.assertEqual(history["comments"][0]["body"], "Existing note")
        self.assertEqual(migrated.metrics()["feedback"], 1)
        with sqlite3.connect(legacy_path) as conn:
            event_parent = conn.execute("PRAGMA foreign_key_list(request_events)").fetchone()[2]
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()

        self.assertEqual(event_parent, "workflow_requests")
        self.assertEqual(violations, [])

    def test_failed_legacy_migration_rolls_back_the_schema_rename(self) -> None:
        legacy_path = self.temp_dir / "failed-legacy.db"
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

        with patch(
            "workflow_schema._migrate_legacy_rows",
            side_effect=RuntimeError("migration interrupted"),
        ):
            with self.assertRaisesRegex(RuntimeError, "migration interrupted"):
                WorkflowService(str(legacy_path))

        with sqlite3.connect(legacy_path) as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(workflow_requests)").fetchall()
            }
            legacy_tables = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name LIKE 'workflow_requests_legacy_%'
                """
            ).fetchall()
            request_ids = conn.execute("SELECT id FROM workflow_requests").fetchall()

        self.assertIn("period_or_date", columns)
        self.assertNotIn("start_date", columns)
        self.assertEqual(legacy_tables, [])
        self.assertEqual(request_ids, [("legacy-1",)])

    def test_newer_database_schema_is_not_silently_downgraded(self) -> None:
        future_version = SCHEMA_VERSION + 1
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"PRAGMA user_version = {future_version}")
            conn.commit()

        with self.assertRaisesRegex(RuntimeError, "newer than supported"):
            WorkflowService(str(self.db_path))

        with sqlite3.connect(self.db_path) as conn:
            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(current_version, future_version)

    def test_submitted_status_from_v2_is_migrated_to_in_review(self) -> None:
        draft = self._draft()
        request = self.service.confirm_draft(draft["id"], "demo-user", {})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE workflow_requests SET status = 'submitted' WHERE id = ?",
                (request["id"],),
            )
            conn.execute(
                "UPDATE request_events SET to_status = 'submitted' WHERE to_status = 'in_review'"
            )
            conn.execute("PRAGMA user_version = 2")
            conn.commit()

        migrated = WorkflowService(str(self.db_path))
        current = migrated.get_for_user(request["id"], "demo-user")
        history = migrated.history(request["id"])

        assert current is not None
        self.assertEqual(current["status"], "in_review")
        self.assertEqual(
            [event["to_status"] for event in history["events"]],
            ["draft", "in_review"],
        )

    def test_in_review_sick_leave_from_v6_is_migrated_to_reported(self) -> None:
        draft = self.service.create_structured_draft(
            request_type="sick_leave",
            start_date="2030-04-01",
            end_date=None,
            comment="",
            applicant="demo-user",
            approver="manager.demo",
            details={
                "expected_return_date": "2030-04-02",
                "expected_return_unknown": False,
                "time_away": "full_day",
            },
        )
        request = self.service.confirm_draft(draft["id"], "demo-user", {})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE workflow_requests SET status = 'in_review' WHERE id = ?",
                (request["id"],),
            )
            conn.execute(
                "UPDATE request_events SET to_status = 'in_review' WHERE to_status = 'reported'"
            )
            conn.execute("PRAGMA user_version = 6")
            conn.commit()

        migrated = WorkflowService(str(self.db_path))
        current = migrated.get_for_user(request["id"], "demo-user")
        history = migrated.history(request["id"])

        assert current is not None
        self.assertEqual(current["status"], "reported")
        self.assertEqual(
            [event["to_status"] for event in history["events"]],
            ["draft", "reported"],
        )

    def test_completed_status_from_v3_is_migrated_to_approved(self) -> None:
        draft = self._draft()
        request = self.service.confirm_draft(draft["id"], "demo-user", {})
        self.service.manager_decision(request["id"], "manager.demo", "approved")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE workflow_requests SET status = 'completed' WHERE id = ?",
                (request["id"],),
            )
            conn.execute(
                """
                INSERT INTO request_events
                (id, request_id, event_type, from_status, to_status, actor, details, created_at)
                VALUES ('completed-event', ?, 'status_changed', 'approved', 'completed',
                        'manager.demo', '{}', '2030-04-01T12:00:00+00:00')
                """,
                (request["id"],),
            )
            conn.execute("PRAGMA user_version = 3")
            conn.commit()

        migrated = WorkflowService(str(self.db_path))
        current = migrated.get_for_user(request["id"], "demo-user")
        history = migrated.history(request["id"])

        assert current is not None
        self.assertEqual(current["status"], "approved")
        self.assertEqual(
            [event["to_status"] for event in history["events"]],
            ["draft", "in_review", "approved"],
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
