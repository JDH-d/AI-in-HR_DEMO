import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from workflow import WorkflowService


class WorkflowAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.service = WorkflowService(str(self.temp_dir / "workflow.db"))
        self.client = TestClient(app)
        self.public_patch = patch("api.public_routes.workflow_service", self.service)
        self.admin_patch = patch("api.admin_routes.workflow_service", self.service)
        self.public_patch.start()
        self.admin_patch.start()

    def tearDown(self) -> None:
        self.public_patch.stop()
        self.admin_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_confirm_cancel_and_history_endpoints(self) -> None:
        draft = self._draft()

        confirmed = self.client.post(
            f"/requests/{draft['id']}/confirm",
            headers={"X-User": "demo-user"},
            json={"comment": "Confirmed vacation"},
        )
        cancelled = self.client.post(
            f"/requests/{draft['id']}/cancel",
            headers={"X-User": "demo-user"},
            json={"comment": "Plans changed"},
        )
        history = self.client.get(
            f"/requests/{draft['id']}/history",
            headers={"X-User": "demo-user"},
        )

        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["request"]["status"], "submitted")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["request"]["status"], "cancelled")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(
            [event["to_status"] for event in history.json()["events"]],
            ["draft", "submitted", "cancelled"],
        )

    def test_other_user_cannot_confirm_draft(self) -> None:
        draft = self._draft()

        response = self.client.post(
            f"/requests/{draft['id']}/confirm",
            headers={"X-User": "other-user"},
            json={},
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_transition_and_comment_endpoints(self) -> None:
        draft = self._draft()
        self.service.confirm_draft(draft["id"], "demo-user", {})
        headers = {"Authorization": "Bearer demo-admin-token"}

        with patch("api.dependencies.ADMIN_TOKEN", "demo-admin-token"):
            review = self.client.put(
                f"/admin/requests/{draft['id']}/status",
                headers=headers,
                json={"status": "in_review", "comment": "Review started"},
            )
            invalid = self.client.put(
                f"/admin/requests/{draft['id']}/status",
                headers=headers,
                json={"status": "completed"},
            )
            comment = self.client.post(
                f"/admin/requests/{draft['id']}/comments",
                headers=headers,
                json={"author": "manager-1", "body": "Approved dates look correct."},
            )

        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["request"]["status"], "in_review")
        self.assertEqual(invalid.status_code, 409)
        self.assertEqual(comment.status_code, 200)

    def _draft(self) -> dict:
        draft = self.service.prepare_draft(
            "I need vacation from 2030-04-01 to 2030-04-03",
            "demo-user",
        )
        assert draft is not None
        return draft


if __name__ == "__main__":
    unittest.main()
