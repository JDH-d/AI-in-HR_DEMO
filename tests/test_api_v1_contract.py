import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.schemas import ChatResponse, Message
from api.v1_routes import _unanswered_entries
from app import app
from core import settings
from services.ai_settings_service import AISettingsService
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
            ("POST", "/api/v1/conversations"),
            ("GET", "/api/v1/conversations"),
            ("GET", "/api/v1/conversations/{conversation_id}"),
            ("GET", "/api/v1/me"),
            ("GET", "/api/v1/requests"),
            ("POST", "/api/v1/requests"),
            ("GET", "/api/v1/requests/{request_id}"),
            ("POST", "/api/v1/requests/{request_id}/submit"),
            ("POST", "/api/v1/requests/{request_id}/approve"),
            ("POST", "/api/v1/requests/{request_id}/decline"),
            ("GET", "/api/v1/documents"),
            ("POST", "/api/v1/documents"),
            ("GET", "/api/v1/documents/{document_id}/download"),
            ("DELETE", "/api/v1/documents/{document_id}"),
            ("POST", "/api/v1/documents/{document_id}/index"),
            ("POST", "/api/v1/feedback"),
            ("GET", "/api/v1/admin/metrics"),
            ("GET", "/api/v1/admin/unanswered"),
            ("GET", "/api/v1/admin/feedback"),
            ("POST", "/api/v1/admin/quality/{item_id}"),
            ("GET", "/api/v1/admin/ai-settings"),
            ("PUT", "/api/v1/admin/ai-settings"),
            ("POST", "/api/v1/admin/ai-settings/test"),
        }
        self.assertTrue(expected.issubset(routes))
        self.assertNotIn(("POST", "/api/v1/requests/{request_id}/complete"), routes)

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

    def test_admin_can_upload_download_and_delete_document(self) -> None:
        temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        service = DocumentService(
            temp_dir,
            index_path=temp_dir / "index.json",
            index_status_path=temp_dir / "index_status.json",
        )
        content = b"# Remote Work\n\nEmployees may work remotely two days per week."
        try:
            with (
                patch("api.v1_routes.document_service", service),
                patch("api.v1_routes.rebuild_index") as rebuild,
            ):
                uploaded = self.client.post(
                    "/api/v1/documents",
                    headers=self._headers("knowledge_admin"),
                    files={"file": ("Remote_Work.md", content, "text/markdown")},
                )
                document_id = uploaded.json()["document"]["id"]
                downloaded = self.client.get(
                    f"/api/v1/documents/{document_id}/download",
                    headers=self._headers("knowledge_admin"),
                )
                forbidden = self.client.get(
                    f"/api/v1/documents/{document_id}/download",
                    headers=self._headers("employee"),
                )
                deleted = self.client.delete(
                    f"/api/v1/documents/{document_id}",
                    headers=self._headers("knowledge_admin"),
                )

            self.assertEqual(uploaded.status_code, 201)
            self.assertEqual(uploaded.json()["document"]["index_status"], "indexed")
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(downloaded.content, content)
            self.assertIn("Remote_Work.md", downloaded.headers["content-disposition"])
            self.assertEqual(forbidden.status_code, 403)
            self.assertEqual(deleted.status_code, 200)
            self.assertTrue(deleted.json()["index_refreshed"])
            self.assertFalse((temp_dir / "Remote_Work.md").exists())
            self.assertEqual(rebuild.call_count, 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_upload_waits_for_manual_indexing_when_auto_index_is_disabled(self) -> None:
        temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        service = DocumentService(
            temp_dir,
            index_path=temp_dir / "index.json",
            index_status_path=temp_dir / "index_status.json",
        )
        try:
            with (
                patch("api.v1_routes.document_service", service),
                patch(
                    "api.v1_routes.ai_settings_service.get",
                    return_value={"auto_index_uploads": False},
                ),
                patch("api.v1_routes.rebuild_index") as rebuild,
            ):
                response = self.client.post(
                    "/api/v1/documents",
                    headers=self._headers("knowledge_admin"),
                    files={"file": ("Policy.md", b"# Policy\n\nContent", "text/markdown")},
                )

            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["document"]["index_status"], "pending")
            rebuild.assert_not_called()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_ai_settings_preview_uses_unsaved_values_without_side_effects(self) -> None:
        temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(temp_dir, ignore_errors=True)
        service = AISettingsService(temp_dir / "ai_settings.json")
        prompt_state = {"value": "Saved prompt"}
        payload = {
            "settings": {
                "strict_grounding": False,
                "concise_answers": True,
                "ask_clarifying_questions": True,
                "suggest_next_steps": False,
                "show_sources": False,
                "auto_index_uploads": True,
            },
            "system_prompt": "Unsaved preview prompt",
        }
        preview_response = ChatResponse(
            message=Message(role="assistant", content="Preview answer"),
            intent="work",
            language="en",
            sources=[],
        )
        try:
            with (
                patch("api.v1_routes.ai_settings_service", service),
                patch(
                    "api.v1_routes.load_system_prompt",
                    side_effect=lambda: prompt_state["value"],
                ),
                patch(
                    "api.v1_routes.save_system_prompt",
                    side_effect=lambda value: prompt_state.update(value=value),
                ),
                patch(
                    "api.v1_routes.chat_service.handle_chat",
                    return_value=preview_response,
                ) as handle_chat,
            ):
                saved = self.client.put(
                    "/api/v1/admin/ai-settings",
                    headers=self._headers("knowledge_admin"),
                    json={**payload, "system_prompt": "Saved custom prompt"},
                )
                previewed = self.client.post(
                    "/api/v1/admin/ai-settings/test",
                    headers=self._headers("knowledge_admin"),
                    json={**payload, "question": "How does relocation work?"},
                )

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["system_prompt"], "Saved custom prompt")
            self.assertIn("default_system_prompt", saved.json())
            self.assertEqual(previewed.status_code, 200)
            self.assertEqual(previewed.json()["answer"], "Preview answer")
            call = handle_chat.call_args
            self.assertEqual(call.kwargs["settings_override"], payload["settings"])
            self.assertEqual(call.kwargs["system_prompt_override"], "Unsaved preview prompt")
            self.assertFalse(call.kwargs["log_outcome"])
            self.assertFalse(call.kwargs["allow_workflow"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_ai_settings_reject_blank_prompt_and_preview_question(self) -> None:
        headers = self._headers("knowledge_admin")
        settings_payload = {
            "strict_grounding": True,
            "concise_answers": True,
            "ask_clarifying_questions": True,
            "suggest_next_steps": True,
            "show_sources": True,
            "auto_index_uploads": True,
        }

        blank_prompt = self.client.put(
            "/api/v1/admin/ai-settings",
            headers=headers,
            json={"settings": settings_payload, "system_prompt": "   "},
        )
        blank_question = self.client.post(
            "/api/v1/admin/ai-settings/test",
            headers=headers,
            json={
                "settings": settings_payload,
                "system_prompt": "Valid prompt",
                "question": "   ",
            },
        )

        self.assertEqual(blank_prompt.status_code, 422)
        self.assertEqual(blank_question.status_code, 422)

    def test_unanswered_queue_excludes_out_of_scope_noise_and_reviewed_items(self) -> None:
        logs = [
            {
                "ts": "2030-01-01T10:00:00+00:00",
                "user": "Talk me Dragon",
                "assistant": "I can assist only with supported workplace topics.",
                "intent": "invalid",
                "sources": [],
            },
            {
                "ts": "2030-01-01T10:01:00+00:00",
                "user": "What is the relocation allowance?",
                "assistant": "I could not find a reliable answer in the current documents.",
                "intent": "work",
                "sources": [],
            },
            {
                "ts": "2030-01-01T10:02:00+00:00",
                "user": "When is payroll processed?",
                "assistant": "Payroll is processed twice per month.",
                "intent": "work",
                "sources": [{"title": "Payroll"}],
            },
        ]

        active = _unanswered_entries(logs)
        reviewed = _unanswered_entries(logs, {active[0]["id"]})

        self.assertEqual(
            [item["question"] for item in active], ["What is the relocation allowance?"]
        )
        self.assertEqual(reviewed, [])

    def _headers(self, username: str) -> dict:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": settings.DEMO_LOGIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


if __name__ == "__main__":
    unittest.main()
