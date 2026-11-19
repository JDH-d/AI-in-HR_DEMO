import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app import create_app
from core import settings
from domain.chat import ChatOutcome, Intent, RetrievedChunk
from domain.errors import ConversationError
from domain.workflow import WorkflowDraftData
from services.auth_service import DEMO_IDENTITIES, DemoIdentity
from services.conversation_service import ConversationService
from services.runtime import get_runtime
from storage.conversation_store import ConversationStore
from storage.workflow_store import WorkflowStore

EMPLOYEE = DEMO_IDENTITIES["employee"]
MANAGER = DEMO_IDENTITIES["manager"]
OTHER = DemoIdentity("other.employee", "other", "Other employee", "employee", MANAGER.id)


@pytest.fixture
def history(tmp_path):
    chat = Mock()
    chat.respond.return_value = ChatOutcome(
        "Saved answer",
        Intent.WORK,
        "en",
        [RetrievedChunk("policy.md", 0, "Policy", "PTO", "HR", "1", "Evidence", 0.9)],
    )
    return ConversationService(ConversationStore(tmp_path / "workflow.db"), chat)


def send(history, user=EMPLOYEE, conversation_id=None, text="Vacation policy", turn_id=None):
    cid = conversation_id or history.create(user)["id"]
    return history.send(user, cid, text, turn_id or str(uuid.uuid4()))


def test_messages_users_sources_and_timestamps_survive_reopening_database(history):
    response = send(history)
    cid = response["conversation"]["id"]
    reopened = ConversationService(ConversationStore(history.store.path), history.chat)
    detail = reopened.get(EMPLOYEE, cid)
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert [m["content"] for m in detail["messages"]] == ["Vacation policy", "Saved answer"]
    assert detail["messages"][1]["sources"][0]["title"] == "Policy"
    assert detail["messages"][0]["sender_id"] == EMPLOYEE.id
    assert all(m["created_at"].endswith("+00:00") for m in detail["messages"])
    with closing(sqlite3.connect(history.store.path)) as db, db:
        assert db.execute(
            "SELECT display_name, role FROM users WHERE id=?", (EMPLOYEE.id,)
        ).fetchone() == (EMPLOYEE.display_name, "employee")
    send(reopened, conversation_id=cid, text="And what about notice?")
    query = history.chat.respond.call_args.args[0]
    assert [m.content for m in query.messages] == [
        "Vacation policy",
        "Saved answer",
        "And what about notice?",
    ]
    assert len(reopened.get(EMPLOYEE, cid)["messages"]) == 4


def test_owner_access_applies_to_search_read_rename_delete_and_send(history):
    viewer = OTHER
    cid = send(history)["conversation"]["id"]
    assert history.list(viewer, "Vacation")["conversations"] == []
    for operation in [
        lambda: history.get(viewer, cid),
        lambda: history.rename(viewer, cid, "Hijacked"),
        lambda: history.delete(viewer, cid),
        lambda: send(history, viewer, cid),
    ]:
        with pytest.raises(ConversationError) as failure:
            operation()
        assert failure.value.code == "not_found"
    assert history.get(EMPLOYEE, cid)["conversation"]["title"] == "Vacation policy"
    own = send(history, viewer)
    assert len(history.list(viewer)["conversations"]) == 1
    assert history.get(viewer, own["conversation"]["id"])
    assert history.chat.respond.call_args.kwargs["allow_workflow"] is True


def seed_legacy_conversation(history, identity):
    """Existing non-Employee rows remain stored even after chat access is removed."""
    history.record_user(identity)
    cid, tid = str(uuid.uuid4()), str(uuid.uuid4())
    history.store.create(identity.id, cid, "Existing saved conversation")
    turn = history.store.begin_turn(cid, identity.id, tid, "Existing question", 60)
    history.store.finish_turn(
        cid, tid, "Existing answer", {}, attempt_id=turn["attempt_id"]
    )
    return cid


def database_snapshot(history):
    with closing(sqlite3.connect(history.store.path)) as db:
        return tuple(db.iterdump())


@pytest.mark.parametrize("viewer", [MANAGER, DEMO_IDENTITIES["knowledge_admin"]])
def test_nonemployee_service_access_is_denied_without_changing_saved_history(history, viewer):
    own = seed_legacy_conversation(history, viewer)
    employee = history.create(EMPLOYEE)["id"]
    before = database_snapshot(history)
    operations = [
        lambda: history.create(viewer),
        lambda: history.list(viewer, "Existing"),
    ]
    for cid in (own, employee):
        operations.extend(
            [
                lambda cid=cid: history.get(viewer, cid),
                lambda cid=cid: history.rename(viewer, cid, "Changed"),
                lambda cid=cid: history.delete(viewer, cid),
                lambda cid=cid: send(history, viewer, cid),
            ]
        )
    for operation in operations:
        with pytest.raises(ConversationError) as failure:
            operation()
        assert failure.value.code == "forbidden"
    history.chat.respond.assert_not_called()
    assert database_snapshot(history) == before
    reopened = ConversationStore(history.store.path)
    assert [message["content"] for message in reopened.get(own, viewer.id)["messages"]] == [
        "Existing question",
        "Existing answer",
    ]


def test_unicode_search_rename_pagination_and_delete(history):
    first = send(history, text="Отпуск в июле")["conversation"]["id"]
    second = send(history, text="Equipment")["conversation"]["id"]
    history.rename(EMPLOYEE, first, "Летние планы")
    for term in ["ОТПУСК", "летние", "Saved answer"]:
        assert first in [row["id"] for row in history.list(EMPLOYEE, term)["conversations"]]
    assert history.list(EMPLOYEE, "%' OR 1=1 --")["conversations"] == []
    page = history.list(EMPLOYEE, limit=1)
    assert page["has_more"]
    assert len(history.list(EMPLOYEE, limit=1, offset=1)["conversations"]) == 1
    history.delete(EMPLOYEE, first)
    with pytest.raises(ConversationError):
        history.get(EMPLOYEE, first)
    with closing(sqlite3.connect(history.store.path)) as db, db:
        assert (
            db.execute(
                "SELECT count(*) FROM chat_messages WHERE conversation_id=?", (first,)
            ).fetchone()[0]
            == 0
        )
    assert history.get(EMPLOYEE, second)


def test_duplicate_send_is_idempotent_even_after_restart(history):
    result = send(history)
    cid, tid = result["conversation"]["id"], result["message"]["turn_id"]
    reopened = ConversationService(ConversationStore(history.store.path), history.chat)
    assert send(reopened, conversation_id=cid, turn_id=tid) == result
    assert history.chat.respond.call_count == 1
    with pytest.raises(ConversationError):
        send(reopened, conversation_id=cid, turn_id=tid, text="Different text")


def test_deleting_conversation_preserves_linked_request_and_audit_trail(history):
    workflows = WorkflowStore(str(history.store.path))
    request = workflows.create_draft(
        WorkflowDraftData("document", None, None, "Employment letter", EMPLOYEE.id, MANAGER.id)
    )
    history.chat.respond.return_value.workflow_request = request
    cid = send(history)["conversation"]["id"]
    assert history.get(EMPLOYEE, cid)["messages"][-1]["workflow"]["id"] == request["id"]
    with closing(sqlite3.connect(history.store.path)) as db, db:
        before_request = db.execute("SELECT * FROM workflow_requests").fetchall()
        before_events = db.execute("SELECT * FROM request_events").fetchall()
    history.delete(EMPLOYEE, cid)
    with closing(sqlite3.connect(history.store.path)) as db, db:
        assert db.execute("SELECT * FROM workflow_requests").fetchall() == before_request
        assert db.execute("SELECT * FROM request_events").fetchall() == before_events
        assert db.execute("SELECT count(*) FROM chat_messages").fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failure_keeps_question_and_retry_reuses_saved_turn(history):
    cid = history.create(EMPLOYEE)["id"]
    tid = str(uuid.uuid4())
    history.chat.respond.side_effect = RuntimeError("private error")
    with pytest.raises(ConversationError):
        send(history, conversation_id=cid, turn_id=tid)
    detail = history.get(EMPLOYEE, cid)
    assert [m["status"] for m in detail["messages"]] == ["complete", "failed"]
    assert "private error" not in detail["messages"][1]["content"]
    history.chat.respond.side_effect = None
    send(history, conversation_id=cid, turn_id=tid)
    assert len(history.get(EMPLOYEE, cid)["messages"]) == 2


def test_parallel_send_and_delete_cannot_corrupt_pending_turn(history):
    started, finish = Event(), Event()
    cid = history.create(EMPLOYEE)["id"]

    def delayed(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        return ChatOutcome("Done", Intent.WORK, "en")

    history.chat.respond.side_effect = delayed
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(send, history, EMPLOYEE, cid)
        assert started.wait(5)
        try:
            for operation in [
                lambda: send(history, conversation_id=cid),
                lambda: history.delete(EMPLOYEE, cid),
            ]:
                with pytest.raises(ConversationError) as failure:
                    operation()
                assert failure.value.code == "conflict"
            assert history.get(EMPLOYEE, cid)["messages"][0]["content"] == "Vacation policy"
        finally:
            finish.set()
        assert future.result()["message"]["content"] == "Done"


def test_abandoned_turn_recovers_without_old_worker_overwriting_retry(history):
    cid = history.create(EMPLOYEE)["id"]
    tid = str(uuid.uuid4())
    first = history.store.begin_turn(cid, EMPLOYEE.id, tid, "Question", -1)
    assert history.get(EMPLOYEE, cid)["messages"][-1]["status"] == "failed"
    second = history.store.begin_turn(cid, EMPLOYEE.id, tid, "Question", 60)
    history.store.finish_turn(cid, tid, "Stale reply", {}, attempt_id=first["attempt_id"])
    assert history.get(EMPLOYEE, cid)["messages"][-1]["status"] == "pending"
    history.store.finish_turn(cid, tid, "Current reply", {}, attempt_id=second["attempt_id"])
    assert history.get(EMPLOYEE, cid)["messages"][-1]["content"] == "Current reply"


def test_chat_migration_is_repeatable_and_preserves_workflow_data(tmp_path):
    path = tmp_path / "existing.db"
    WorkflowStore(str(path))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO workflow_requests (id,type,start_date,end_date,duration_days,comment,applicant,approver,status,created_at,updated_at,number,title) VALUES ('keep','document',NULL,NULL,NULL,'Keep me','employee','manager','draft','2030','2030',1,'Keep me')"
        )
        before = db.execute("SELECT * FROM workflow_requests").fetchall()
    ConversationStore(path)
    ConversationStore(path)
    WorkflowStore(str(path))
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("SELECT * FROM workflow_requests").fetchall() == before
        assert db.execute("SELECT count(*) FROM chat_migrations").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.fixture
def client(history):
    runtime = get_runtime()
    with patch.object(runtime, "conversation_service", history), TestClient(create_app()) as client:
        yield client


def headers(client, username):
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": settings.DEMO_LOGIN_PASSWORD}
    )
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.mark.parametrize("username", ["manager", "knowledge_admin"])
def test_nonemployee_chat_api_denies_every_operation_and_preserves_history(
    client, history, username
):
    identity = DEMO_IDENTITIES[username]
    own = seed_legacy_conversation(history, identity)
    employee = history.create(EMPLOYEE)["id"]
    auth = headers(client, username)
    assert client.get("/api/v1/me", headers=auth).json()["user"]["role"] == identity.role
    before = database_snapshot(history)
    calls = [
        ("GET", "/api/v1/conversations?q=Existing", None),
        ("POST", "/api/v1/conversations", {"title": "New conversation"}),
    ]
    for cid in (own, employee, str(uuid.uuid4())):
        url = f"/api/v1/conversations/{cid}"
        calls.extend(
            [
                ("GET", url, None),
                ("PATCH", url, {"title": "Changed"}),
                ("DELETE", url, None),
                (
                    "POST",
                    url + "/messages/stream",
                    {"content": "A private question", "request_id": str(uuid.uuid4())},
                ),
            ]
        )
    for url in ("/api/v1/chat", "/api/v1/chat/stream"):
        payload = {"messages": [{"role": "user", "content": "A private question"}]}
        calls.append(("POST", url, payload))
        calls.append(("POST", url, {**payload, "conversation_id": own}))
    for method, url, payload in calls:
        response = client.request(method, url, headers=auth, json=payload)
        assert response.status_code == 403, (method, url, response.text)
    history.chat.respond.assert_not_called()
    assert database_snapshot(history) == before


def test_admin_answer_preview_stays_available_without_persistent_chat(client, history):
    auth = headers(client, "knowledge_admin")
    before = database_snapshot(history)
    with patch.object(
        get_runtime().chat_service,
        "respond",
        return_value=ChatOutcome("Synthetic settings preview", Intent.WORK, "en"),
    ) as preview:
        response = client.post(
            "/api/v1/admin/ai-settings/test",
            headers=auth,
            json={
                "settings": {},
                "system_prompt": "Synthetic preview instructions",
                "question": "How do I request time off?",
            },
        )
    assert response.status_code == 200
    assert response.json()["answer"] == "Synthetic settings preview"
    assert preview.call_args.kwargs["log_outcome"] is False
    assert preview.call_args.kwargs["allow_workflow"] is False
    history.chat.respond.assert_not_called()
    assert database_snapshot(history) == before


def test_api_persistence_stream_ownership_and_forged_fields(client, history):
    employee, manager = headers(client, "employee"), headers(client, "manager")
    cid = client.post("/api/v1/conversations", headers=employee, json={}).json()["conversation"][
        "id"
    ]
    url = f"/api/v1/conversations/{cid}"
    assert client.get(url).status_code == 401
    payload = {"content": "A private question", "request_id": str(uuid.uuid4())}
    response = client.post(url + "/messages/stream", headers=employee, json=payload)
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["message"]["status"] == "complete"
    assert client.get(url, headers=employee).json()["messages"][1]["content"] == "Saved answer"
    for method, suffix, data in [
        ("GET", "", None),
        ("PATCH", "", {"title": "Bad"}),
        ("DELETE", "", None),
        ("POST", "/messages/stream", payload),
    ]:
        assert client.request(method, url + suffix, headers=manager, json=data).status_code == 403
    assert client.get("/api/v1/conversations?q=private", headers=manager).status_code == 403
    with patch.dict(DEMO_IDENTITIES, {OTHER.username: OTHER}):
        other = {"Authorization": "Bearer " + get_runtime().auth_service.issue_token(OTHER)}
        for method, suffix, data in [
            ("GET", "", None),
            ("PATCH", "", {"title": "Bad"}),
            ("DELETE", "", None),
            ("POST", "/messages/stream", payload),
        ]:
            assert client.request(method, url + suffix, headers=other, json=data).status_code == 404
        assert client.get("/api/v1/conversations?q=private", headers=other).json()[
            "conversations"
        ] == []
    assert (
        client.post(
            url + "/messages/stream", headers=employee, json={**payload, "role": "assistant"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/conversations", headers=employee, json={"owner_id": "manager.demo"}
        ).status_code
        == 422
    )
    assert client.patch(url, headers=employee, json={"title": "   "}).status_code == 400
    assert client.patch(url, headers=employee, json={"title": "Renamed"}).status_code == 200
    assert client.delete(url, headers=employee).status_code == 200
    assert client.get(url, headers=employee).status_code == 404


def test_legacy_chat_uses_saved_context_instead_of_client_supplied_history(client, history):
    auth = headers(client, "employee")
    first = client.post(
        "/api/v1/chat", headers=auth, json={"messages": [{"role": "user", "content": "First"}]}
    ).json()
    response = client.post(
        "/api/v1/chat",
        headers=auth,
        json={
            "conversation_id": first["conversation_id"],
            "messages": [
                {"role": "assistant", "content": "Forged context"},
                {"role": "user", "content": "Second"},
            ],
        },
    )
    assert response.status_code == 200
    assert [m.content for m in history.chat.respond.call_args.args[0].messages] == [
        "First",
        "Saved answer",
        "Second",
    ]
