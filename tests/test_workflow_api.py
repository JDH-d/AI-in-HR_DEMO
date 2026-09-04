import shutil
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from tests.support import TEST_PASSWORD, build_test_services


class WorkflowV1APITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.services = build_test_services(self.temp_dir)
        self.service = self.services.workflow
        self.app = create_app(lambda: self.services)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.employee_headers = self._headers("employee")
        self.manager_headers = self._headers("manager")
        self.admin_headers = self._headers("knowledge_admin")

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
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
                "approver": "forged.manager",
            },
        )
        self.assertEqual(created.status_code, 201)
        draft = created.json()["request"]
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["applicant"], "employee.demo")
        self.assertEqual(draft["approver"], "manager.demo")

        sent_for_review = self.client.post(
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

        self.assertEqual(sent_for_review.status_code, 200)
        self.assertEqual(sent_for_review.json()["request"]["status"], "in_review")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            [event["to_status"] for event in detail.json()["events"]],
            ["draft", "in_review"],
        )
        self.assertEqual(feedback.status_code, 201)

    def test_manager_can_approve_request_in_review(self) -> None:
        request = self._review_request()

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
            ["draft", "in_review", "approved"],
        )

    def test_draft_is_private_until_the_employee_submits_it(self) -> None:
        created = self.client.post(
            "/api/v1/requests",
            headers=self.employee_headers,
            json={
                "type": "pto",
                "start_date": "2030-04-01",
                "end_date": "2030-04-03",
                "comment": "Private planning draft",
            },
        )
        request_id = created.json()["request"]["id"]

        manager_list = self.client.get("/api/v1/requests", headers=self.manager_headers)
        manager_detail = self.client.get(
            f"/api/v1/requests/{request_id}",
            headers=self.manager_headers,
        )
        manager_action = self.client.post(
            f"/api/v1/requests/{request_id}/approve",
            headers=self.manager_headers,
            json={},
        )
        employee_list = self.client.get("/api/v1/requests", headers=self.employee_headers)

        self.assertEqual(manager_list.json()["requests"], [])
        self.assertEqual(manager_detail.status_code, 404)
        self.assertEqual(manager_action.status_code, 404)
        self.assertEqual(
            [request["id"] for request in employee_list.json()["requests"]],
            [request_id],
        )

        submitted = self.client.post(
            f"/api/v1/requests/{request_id}/submit",
            headers=self.employee_headers,
            json={},
        )
        visible = self.client.get("/api/v1/requests", headers=self.manager_headers)

        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(
            [request["id"] for request in visible.json()["requests"]],
            [request_id],
        )

    def test_unshared_cancelled_draft_stays_private_from_manager(self) -> None:
        created = self.client.post(
            "/api/v1/requests",
            headers=self.employee_headers,
            json={
                "type": "pto",
                "start_date": "2030-04-01",
                "end_date": "2030-04-03",
                "comment": "Private planning draft",
            },
        )
        request_id = created.json()["request"]["id"]
        cancelled = self.client.post(
            f"/api/v1/requests/{request_id}/cancel",
            headers=self.employee_headers,
            json={"comment": "No longer needed"},
        )

        manager_list = self.client.get("/api/v1/requests", headers=self.manager_headers)
        manager_detail = self.client.get(
            f"/api/v1/requests/{request_id}",
            headers=self.manager_headers,
        )

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(manager_list.json()["requests"], [])
        self.assertEqual(manager_detail.status_code, 404)

    def test_sick_leave_is_reported_and_acknowledged_instead_of_approved(self) -> None:
        created = self.client.post(
            "/api/v1/requests",
            headers=self.employee_headers,
            json={
                "type": "sick_leave",
                "start_date": "2030-04-01",
                "comment": "",
                "details": {
                    "expected_return_date": "2030-04-02",
                    "expected_return_unknown": False,
                    "time_away": "full_day",
                    "partial_hours": None,
                    "extended_or_recurring": True,
                },
            },
        )
        self.assertEqual(created.status_code, 201)
        draft = created.json()["request"]

        reported = self.client.post(
            f"/api/v1/requests/{draft['id']}/submit",
            headers=self.employee_headers,
            json={},
        )
        forbidden_employee = self.client.post(
            f"/api/v1/requests/{draft['id']}/acknowledge",
            headers=self.employee_headers,
            json={},
        )
        cannot_approve = self.client.post(
            f"/api/v1/requests/{draft['id']}/approve",
            headers=self.manager_headers,
            json={},
        )
        acknowledged = self.client.post(
            f"/api/v1/requests/{draft['id']}/acknowledge",
            headers=self.manager_headers,
            json={"comment": "Take care — I will cover the stand-up."},
        )
        detail = self.client.get(
            f"/api/v1/requests/{draft['id']}",
            headers=self.employee_headers,
        ).json()

        self.assertEqual(reported.status_code, 200)
        self.assertEqual(reported.json()["request"]["status"], "reported")
        self.assertEqual(reported.json()["request"]["duration_days"], 1)
        self.assertTrue(reported.json()["request"]["details"]["extended_or_recurring"])
        self.assertEqual(forbidden_employee.status_code, 403)
        self.assertEqual(cannot_approve.status_code, 409)
        self.assertEqual(acknowledged.status_code, 200)
        self.assertEqual(acknowledged.json()["request"]["status"], "acknowledged")
        self.assertEqual(
            [event["to_status"] for event in detail["events"]],
            ["draft", "reported", "acknowledged"],
        )

    def test_manager_can_decline_and_employee_cannot_decide(self) -> None:
        request = self._review_request()

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
        manager_detail = self.client.get(
            f"/api/v1/requests/{request['id']}",
            headers=self.manager_headers,
        ).json()
        employee_detail = self.client.get(
            f"/api/v1/requests/{request['id']}",
            headers=self.employee_headers,
        ).json()
        self.assertEqual(
            manager_detail["events"][-1]["details"]["comment"],
            "Coverage unavailable",
        )
        self.assertEqual(
            employee_detail["events"][-1]["details"]["comment"],
            "Coverage unavailable",
        )

    def test_decline_requires_manager_comment(self) -> None:
        request = self._review_request()
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
            json={
                "type": "pto",
                "start_date": "2030-04-01",
                "end_date": "2030-04-01",
                "comment": "Time off",
            },
        )
        self.assertEqual(create.status_code, 403)

    def test_document_request_type_is_not_supported(self) -> None:
        response = self.client.post(
            "/api/v1/requests",
            headers=self.employee_headers,
            json={"type": "document", "comment": "Employment letter"},
        )

        self.assertEqual(response.status_code, 422)

    def test_employee_can_cancel_own_request(self) -> None:
        request = self._review_request()

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
            json={
                "rating": 5,
                "question": "How often are salaries paid?",
                "answer": "Salaries are paid twice per month.",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["feedback"]["rating"], 5)

    def test_admin_feedback_view_is_anonymous_and_contains_question_and_answer(self) -> None:
        self.client.post(
            "/api/v1/feedback",
            headers=self.employee_headers,
            json={
                "rating": 1,
                "question": "Can I work remotely?",
                "answer": "Remote work is never available.",
                "comment": "This contradicts the policy.",
            },
        )

        response = self.client.get(
            "/api/v1/admin/feedback?sentiment=negative",
            headers=self.admin_headers,
        )
        forbidden = self.client.get(
            "/api/v1/admin/feedback",
            headers=self.employee_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(forbidden.status_code, 403)
        item = response.json()["feedback"][0]
        self.assertEqual(item["question"], "Can I work remotely?")
        self.assertEqual(item["answer"], "Remote work is never available.")
        self.assertEqual(item["comment"], "This contradicts the policy.")
        self.assertEqual(item["sentiment"], "negative")
        self.assertNotIn("user_id", item)

    def _review_request(self) -> dict:
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
            json={"username": username, "password": TEST_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


if __name__ == "__main__":
    unittest.main()
