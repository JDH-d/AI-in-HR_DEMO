import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.schemas import ChatResponse, Message
from api.v1_routes import _stream_chat_response
from app import app
from core import settings
from domain.request_policy import RequestConflictError
from domain.workflow import InvalidTransitionError
from services.auth_service import AuthenticationError, DemoAuthService
from services.runtime import get_runtime
from services.workflow_service import WorkflowService


def test_import_does_not_create_database(tmp_path):
    database = tmp_path / "uncreated" / "workflow.db"
    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        env={**os.environ, "WORKFLOW_DB": str(database), "DEMO_AUTH_SECRET": ""},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not database.parent.exists()


def test_startup_rejects_missing_signing_secret():
    with patch.object(settings, "DEMO_AUTH_SECRET", ""):
        with pytest.raises(ValueError, match="DEMO_AUTH_SECRET"):
            settings.validate_auth_settings()


def test_unicode_credentials_and_invalid_token():
    auth = DemoAuthService("x" * 32, "пароль")
    token, user = auth.login("employee", "пароль")
    assert auth.verify_token(token) == user
    with pytest.raises(AuthenticationError):
        auth.verify_token("невалидный.токен")


def test_stream_preserves_original_whitespace():
    content = "A paragraph.\n\n- first\n- second\n  indented\ttext  "
    response = ChatResponse(
        message=Message(role="assistant", content=content), intent="work", language="en"
    )
    events = [json.loads(line) for line in _stream_chat_response(response)]
    assert "".join(event["content"] for event in events if event["type"] == "token") == content


def test_concurrent_decisions_create_only_one_final_event(tmp_path):
    workflow = WorkflowService(str(tmp_path / "workflow.db"))
    draft = workflow.create_structured_draft(
        request_type="document",
        start_date=None,
        end_date=None,
        comment="Letter",
        applicant="employee",
        approver="manager",
    )
    submitted = workflow.confirm_draft(draft["id"], "employee", {})
    review = workflow.act(draft["id"], "manager", "manager", "start_review", submitted["revision"])

    def decide(target):
        try:
            workflow.act(
                draft["id"],
                "manager",
                "manager",
                target,
                review["revision"],
                comment="Decision",
                basis="Policy",
                fair_review_confirmed=True,
            )
            return True
        except (InvalidTransitionError, RequestConflictError):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(decide, ["approve", "reject"])) == 1
    events = workflow.history(draft["id"])["events"]
    assert sum(event["to_status"] in {"approved", "rejected"} for event in events) == 1


def test_manager_chat_is_denied_before_creating_conversation_or_draft():
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": settings.DEMO_LOGIN_PASSWORD},
        ).json()
        runtime = get_runtime()
        with (
            patch.object(runtime.chat_service, "respond") as respond,
            patch.object(runtime.conversation_service, "create") as create_conversation,
        ):
            result = client.post(
                "/api/v1/chat",
                headers={"Authorization": f"Bearer {login['access_token']}"},
                json={"messages": [{"role": "user", "content": "I need vacation tomorrow"}]},
            )
        assert result.status_code == 403
        respond.assert_not_called()
        create_conversation.assert_not_called()


def test_document_submission_can_clear_dates_without_erasing_optional_text(tmp_path):
    workflow = WorkflowService(str(tmp_path / "workflow.db"))
    with TestClient(app) as client, patch.object(get_runtime(), "workflow_service", workflow):
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "employee", "password": settings.DEMO_LOGIN_PASSWORD},
        ).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}
        draft = client.post(
            "/api/v1/requests",
            headers=headers,
            json={
                "type": "pto",
                "start_date": "2030-01-01",
                "end_date": "2030-01-03",
                "comment": "Original note",
            },
        ).json()["request"]
        response = client.post(
            f"/api/v1/requests/{draft['id']}/submit",
            headers=headers,
            json={
                "type": "document",
                "start_date": None,
                "end_date": None,
                "comment": None,
                "expected_revision": draft["revision"],
            },
        )
    assert response.status_code == 200
    request = response.json()["request"]
    assert request["start_date"] is None
    assert request["end_date"] is None
    assert request["duration_days"] is None
    assert request["comment"] == "Original note"
    assert request["approver"] == draft["approver"]
