from __future__ import annotations

import hashlib
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.routes.admin import build_unanswered_entries
from app import create_app
from rag.nlp import Intent
from services.chat_models import ChatOutcome
from tests.support import TEST_PASSWORD, build_test_services


class APIV1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.services = build_test_services(self.temp_dir)
        self.app = create_app(lambda: self.services)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_me_exposes_storage_identity_only_after_authentication(self) -> None:
        for headers in ({}, {"X-User": "employee.demo"}, {"Authorization": "Bearer invalid"}):
            response = self.client.get("/api/v1/me", headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("backend_id", response.json())
        employee = self.client.get("/api/v1/me", headers=self._headers("employee"))
        manager = self.client.get("/api/v1/me", headers=self._headers("manager"))
        self.assertEqual(employee.status_code, 200)
        self.assertEqual(manager.status_code, 200)
        self.assertEqual(set(employee.json()), {"user", "backend_id"})
        self.assertEqual(employee.json()["user"]["id"], "employee.demo")
        backend_id = employee.json()["backend_id"]
        self.assertEqual(str(uuid.UUID(backend_id)), backend_id)
        self.assertEqual(backend_id, self.services.conversations.backend_id)
        self.assertEqual(backend_id, manager.json()["backend_id"])
        self.assertNotIn("backend_id", self.client.get("/api/v1/health").json())

    def test_me_identity_survives_service_restart_but_changes_with_another_database(self) -> None:
        headers = self._headers("employee")
        first = self.client.get("/api/v1/me", headers=headers).json()
        # A new container reads the same test storage through a different origin.
        restarted = build_test_services(self.temp_dir)
        with TestClient(create_app(lambda: restarted), base_url="http://other-host:4567") as client:
            response = client.get("/api/v1/me", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), first)
        other = build_test_services(self.temp_dir / "other-backend")
        with TestClient(create_app(lambda: other)) as client:
            response = client.get("/api/v1/me", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertNotEqual(response.json()["backend_id"], first["backend_id"])
            self.assertEqual(response.json()["user"], first["user"])

    def test_expected_routes_are_exposed(self) -> None:
        routes = {
            (method, route.path)
            for route in self.app.routes
            for method in getattr(route, "methods", set())
        }
        expected = {
            ("GET", "/api/v1/health"),
            ("POST", "/api/v1/auth/login"),
            ("POST", "/api/v1/chat"),
            ("POST", "/api/v1/chat/stream"),
            ("GET", "/api/v1/conversations"),
            ("GET", "/api/v1/conversations/{conversation_id}"),
            ("DELETE", "/api/v1/conversations/{conversation_id}"),
            ("GET", "/api/v1/me"),
            ("GET", "/api/v1/requests"),
            ("POST", "/api/v1/requests"),
            ("GET", "/api/v1/requests/{request_id}"),
            ("POST", "/api/v1/requests/{request_id}/submit"),
            ("POST", "/api/v1/requests/{request_id}/cancel"),
            ("POST", "/api/v1/requests/{request_id}/approve"),
            ("POST", "/api/v1/requests/{request_id}/decline"),
            ("POST", "/api/v1/requests/{request_id}/acknowledge"),
            ("POST", "/api/v1/requests/{request_id}/comments"),
            ("GET", "/api/v1/documents"),
            ("POST", "/api/v1/documents"),
            ("POST", "/api/v1/documents/index"),
            ("GET", "/api/v1/documents/{document_id}/download"),
            ("DELETE", "/api/v1/documents/{document_id}"),
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
        self.assertNotIn(("POST", "/api/v1/conversations"), routes)
        self.assertNotIn(("POST", "/api/v1/documents/{document_id}/index"), routes)
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
        manager = self.client.post(
            "/api/v1/chat",
            headers=self._headers("manager"),
            json=payload,
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(x_user_only.status_code, 401)
        self.assertEqual(authenticated.status_code, 200)
        self.assertEqual(authenticated.json()["intent"], "view_capabilities")
        self.assertEqual(manager.status_code, 403)

    def test_cors_allows_configured_react_origin(self) -> None:
        response = self.client.options(
            "/api/v1/chat",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "http://127.0.0.1:5173",
        )

    def test_chat_stream_returns_ndjson_and_preserves_whitespace(self) -> None:
        response = self.client.post(
            "/api/v1/chat/stream",
            headers=self._headers("employee"),
            json={"messages": [{"role": "user", "content": "What can you help with?"}]},
        )
        events = [json.loads(line) for line in response.text.splitlines()]
        content = "".join(event["content"] for event in events if event["type"] == "token")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/x-ndjson")
        self.assertEqual(events[0]["type"], "start")
        self.assertIn("\n1. PTO, vacation, and sick leave\n", content)
        self.assertEqual(events[-1]["type"], "complete")
        self.assertTrue(events[-1]["conversation_id"])

    def test_conversation_is_created_by_first_successful_exchange(self) -> None:
        headers = self._headers("employee")
        streamed = self.client.post(
            "/api/v1/chat/stream",
            headers=headers,
            json={"messages": [{"role": "user", "content": "What can you help with?"}]},
        )
        complete = [
            json.loads(line)
            for line in streamed.text.splitlines()
            if json.loads(line)["type"] == "complete"
        ][0]
        conversation_id = complete["conversation_id"]
        listed = self.client.get("/api/v1/conversations", headers=headers)
        detail = self.client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=headers,
        )

        self.assertEqual(streamed.status_code, 200)
        self.assertEqual(listed.json()["conversations"][0]["id"], conversation_id)
        self.assertEqual(
            [message["role"] for message in detail.json()["messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(detail.json()["messages"][0]["content"], "What can you help with?")

    def test_existing_conversation_requires_a_new_user_message(self) -> None:
        headers = self._headers("employee")
        created = self.client.post(
            "/api/v1/chat",
            headers=headers,
            json={"messages": [{"role": "user", "content": "What can you help with?"}]},
        ).json()
        conversation_id = created["conversation_id"]

        response = self.client.post(
            "/api/v1/chat",
            headers=headers,
            json={
                "conversation_id": conversation_id,
                "messages": [{"role": "assistant", "content": "Repeat the previous action."}],
            },
        )
        detail = self.client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=headers,
        ).json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail["conversation"]["message_count"], 2)
        self.assertEqual(self.services.workflow.list_for_user("employee.demo"), [])

    def test_employee_can_delete_a_conversation_with_an_empty_204_response(self) -> None:
        headers = self._headers("employee")
        created = self.client.post(
            "/api/v1/chat",
            headers=headers,
            json={"messages": [{"role": "user", "content": "What can you help with?"}]},
        ).json()
        path = f"/api/v1/conversations/{created['conversation_id']}"

        deleted = self.client.delete(path, headers=headers)

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.content, b"")
        self.assertEqual(self.client.get(path, headers=headers).status_code, 404)
        self.assertEqual(
            self.client.get("/api/v1/conversations", headers=headers).json()["conversations"],
            [],
        )
        self.assertEqual(self.client.delete(path, headers=headers).status_code, 404)
        self.assertEqual(self.services.conversations.metrics()["questions"], 0)

    def test_delete_returns_the_same_404_for_foreign_and_missing_conversations(self) -> None:
        foreign = self.services.conversations.record_exchange(
            "another.employee",
            conversation_id=None,
            user_content="Private question",
            assistant_content="Private answer.",
        )
        foreign_id = foreign["conversation"]["id"]
        headers = self._headers("employee")

        denied = self.client.delete(f"/api/v1/conversations/{foreign_id}", headers=headers)
        missing = self.client.delete("/api/v1/conversations/missing-conversation", headers=headers)

        self.assertEqual(denied.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(denied.json(), missing.json())
        self.assertEqual(
            self.services.conversations.get_for_user(foreign_id, "another.employee"),
            foreign,
        )

    def test_delete_conversation_requires_employee_authentication(self) -> None:
        detail = self.services.conversations.record_exchange(
            "employee.demo",
            conversation_id=None,
            user_content="Private question",
            assistant_content="Private answer.",
        )
        path = f"/api/v1/conversations/{detail['conversation']['id']}"

        self.assertEqual(self.client.delete(path).status_code, 401)
        for role in ("manager", "knowledge_admin"):
            with self.subTest(role=role):
                self.assertEqual(
                    self.client.delete(path, headers=self._headers(role)).status_code,
                    403,
                )
        self.assertIsNotNone(
            self.services.conversations.get_for_user(detail["conversation"]["id"], "employee.demo")
        )

    def test_deleting_a_conversation_preserves_its_workflow_request_and_timeline(self) -> None:
        employee_headers = self._headers("employee")
        created = self.client.post(
            "/api/v1/chat",
            headers=employee_headers,
            json={
                "messages": [
                    {"role": "user", "content": "I need vacation from 2030-04-01 to 2030-04-03"}
                ]
            },
        ).json()
        request_id = created["workflow_request"]["id"]
        request_path = f"/api/v1/requests/{request_id}"
        submitted = self.client.post(
            f"{request_path}/submit",
            headers=employee_headers,
            json={"comment": "Family vacation"},
        )
        self.assertEqual(submitted.status_code, 200)
        before = self.client.get(request_path, headers=employee_headers).json()

        deleted = self.client.delete(
            f"/api/v1/conversations/{created['conversation_id']}",
            headers=employee_headers,
        )

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(request_path, headers=employee_headers).json(), before)
        manager_requests = self.client.get(
            "/api/v1/requests",
            headers=self._headers("manager"),
        ).json()["requests"]
        self.assertEqual([request["id"] for request in manager_requests], [request_id])
        self.assertEqual(manager_requests[0]["status"], "in_review")
        self.assertEqual(self.services.workflow.metrics()["total_requests"], 1)

    def test_conversation_workflow_card_reflects_current_request_state(self) -> None:
        headers = self._headers("employee")
        streamed = self.client.post(
            "/api/v1/chat/stream",
            headers=headers,
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": "I need vacation from 2030-04-01 to 2030-04-03",
                    }
                ]
            },
        )
        complete = [
            json.loads(line)
            for line in streamed.text.splitlines()
            if json.loads(line)["type"] == "complete"
        ][0]
        request_id = complete["workflow_request"]["id"]
        submitted = self.client.post(
            f"/api/v1/requests/{request_id}/submit",
            headers=headers,
            json={"comment": "Family vacation"},
        )
        detail = self.client.get(
            f"/api/v1/conversations/{complete['conversation_id']}",
            headers=headers,
        )

        self.assertEqual(submitted.status_code, 200)
        assistant_message = detail.json()["messages"][1]
        self.assertEqual(assistant_message["workflow"]["status"], "in_review")

    def test_document_routes_are_restricted_to_knowledge_admin(self) -> None:
        (self.temp_dir / "documents" / "Policy.md").write_text(
            "# Policy\n\nDemo content.",
            encoding="utf-8",
        )
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

    def test_admin_can_upload_index_download_and_delete_document(self) -> None:
        content = b"# Remote Work\n\nEmployees may work remotely two days per week."
        headers = self._headers("knowledge_admin")

        uploaded = self.client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("Remote_Work.md", content, "text/markdown")},
        )
        document_id = uploaded.json()["document"]["id"]
        downloaded = self.client.get(
            f"/api/v1/documents/{document_id}/download",
            headers=headers,
        )
        forbidden = self.client.get(
            f"/api/v1/documents/{document_id}/download",
            headers=self._headers("employee"),
        )
        rebuilt = self.client.post("/api/v1/documents/index", headers=headers)
        deleted = self.client.delete(
            f"/api/v1/documents/{document_id}",
            headers=headers,
        )

        self.assertEqual(uploaded.status_code, 201)
        self.assertEqual(uploaded.json()["document"]["index_status"], "indexed")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, content)
        self.assertIn("Remote_Work.md", downloaded.headers["content-disposition"])
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(rebuilt.status_code, 200)
        self.assertEqual(rebuilt.json()["scope"], "all_documents")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["index_refreshed"])
        self.assertFalse((self.temp_dir / "documents" / "Remote_Work.md").exists())

    def test_upload_waits_for_manual_indexing_when_auto_index_is_disabled(self) -> None:
        self.services.ai_settings.save_configuration(
            {"auto_index_uploads": False},
            self.services.ai_settings.get_system_prompt(),
        )
        response = self.client.post(
            "/api/v1/documents",
            headers=self._headers("knowledge_admin"),
            files={"file": ("Policy.md", b"# Policy\n\nContent", "text/markdown")},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["document"]["index_status"], "pending")
        self.assertFalse((self.temp_dir / "index.json").exists())

    def test_failed_upload_indexing_rolls_back_document_and_index(self) -> None:
        old_index = b'{"mode":"lexical","items":[]}'
        (self.temp_dir / "index.json").write_bytes(old_index)
        self.services.knowledge_index._retriever = object()
        with patch.object(
            self.services.knowledge_index,
            "rebuild",
            side_effect=RuntimeError("broken document"),
        ):
            response = self.client.post(
                "/api/v1/documents",
                headers=self._headers("knowledge_admin"),
                files={"file": ("Broken.md", b"# Broken\n\nContent", "text/markdown")},
            )

        self.assertEqual(response.status_code, 503)
        self.assertFalse((self.temp_dir / "documents" / "Broken.md").exists())
        self.assertEqual((self.temp_dir / "index.json").read_bytes(), old_index)
        self.assertIsNone(self.services.knowledge_index._retriever)

    def test_failed_delete_indexing_restores_document_index_and_cache(self) -> None:
        content = b"# Policy\n\nImportant policy text."
        document_path = self.temp_dir / "documents" / "Policy.md"
        document_path.write_bytes(content)
        old_index = b'{"mode":"lexical","items":[]}'
        old_status = b'{"legacy":{"status":"indexed"}}'
        (self.temp_dir / "index.json").write_bytes(old_index)
        (self.temp_dir / "index_status.json").write_bytes(old_status)
        document_id = self.services.documents.document_id("Policy.md")
        self.services.knowledge_index._retriever = object()

        with patch.object(
            self.services.knowledge_index,
            "rebuild",
            side_effect=RuntimeError("broken index"),
        ):
            response = self.client.delete(
                f"/api/v1/documents/{document_id}",
                headers=self._headers("knowledge_admin"),
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(document_path.read_bytes(), content)
        self.assertEqual((self.temp_dir / "index.json").read_bytes(), old_index)
        self.assertEqual((self.temp_dir / "index_status.json").read_bytes(), old_status)
        self.assertIsNone(self.services.knowledge_index._retriever)

    def test_ai_settings_preview_uses_unsaved_values_without_side_effects(self) -> None:
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
        preview_outcome = ChatOutcome(
            content="Preview answer",
            intent=Intent.WORK,
            language="en",
        )
        with patch.object(
            self.services.chat,
            "respond",
            return_value=preview_outcome,
        ) as respond:
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
        call = respond.call_args
        self.assertEqual(call.kwargs["settings"], payload["settings"])
        self.assertEqual(call.kwargs["system_prompt"], "Unsaved preview prompt")
        self.assertFalse(call.kwargs["log_outcome"])
        self.assertFalse(call.kwargs["allow_workflow"])
        self.assertEqual(
            self.services.ai_settings.get_system_prompt(),
            "Saved custom prompt",
        )

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

    def test_unanswered_queue_uses_outcome_code_and_excludes_reviewed_items(self) -> None:
        logs = [
            {
                "ts": "2030-01-01T10:00:00+00:00",
                "user": "Talk me Dragon",
                "assistant": "I can assist only with supported workplace topics.",
                "intent": "invalid",
                "outcome_code": "unsupported",
                "sources": [],
            },
            {
                "ts": "2030-01-01T10:01:00+00:00",
                "user": "What is the relocation allowance?",
                "assistant": "No matching policy was found.",
                "intent": "work",
                "outcome_code": "no_match",
                "sources": [],
            },
            {
                "ts": "2030-01-01T10:02:00+00:00",
                "user": "When is payroll processed?",
                "assistant": "Payroll is processed twice per month.",
                "intent": "work",
                "outcome_code": "grounded",
                "sources": [{"title": "Payroll"}],
            },
        ]

        active = build_unanswered_entries(logs)
        reviewed = build_unanswered_entries(logs, {active[0]["id"]})

        expected_id = hashlib.sha256(
            b"2030-01-01T10:01:00+00:00\nWhat is the relocation allowance?"
        ).hexdigest()[:16]
        self.assertEqual(active[0]["id"], expected_id)
        self.assertEqual(
            [item["question"] for item in active],
            ["What is the relocation allowance?"],
        )
        self.assertEqual(reviewed, [])

    def _headers(self, username: str) -> dict[str, str]:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": TEST_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


if __name__ == "__main__":
    unittest.main()
