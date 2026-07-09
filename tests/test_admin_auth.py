import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app


class AdminAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_admin_route_requires_token(self) -> None:
        with patch("api.dependencies.ADMIN_TOKEN", "demo-admin-token"):
            response = self.client.get("/admin/system-prompt")

        self.assertEqual(response.status_code, 401)

    def test_admin_route_accepts_bearer_token(self) -> None:
        with patch("api.dependencies.ADMIN_TOKEN", "demo-admin-token"):
            response = self.client.get(
                "/admin/system-prompt",
                headers={"Authorization": "Bearer demo-admin-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("system_prompt", response.json())

    def test_rebuild_index_returns_clear_service_error(self) -> None:
        with (
            patch("api.dependencies.ADMIN_TOKEN", "demo-admin-token"),
            patch(
                "api.admin_routes.rebuild_index",
                side_effect=RuntimeError("embedding failure"),
            ),
        ):
            response = self.client.post(
                "/admin/rebuild-index",
                headers={"Authorization": "Bearer demo-admin-token"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "Index rebuild failed. Check document readability and OpenAI configuration.",
        )


if __name__ == "__main__":
    unittest.main()
