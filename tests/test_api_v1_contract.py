import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from core import settings
from services.document_service import DocumentService


class APIV1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_expected_routes_are_exposed(self) -> None:
        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }
        expected = {
            ("POST", "/api/v1/chat"),
            ("POST", "/api/v1/chat/stream"),
            ("GET", "/api/v1/me"),
            ("GET", "/api/v1/requests"),
            ("POST", "/api/v1/requests"),
            ("GET", "/api/v1/requests/{request_id}"),
            ("POST", "/api/v1/requests/{request_id}/submit"),
            ("POST", "/api/v1/requests/{request_id}/approve"),
            ("POST", "/api/v1/requests/{request_id}/decline"),
            ("GET", "/api/v1/documents"),
            ("POST", "/api/v1/documents"),
            ("POST", "/api/v1/documents/{document_id}/index"),
            ("POST", "/api/v1/feedback"),
            ("GET", "/api/v1/admin/metrics"),
            ("GET", "/api/v1/admin/unanswered"),
        }
        self.assertTrue(expected.issubset(routes))

    def test_chat_requires_bearer_token_and_ignores_x_user_identity(self) -> None:
        payload = {"messages": [{"role": "user", "content": "What can you help with?"}]}

        anonymous = self.client.post("/api/v1/chat", json=payload)
        x_user_only = self.client.post(
            "/api/v1/chat",
            headers={"X-User": "forged-user"},
            json=payload,
        )
        authenticated = self.client.post(
            "/api/v1/chat",
            headers=self._headers("employee"),
            json=payload,
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(x_user_only.status_code, 401)
        self.assertEqual(authenticated.status_code, 200)
        self.assertEqual(authenticated.json()["intent"], "view_capabilities")

    def test_cors_allows_configured_react_origin(self) -> None:
        response = self.client.options(
            "/api/v1/chat",
            headers={
                "Origin": settings.CORS_ORIGINS[0],
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            settings.CORS_ORIGINS[0],
        )

    def test_chat_stream_returns_incremental_ndjson_events(self) -> None:
        response = self.client.post(
            "/api/v1/chat/stream",
            headers=self._headers("employee"),
            json={"messages": [{"role": "user", "content": "What can you help with?"}]},
        )
        events = [json.loads(line) for line in response.text.splitlines()]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/x-ndjson")
        self.assertEqual(events[0]["type"], "start")
        self.assertTrue(any(event["type"] == "token" for event in events))
        self.assertEqual(events[-1]["type"], "complete")

    def test_document_routes_are_restricted_to_knowledge_admin(self) -> None:
        temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "Policy.md").write_text("# Policy\n\nDemo content.", encoding="utf-8")
        service = DocumentService(temp_dir)
        try:
            with patch("api.v1_routes.document_service", service):
                employee = self.client.get(
                    "/api/v1/documents",
                    headers=self._headers("employee"),
                )
                admin = self.client.get(
                    "/api/v1/documents",
                    headers=self._headers("knowledge_admin"),
                )
            self.assertEqual(employee.status_code, 403)
            self.assertEqual(admin.status_code, 200)
            self.assertEqual(len(admin.json()["documents"]), 1)
            self.assertTrue(admin.json()["documents"][0]["id"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _headers(self, username: str) -> dict:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": settings.DEMO_LOGIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


if __name__ == "__main__":
    unittest.main()
