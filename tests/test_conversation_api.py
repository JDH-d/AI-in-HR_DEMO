import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.schemas import ChatResponse, Message, SourceChunk
from app import app
from core import settings
from services.conversation_service import ConversationService


class ConversationV1APITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.service = ConversationService(str(self.temp_dir / "workflow.db"))
        self.client = TestClient(app)
        self.service_patch = patch("api.v1_routes.conversation_service", self.service)
        self.service_patch.start()
        self.employee_headers = self._headers("employee")
        self.manager_headers = self._headers("manager")

    def tearDown(self) -> None:
        self.service_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_streamed_chat_is_saved_and_can_be_reopened(self) -> None:
        created = self.client.post(
            "/api/v1/conversations",
            headers=self.employee_headers,
        )
        conversation_id = created.json()["conversation"]["id"]
        response = ChatResponse(
            message=Message(
                role="assistant",
                content="Partial-day PTO is supported.",
            ),
            intent="work",
            language="en",
            sources=[
                SourceChunk(
                    source="Vacation_Policy.md",
                    title="Vacation Policy",
                    section="Partial days",
                    category="leave",
                    version="1.0",
                    excerpt="Partial-day PTO is supported.",
                    score=0.91,
                )
            ],
        )

        with patch("api.v1_routes.chat_service.handle_chat", return_value=response):
            streamed = self.client.post(
                "/api/v1/chat/stream",
                headers=self.employee_headers,
                json={
                    "conversation_id": conversation_id,
                    "messages": [{"role": "user", "content": "Can I request a half day?"}],
                },
            )

        events = [json.loads(line) for line in streamed.text.splitlines()]
        reopened = self.client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=self.employee_headers,
        )
        listed = self.client.get(
            "/api/v1/conversations",
            headers=self.employee_headers,
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(streamed.status_code, 200)
        self.assertEqual(events[-1]["type"], "complete")
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(
            [message["content"] for message in reopened.json()["messages"]],
            ["Can I request a half day?", "Partial-day PTO is supported."],
        )
        self.assertEqual(
            reopened.json()["messages"][1]["sources"][0]["title"],
            "Vacation Policy",
        )
        self.assertEqual(
            listed.json()["conversations"][0]["title"],
            "Can I request a half day?",
        )

    def test_empty_conversation_is_hidden_from_recent_list(self) -> None:
        created = self.client.post(
            "/api/v1/conversations",
            headers=self.employee_headers,
        )
        listed = self.client.get(
            "/api/v1/conversations",
            headers=self.employee_headers,
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(listed.json(), {"conversations": []})

    def test_history_routes_are_employee_only(self) -> None:
        create = self.client.post(
            "/api/v1/conversations",
            headers=self.manager_headers,
        )
        listed = self.client.get(
            "/api/v1/conversations",
            headers=self.manager_headers,
        )

        self.assertEqual(create.status_code, 403)
        self.assertEqual(listed.status_code, 403)

    def test_employee_can_delete_own_conversation(self) -> None:
        conversation = self.service.create("employee.demo")
        self.service.append_exchange(
            conversation["id"],
            "employee.demo",
            user_text="Temporary question",
            assistant_text="Temporary answer",
        )

        forbidden = self.client.delete(
            f"/api/v1/conversations/{conversation['id']}",
            headers=self.manager_headers,
        )
        deleted = self.client.delete(
            f"/api/v1/conversations/{conversation['id']}",
            headers=self.employee_headers,
        )
        reopened = self.client.get(
            f"/api/v1/conversations/{conversation['id']}",
            headers=self.employee_headers,
        )
        deleted_again = self.client.delete(
            f"/api/v1/conversations/{conversation['id']}",
            headers=self.employee_headers,
        )

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(deleted.json()["conversation"]["id"], conversation["id"])
        self.assertEqual(reopened.status_code, 404)
        self.assertEqual(deleted_again.status_code, 404)

    def test_unknown_conversation_is_rejected_before_chat_processing(self) -> None:
        with patch("api.v1_routes.chat_service.handle_chat") as handle_chat:
            response = self.client.post(
                "/api/v1/chat",
                headers=self.employee_headers,
                json={
                    "conversation_id": "missing",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

        self.assertEqual(response.status_code, 404)
        handle_chat.assert_not_called()

    def _headers(self, username: str) -> dict:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": settings.DEMO_LOGIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


if __name__ == "__main__":
    unittest.main()
