import unittest

from fastapi.testclient import TestClient

from app import app
from core import settings


class DemoAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_login_and_me_return_predefined_identity(self) -> None:
        login = self.client.post(
            "/api/v1/auth/login",
            json={"username": "employee", "password": settings.DEMO_LOGIN_PASSWORD},
        )

        self.assertEqual(login.status_code, 200)
        token = login.json()["access_token"]
        me = self.client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["id"], "employee.demo")
        self.assertEqual(me.json()["user"]["role"], "employee")

    def test_invalid_password_is_rejected(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "employee", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)

    def test_metrics_requires_authentication_and_knowledge_admin_role(self) -> None:
        anonymous = self.client.get("/api/v1/admin/metrics")
        employee = self.client.get(
            "/api/v1/admin/metrics",
            headers=self._headers("employee"),
        )
        admin = self.client.get(
            "/api/v1/admin/metrics",
            headers=self._headers("knowledge_admin"),
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(employee.status_code, 403)
        self.assertEqual(admin.status_code, 200)
        self.assertIn("requests_by_status", admin.json()["metrics"])

    def test_tampered_token_is_rejected(self) -> None:
        token = self._token("manager")
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

        response = self.client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {tampered}"},
        )

        self.assertEqual(response.status_code, 401)

    def test_legacy_identity_routes_are_not_exposed(self) -> None:
        self.assertEqual(self.client.post("/chat", json={"messages": []}).status_code, 404)
        self.assertEqual(
            self.client.get("/requests", headers={"X-User": "anyone"}).status_code, 404
        )
        self.assertEqual(self.client.get("/admin/requests").status_code, 404)

    def _headers(self, username: str) -> dict:
        return {"Authorization": f"Bearer {self._token(username)}"}

    def _token(self, username: str) -> str:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": settings.DEMO_LOGIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]


if __name__ == "__main__":
    unittest.main()
