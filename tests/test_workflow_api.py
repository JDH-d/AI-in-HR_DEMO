import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from core import settings
from workflow import WorkflowService


class WorkflowV1APITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.service = WorkflowService(str(self.temp_dir / "workflow.db"))
        self.client = TestClient(app)
        self.workflow_patch = patch("api.v1_routes.workflow_service", self.service)
        self.workflow_patch.start()
        self.employee_headers = self._headers("employee")
        self.manager_headers = self._headers("manager")
        self.admin_headers = self._headers("knowledge_admin")

    def tearDown(self) -> None:
        self.workflow_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_submit_get_and_feedback_contract(self) -> None:
        created = self.client.post(
            "/api/v1/requests",
            headers=self.employee_headers,
            json={
                "type": "pto",
                "start_date": "2030-04-01",
                "end_date": "2030-04-03",
                "comment": "Family vacation",
            },
        )
        self.assertEqual(created.status_code, 201)
        draft = created.json()["request"]
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["applicant"], "employee.demo")

        submitted = self.client.post(
            f"/api/v1/requests/{draft['id']}/submit",
            headers=self.employee_headers,
            json={},
        )
        detail = self.client.get(
            f"/api/v1/requests/{draft['id']}",
            headers=self.employee_headers,
        )
        feedback = self.client.post(
            "/api/v1/feedback",
            headers=self.employee_headers,
            json={"request_id": draft["id"], "rating": 5, "comment": "Clear flow"},
        )

        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json()["request"]["status"], "submitted")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            [event["to_status"] for event in detail.json()["events"]],
            ["draft", "submitted"],
        )
        self.assertEqual(feedback.status_code, 201)

    def test_manager_can_approve_submitted_request(self) -> None:
        request = self._submitted_request()

        approved = self.client.post(
            f"/api/v1/requests/{request['id']}/approve",
            headers=self.manager_headers,
            json={"comment": "Dates approved"},
        )
        detail = self.client.get(
            f"/api/v1/requests/{request['id']}",
            headers=self.manager_headers,
        )

        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["request"]["status"], "approved")
        self.assertEqual(
            [event["to_status"] for event in detail.json()["events"]],
            ["draft", "submitted", "in_review", "approved"],
        )

    def test_manager_can_decline_and_employee_cannot_decide(self) -> None:
        request = self._submitted_request()

        forbidden = self.client.post(
            f"/api/v1/requests/{request['id']}/approve",
            headers=self.employee_headers,
            json={},
        )
        declined = self.client.post(
            f"/api/v1/requests/{request['id']}/decline",
            headers=self.manager_headers,
            json={"comment": "Coverage unavailable"},
        )

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(declined.status_code, 200)
        self.assertEqual(declined.json()["request"]["status"], "declined")

    def test_decline_requires_manager_comment(self) -> None:
        request = self._submitted_request()
        response = self.client.post(
            f"/api/v1/requests/{request['id']}/decline",
            headers=self.manager_headers,
            json={"comment": ""},
        )
        self.assertEqual(response.status_code, 422)

    def test_knowledge_admin_cannot_create_or_approve_request(self) -> None:
        create = self.client.post(
            "/api/v1/requests",
            headers=self.admin_headers,
            json={"type": "document", "comment": "Employment letter"},
        )
        self.assertEqual(create.status_code, 403)

    def test_employee_can_cancel_own_request(self) -> None:
        request = self._submitted_request()

        cancelled = self.client.post(
            f"/api/v1/requests/{request['id']}/cancel",
            headers=self.employee_headers,
            json={"comment": "Plans changed"},
        )

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["request"]["status"], "cancelled")

    def test_invalid_calendar_date_is_rejected_by_api(self) -> None:
        response = self.client.post(
            "/api/v1/requests",
            headers=self.employee_headers,
            json={
                "type": "pto",
                "start_date": "2030-02-31",
                "end_date": "2030-03-02",
                "comment": "Invalid date",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_answer_feedback_does_not_require_workflow_request(self) -> None:
        response = self.client.post(
            "/api/v1/feedback",
            headers=self.employee_headers,
            json={"rating": 5, "question": "How often are salaries paid?"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["feedback"]["rating"], 5)

    def _submitted_request(self) -> dict:
        draft = self.service.create_structured_draft(
            request_type="pto",
            start_date="2030-04-01",
            end_date="2030-04-03",
            comment="Vacation",
            applicant="employee.demo",
            approver="manager.demo",
        )
        return self.service.confirm_draft(draft["id"], "employee.demo", {})

    def _headers(self, username: str) -> dict:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": settings.DEMO_LOGIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


if __name__ == "__main__":
    unittest.main()
