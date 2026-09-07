"""Durable inbox tests using installed Bolt, real SQLite, and fake remote services."""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from slack_bolt.adapter.socket_mode.internals import run_bolt_app, send_response
from slack_bolt.request import BoltRequest
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.web.slack_response import SlackResponse

from peopleflow_slack import __main__ as startup
from peopleflow_slack.application import EmployeeApp
from peopleflow_slack.client import APIError, PeopleFlowClient
from peopleflow_slack.config import Settings
from peopleflow_slack.handlers import create_bolt_app
from peopleflow_slack.inbox import normalize_action, recover_inbox
from peopleflow_slack.store import Store

TEAM, USER, CHANNEL = "TINBOX", "UINBOX", "DINBOX"
REQUEST = {
    "id": "request-1",
    "type": "pto",
    "type_label": "PTO",
    "status": "in_review",
    "comment": "Cover arranged",
    "details": {},
    "validation_errors": [],
}


@pytest.fixture
def tmp_path():
    root = Path(__file__).resolve().parents[1] / "work"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="inbox-tests-", dir=root) as directory:
        result = Path(directory).resolve()
        assert result.is_relative_to(root.resolve())
        yield result


def message(**overrides):
    return {
        "type": "event_callback",
        "team_id": TEAM,
        "api_app_id": "AINBOX",
        "event_id": "event-1",
        "event": {
            "type": "message",
            "channel_type": "im",
            "user": USER,
            "channel": CHANNEL,
            "ts": "100.1",
            "text": "Question",
        },
        **overrides,
    }


def action(kind, value="request-1", nonce="100.2"):
    return {
        "type": "block_actions",
        "team": {"id": TEAM},
        "user": {"id": USER},
        "api_app_id": "AINBOX",
        "trigger_id": "unused-trigger",
        "actions": [{"type": "button", "action_id": kind, "value": value, "action_ts": nonce}],
    }


def submission(callback, *, view_id="V1", metadata=None, fields=None):
    return {
        "type": "view_submission",
        "team": {"id": TEAM},
        "user": {"id": USER},
        "api_app_id": "AINBOX",
        "trigger_id": "unused-trigger",
        "view": {
            "id": view_id,
            "type": "modal",
            "callback_id": callback,
            "private_metadata": json.dumps(metadata or {}),
            "state": {"values": fields or {}},
        },
    }


def text_field(value):
    return {"value": {"type": "plain_text_input", "value": value}}


def request_submission():
    return submission(
        "request_submit",
        metadata={"request_type": "pto"},
        fields={
            "start_date": {"value": {"selected_date": "2030-04-01"}},
            "end_date": {"value": {"selected_date": "2030-04-03"}},
            "comment": text_field("Cover arranged"),
        },
    )


@pytest.fixture
def systems(tmp_path, monkeypatch):
    created = []

    def auth_transport(api_method, **kwargs):
        assert api_method == "auth.test", "Tests must never call Slack's network transport"
        return SlackResponse(
            client=None,
            http_verb="POST",
            api_url="https://slack.invalid/api/auth.test",
            req_args={},
            data={"ok": True, "team_id": TEAM, "user_id": "UBOT", "bot_id": "BBOT"},
            headers={},
            status_code=200,
        )

    monkeypatch.setattr(WebClient, "api_call", Mock(side_effect=auth_transport))

    def create(*, path=None, capture=True, settings=None):
        settings = settings or Settings(
            bot_token="xoxb-test",
            app_token="xapp-test",
            employee_user_id=USER,
            team_id=TEAM,
            state_path=path or tmp_path / f"state-{len(created)}.db",
        )
        slack = WebClient(token="xoxb-test", retry_handlers=[])
        for name, result in {
            "conversations_open": {"channel": {"id": CHANNEL}},
            "chat_postMessage": {"channel": CHANNEL, "ts": "200.1"},
            "chat_update": {"ok": True},
            "views_publish": {"ok": True},
            "views_update": {"ok": True},
            "views_open": {"view": {"id": "V1"}},
        }.items():
            setattr(slack, name, Mock(return_value=result))
        api = Mock(spec=PeopleFlowClient)
        api.requests.return_value = []
        api.conversations.return_value = []
        api.conversation.return_value = {
            "conversation": {"id": "conversation-1", "title": "Q"},
            "messages": [],
        }
        api.create_request.return_value = {**REQUEST, "status": "draft"}
        api.submit_request.return_value = {"request": REQUEST}
        api.stream_chat.side_effect = lambda *args: iter(
            [
                {"type": "start"},
                {"type": "token", "content": "Answer"},
                {
                    "type": "complete",
                    "conversation_id": "conversation-1",
                    "sources": [],
                    "workflow_request": None,
                },
            ]
        )
        store = Store(settings.state_path)
        service = EmployeeApp(settings, api, store, slack)
        app = create_bolt_app(service, verify=False)
        done, errors, jobs = Event(), [], []
        app.listener_runner.listener_completion_handler = SimpleNamespace(
            handle=lambda **_: done.set()
        )

        @app.error
        def error_handler(error):
            errors.append(error)

        if capture:
            service.queue = lambda function, *args: jobs.append((function, args))
        result = SimpleNamespace(
            service=service,
            store=store,
            settings=settings,
            api=api,
            slack=slack,
            app=app,
            jobs=jobs,
            done=done,
            errors=errors,
        )
        created.append(result)
        return result

    yield create
    for system in created:
        system.app.listener_runner.listener_executor.shutdown(wait=True)
        system.service.close()


def dispatch(system, body):
    system.done.clear()
    response = system.app.dispatch(BoltRequest(body=copy.deepcopy(body), mode="socket_mode"))
    assert response.status == 200
    assert system.done.wait(2), "Listener must finish after its early ACK"
    assert not system.errors
    return json.loads(response.body) if response.body else {}


def run_jobs(system):
    while system.jobs:
        function, args = system.jobs.pop(0)
        function(*args)


def persist(system, body):
    item = normalize_action(body, system.service)
    assert item is not None
    system.store.receive_inbox(item.receipt_id, item.operation_id, item.kind, item.payload)
    return item


@pytest.mark.parametrize(
    ("body", "receipt_id", "kind"),
    [
        (message(), "event-1", "ask"),
        (request_submission(), "submit:V1", "submit_request"),
        (
            submission("question_submit", fields={"question": text_field("Question")}),
            "question:V1",
            "ask_new",
        ),
        (
            submission(
                "feedback_submit",
                metadata={"answer_id": "answer-1"},
                fields={"comment": text_field("More detail")},
            ),
            "feedback-view:V1",
            "rate",
        ),
        (action("feedback_helpful", "answer-1"), "action:feedback_helpful:100.2", "rate"),
        (action("cancel_request"), "action:cancel_request:100.2", "cancel"),
        (
            action("delete_conversation", "conversation-1"),
            "action:delete_conversation:100.2",
            "delete",
        ),
        (
            {
                "command": "/peopleflow",
                "team_id": TEAM,
                "user_id": USER,
                "trigger_id": "command-1",
                "text": "Question",
            },
            "command:command-1",
            "ask_new",
        ),
    ],
)
def test_real_bolt_ack_has_a_committed_receipt_before_worker_runs(systems, body, receipt_id, kind):
    system = systems()
    response = dispatch(system, body)
    # A new Store/connection can already read the committed receipt at ACK time.
    row = Store(system.settings.state_path).inbox_item(receipt_id)
    assert row["kind"] == kind and row["state"] == "pending"
    assert system.store.operation(row["operation_id"]) is None
    assert len(system.jobs) == 1
    assert not system.api.mock_calls
    if kind == "submit_request":
        assert response["response_action"] == "update"


def test_socket_mode_auto_ack_follows_sqlite_commit(systems):
    system = systems()
    envelope = SocketModeRequest(type="events_api", envelope_id="envelope-1", payload=message())
    response = run_bolt_app(system.app, envelope)
    sent = []

    def send(value):
        assert Store(system.settings.state_path).inbox_item("event-1")["state"] == "pending"
        sent.append(value)

    socket = SimpleNamespace(
        logger=logging.getLogger("test-inbox-socket"), send_socket_mode_response=send
    )
    send_response(socket, envelope, response, 0)
    assert len(sent) == 1
    assert system.done.wait(2)
    assert not system.api.mock_calls


def test_write_failure_never_acks_or_starts_a_listener(systems, monkeypatch, caplog):
    system = systems()
    monkeypatch.setattr(
        system.store,
        "receive_inbox",
        Mock(side_effect=sqlite3.OperationalError("private-body-secret")),
    )
    envelope = SocketModeRequest(type="events_api", envelope_id="envelope-1", payload=message())
    response = run_bolt_app(system.app, envelope)
    socket = SimpleNamespace(
        logger=logging.getLogger("test-inbox-socket"), send_socket_mode_response=Mock()
    )
    send_response(socket, envelope, response, 0)
    assert response.status == 503
    socket.send_socket_mode_response.assert_not_called()
    assert not system.jobs and not system.done.is_set()
    assert "private-body-secret" not in caplog.text


def test_normalization_drops_transport_secrets_and_unneeded_view_data(systems):
    system = systems()
    body = request_submission()
    body.update(
        token="TOKEN_SECRET",
        response_url="RESPONSE_URL_SECRET",
        authorizations=[{"token": "AUTH_SECRET"}],
    )
    body["trigger_id"] = "TRIGGER_SECRET"
    body["view"]["blocks"] = [{"text": "UNNEEDED_BLOCK"}]
    body["view"]["private_metadata"] = json.dumps(
        {"request_type": "pto", "token": "METADATA_SECRET"}
    )
    dispatch(system, body)
    row = system.store.inbox_item("submit:V1")
    serialized = json.dumps(row)
    for marker in (
        "TOKEN_SECRET",
        "RESPONSE_URL_SECRET",
        "AUTH_SECRET",
        "TRIGGER_SECRET",
        "UNNEEDED_BLOCK",
        "METADATA_SECRET",
    ):
        assert marker not in serialized
    assert set(row["payload"]) == {"team_id", "user_id", "view_id", "fields", "draft_id"}
    run_jobs(system)
    assert system.store.inbox_item("submit:V1")["payload"] == {}


@pytest.mark.parametrize(
    "overrides",
    [
        {"team_id": "TOTHER"},
        {"event": {**message()["event"], "user": "UOTHER"}},
        {"event": {**message()["event"], "bot_id": "BBOT"}},
        {"event": {**message()["event"], "subtype": "message_changed"}},
        {"event": {**message()["event"], "channel_type": "channel"}},
        {"event": {**message()["event"], "text": "  "}},
    ],
)
def test_ignored_or_unscoped_events_have_no_inbox_record(systems, overrides):
    system = systems()
    assert normalize_action(message(**overrides), system.service) is None


@pytest.mark.parametrize(
    "body",
    [
        submission("request_submit", metadata={"request_type": "pto"}),
        submission("question_submit", fields={"question": text_field("  ")}),
    ],
)
def test_invalid_forms_remain_editable_without_queued_work(systems, body):
    system = systems()
    result = dispatch(system, body)
    assert result["response_action"] == "errors"
    assert not system.jobs
    with system.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0


def test_repeated_deliveries_do_not_overwrite_or_repeat_completed_action(systems):
    system = systems()
    dispatch(system, message())
    dispatch(system, message())
    run_jobs(system)
    assert system.api.stream_chat.call_count == 1
    assert system.store.inbox_item("event-1")["state"] == "done"
    dispatch(system, message())
    run_jobs(system)
    assert system.api.stream_chat.call_count == 1


def test_changed_pending_delivery_cannot_replace_the_accepted_action(systems):
    system = systems()
    dispatch(system, message())
    changed = message(event={**message()["event"], "text": "Changed content"})
    response = system.app.dispatch(BoltRequest(body=changed, mode="socket_mode"))
    assert response.status == 400
    assert len(system.jobs) == 1
    assert system.store.inbox_item("event-1")["payload"]["text"] == "Question"
    run_jobs(system)
    system.api.stream_chat.assert_called_once_with("Question", None)


@pytest.mark.parametrize("changed", ["operation", "kind"])
def test_receipt_identity_cannot_be_reused_for_another_mutation(systems, changed):
    system = systems()
    item = persist(system, message())
    with pytest.raises(ValueError, match="original delivery"):
        system.store.receive_inbox(
            item.receipt_id,
            "other-operation" if changed == "operation" else item.operation_id,
            "submit_request" if changed == "kind" else item.kind,
            item.payload,
        )
    assert system.store.inbox_item(item.receipt_id)["operation_id"] == item.operation_id


def test_corrupt_draft_metadata_cannot_turn_submission_into_a_new_request(systems):
    system = systems()
    body = request_submission()
    body["view"]["private_metadata"] = '{"draft_id":'
    response = system.app.dispatch(BoltRequest(body=body, mode="socket_mode"))
    assert response.status == 400
    assert not system.jobs
    assert system.store.inbox_item("submit:V1") is None


def test_restart_replays_acked_work_that_never_started(systems):
    original = systems()
    dispatch(original, message())
    assert original.store.operation("event-1") is None
    restarted = systems(path=original.settings.state_path, capture=False)
    recover_inbox(restarted.service)
    restarted.api.stream_chat.assert_called_once_with("Question", None)
    assert restarted.store.operation("event-1")["state"] == "complete"
    assert restarted.store.inbox_item("event-1")["state"] == "done"
    recover_inbox(restarted.service)
    assert restarted.api.stream_chat.call_count == 1


def test_recovery_preserves_acceptance_order_and_continuation_context(systems):
    original = systems()
    persist(original, message())
    persist(
        original,
        submission(
            "question_submit",
            fields={"question": text_field("Next")},
            metadata={"conversation_id": "conversation-1"},
        ),
    )
    restarted = systems(path=original.settings.state_path, capture=False)
    recover_inbox(restarted.service)
    assert restarted.api.stream_chat.call_args_list[0].args == ("Question", None)
    assert restarted.api.stream_chat.call_args_list[1].args == ("Next", "conversation-1")
    restarted.slack.views_open.assert_not_called()


@pytest.mark.parametrize(
    "kind,action_id,resource_id",
    [
        ("cancel", "cancel_request", "request-1"),
        ("delete", "delete_conversation", "conversation-1"),
    ],
)
@pytest.mark.parametrize("view_type", ["modal", "home", None])
def test_cancel_delete_replay_preserves_only_modal_view_id(
    systems, kind, action_id, resource_id, view_type
):
    original = systems()
    body = action(action_id, resource_id)
    if view_type:
        body["view"] = {"type": view_type, "id": "VDETAIL"}
    dispatch(original, body)
    receipt_id = f"action:{action_id}:100.2"
    expected_view_id = "VDETAIL" if view_type == "modal" else None
    assert original.store.inbox_item(receipt_id)["payload"]["view_id"] == expected_view_id
    assert original.jobs[0][1] == (resource_id, receipt_id, expected_view_id)

    restarted = systems(path=original.settings.state_path, capture=False)
    restarted.api.request.return_value = {
        "request": {**REQUEST, "status": "cancelled"},
        "events": [],
        "comments": [],
    }
    method = Mock(wraps=getattr(restarted.service, kind))
    setattr(restarted.service, kind, method)
    recover_inbox(restarted.service)
    method.assert_called_once_with(resource_id, receipt_id, expected_view_id)
    assert restarted.store.inbox_item(receipt_id)["state"] == "done"
    if expected_view_id:
        assert restarted.slack.views_update.call_args.kwargs["view_id"] == expected_view_id
    else:
        restarted.slack.views_update.assert_not_called()


@pytest.mark.parametrize(
    "kind,action_id,resource_id",
    [
        ("cancel", "cancel_request", "request-1"),
        ("delete", "delete_conversation", "conversation-1"),
    ],
)
def test_cancel_delete_legacy_receipts_default_missing_view_id_to_none(
    systems, kind, action_id, resource_id
):
    original = systems()
    item = persist(original, action(action_id, resource_id))
    legacy_payload = {key: value for key, value in item.payload.items() if key != "view_id"}
    with original.store.connection() as db:
        db.execute(
            "UPDATE inbox SET payload=? WHERE id=?", (json.dumps(legacy_payload), item.receipt_id)
        )
    restarted = systems(path=original.settings.state_path, capture=False)
    method = Mock(wraps=getattr(restarted.service, kind))
    setattr(restarted.service, kind, method)
    recover_inbox(restarted.service)
    method.assert_called_once_with(resource_id, item.operation_id, None)
    assert restarted.store.inbox_item(item.receipt_id)["state"] == "done"
    restarted.slack.views_update.assert_not_called()


@pytest.mark.parametrize("state", ["started", "draft_created", "complete", "failed", "uncertain"])
def test_restart_never_repeats_started_or_terminal_operations(systems, state):
    original = systems()
    item = persist(original, request_submission())
    original.store.claim(item.operation_id)
    if state != "started":
        original.store.finish(item.operation_id, state, {"request_id": "request-1"})
    restarted = systems(path=original.settings.state_path, capture=False)
    recover_inbox(restarted.service)
    restarted.api.create_request.assert_not_called()
    restarted.api.submit_request.assert_not_called()
    expected = "uncertain" if state in {"started", "draft_created", "uncertain"} else state
    assert restarted.store.operation(item.operation_id)["state"] == expected
    if state == "draft_created":
        assert restarted.store.operation(item.operation_id)["payload"] == {
            "request_id": "request-1"
        }
    assert restarted.store.inbox_item(item.receipt_id)["payload"] == {}


def test_recovery_reconciles_legacy_operations_without_inbox(systems):
    system = systems(capture=False)
    system.store.claim("legacy-event")
    recover_inbox(system.service)
    assert system.store.operation("legacy-event")["state"] == "uncertain"
    assert not system.api.mock_calls


def test_successful_replay_survives_expired_slack_modal(systems):
    original = systems()
    persist(original, request_submission())
    restarted = systems(path=original.settings.state_path, capture=False)
    restarted.slack.views_update.side_effect = SlackApiError(
        "view gone", {"error": "view_not_found"}
    )
    recover_inbox(restarted.service)
    assert restarted.api.create_request.call_count == 1
    assert restarted.api.submit_request.call_count == 1
    assert restarted.store.inbox_item("submit:V1")["state"] == "done"
    recover_inbox(restarted.service)
    assert restarted.api.create_request.call_count == 1


def test_replay_transport_failure_becomes_uncertain_without_blind_repeat(systems):
    original = systems()
    persist(original, message())
    restarted = systems(path=original.settings.state_path, capture=False)
    restarted.slack.chat_postMessage.side_effect = ConnectionError("temporary failure")
    recover_inbox(restarted.service)
    assert restarted.store.inbox_item("event-1")["state"] == "uncertain"
    restarted.slack.chat_postMessage.side_effect = None
    recover_inbox(restarted.service)
    assert restarted.slack.chat_postMessage.call_count == 1
    restarted.api.stream_chat.assert_not_called()


@pytest.mark.parametrize("legacy", [False, True])
def test_recovery_keeps_the_accepted_question_surface(systems, legacy):
    original = systems()
    item = persist(original, message())
    assert item.payload["new_message"] is True
    if legacy:
        payload = {key: value for key, value in item.payload.items() if key != "new_message"}
        with original.store.connection() as db:
            db.execute(
                "UPDATE inbox SET payload=? WHERE id=?", (json.dumps(payload), item.receipt_id)
            )
    restarted = systems(path=original.settings.state_path, capture=False)
    recover_inbox(restarted.service)
    posted = restarted.slack.chat_postMessage.call_args.kwargs
    assert ("thread_ts" in posted) is legacy
    if legacy:
        assert posted["thread_ts"] == item.payload["thread_ts"]
    restarted.api.stream_chat.assert_called_once()
    assert restarted.store.inbox_item(item.receipt_id)["state"] == "done"
    recover_inbox(restarted.service)
    restarted.api.stream_chat.assert_called_once()


def test_uncertain_api_timeout_is_never_replayed(systems):
    original = systems()
    persist(original, request_submission())
    restarted = systems(path=original.settings.state_path, capture=False)
    restarted.api.create_request.side_effect = APIError(504, "Timeout", uncertain=True)
    recover_inbox(restarted.service)
    assert restarted.store.operation("submit:V1")["state"] == "uncertain"
    recover_inbox(restarted.service)
    assert restarted.api.create_request.call_count == 1


def test_feedback_allows_new_click_after_safe_failure_but_not_redelivery(systems):
    system = systems()
    system.store.save_answer(
        {"question": "Q", "answer": "A", "channel": CHANNEL, "thread_ts": "100.1"}, "answer-1"
    )
    system.api.feedback.side_effect = [APIError(503, "Not connected"), {"feedback": {"id": "f1"}}]
    body = action("feedback_helpful", "answer-1")
    dispatch(system, body)
    run_jobs(system)
    assert system.store.operation("feedback:answer-1")["state"] == "failed"
    dispatch(system, body)
    run_jobs(system)
    assert system.api.feedback.call_count == 1
    dispatch(system, action("feedback_helpful", "answer-1", "100.3"))
    run_jobs(system)
    assert system.api.feedback.call_count == 2


def test_new_feedback_after_uncertain_attempt_is_also_blocked(systems):
    system = systems()
    first = persist(system, action("feedback_helpful", "answer-1"))
    system.store.claim(first.operation_id)
    system.store.finish(first.operation_id, "uncertain")
    second = persist(system, action("feedback_helpful", "answer-1", "100.3"))
    assert system.store.inbox_item(second.receipt_id)["state"] == "uncertain"
    assert not system.store.claim(first.operation_id, retry_failed=True)


def test_new_safe_feedback_retry_is_recoverable_before_its_worker_starts(systems):
    original = systems()
    original.store.save_answer(
        {"question": "Q", "answer": "A", "channel": CHANNEL, "thread_ts": "100.1"}, "answer-1"
    )
    first = persist(original, action("feedback_helpful", "answer-1"))
    original.store.claim(first.operation_id)
    original.store.finish(first.operation_id, "failed")
    second = persist(original, action("feedback_helpful", "answer-1", "100.3"))
    restarted = systems(path=original.settings.state_path, capture=False)
    recover_inbox(restarted.service)
    restarted.api.feedback.assert_called_once_with("Q", "A", 5, "")
    assert restarted.store.inbox_item(second.receipt_id)["state"] == "done"


@pytest.mark.parametrize(
    "corruption", ["wrong_scope", "unknown_kind", "invalid_json", "wrong_shape"]
)
def test_malformed_or_wrong_installation_receipt_is_not_executed(systems, corruption):
    original = systems()
    item = persist(original, message())
    with original.store.connection() as db:
        if corruption == "unknown_kind":
            db.execute("UPDATE inbox SET kind='close'")
        else:
            payload = {**item.payload, "user_id": "UOTHER"} if corruption == "wrong_scope" else []
            db.execute(
                "UPDATE inbox SET payload=?",
                ("not json" if corruption == "invalid_json" else json.dumps(payload),),
            )
    restarted = systems(path=original.settings.state_path, capture=False)
    recover_inbox(restarted.service)
    assert not restarted.api.mock_calls
    assert restarted.store.inbox_item(item.receipt_id)["state"] == "uncertain"


def test_schema_upgrade_preserves_existing_transport_state(tmp_path):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as db:
        with db:
            db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute("INSERT INTO metadata VALUES ('dm','\"DINBOX\"')")
    store = Store(path)
    assert store.get("dm") == CHANNEL
    assert store.recover_inbox() == []


def test_concurrent_receipt_delivery_is_inserted_only_once(systems):
    system = systems()
    item = normalize_action(message(), system.service)
    gate = Barrier(6)

    def receive(_):
        gate.wait(timeout=3)
        return system.store.receive_inbox(
            item.receipt_id, item.operation_id, item.kind, item.payload
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(receive, range(6))) == 1
    assert len(system.store.recover_inbox()) == 1


def test_startup_recovery_precedes_socket_creation_and_polling(systems, monkeypatch):
    system = systems()
    events = []
    system.api.me.return_value = {
        "user": {"role": "employee"},
        "backend_id": "235d880c-7a1d-4315-8d60-f18d1c2da720",
    }
    monkeypatch.setattr(startup, "PeopleFlowClient", lambda *args: system.api)
    monkeypatch.setattr(startup, "WebClient", lambda **kwargs: system.slack)
    monkeypatch.setattr(system.slack, "auth_test", lambda: {"team_id": TEAM, "user_id": "UBOT"})
    monkeypatch.setattr(startup, "Store", lambda path: system.store)
    monkeypatch.setattr(startup, "EmployeeApp", lambda *args: system.service)
    monkeypatch.setattr(system.service, "poll_once", lambda: events.append("baseline"))
    monkeypatch.setattr(startup, "recover_inbox", lambda service: events.append("recover"))
    monkeypatch.setattr(startup, "create_bolt_app", lambda service: system.app)
    monkeypatch.setattr(system.service, "start_polling", lambda: events.append("polling"))

    def socket(*args):
        events.append("socket")
        return SimpleNamespace(start=lambda: events.append("start"), close=lambda: None)

    monkeypatch.setattr(startup, "SocketModeHandler", socket)
    with ExitStack() as stack:
        startup.run(system.settings, False, stack)
    assert events == ["baseline", "recover", "socket", "polling", "start"]
