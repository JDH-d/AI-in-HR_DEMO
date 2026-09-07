"""Real Socket Mode Bolt dispatch with isolated API/Slack fakes and SQLite state.

No handler is invoked directly. A completion event joins Bolt's listener so an
early ack cannot hide a post-ack exception. Most tests capture background jobs
and run them explicitly; the latency test uses the real EmployeeApp worker and
a blocked API call. No tokens, external services, or backend imports are needed.
"""

from __future__ import annotations

import copy
import itertools
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from slack_bolt.request import BoltRequest
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse

from peopleflow_slack import views
from peopleflow_slack.application import EmployeeApp
from peopleflow_slack.client import APIError, PeopleFlowClient
from peopleflow_slack.config import Settings
from peopleflow_slack.forms import field_value, request_payload
from peopleflow_slack.handlers import create_bolt_app
from peopleflow_slack.process_lock import ProcessLock
from peopleflow_slack.store import Store

TEAM = "TDEMO"
USER = "UEMPLOYEE"
VIEW = "VMODAL"
CHANNEL = "DDEMO"
WORKFLOW = {
    "id": "request-1",
    "type": "pto",
    "type_label": "PTO",
    "status": "draft",
    "start_date": "2026-10-05",
    "end_date": "2026-10-07",
    "duration_days": 3,
    "comment": "Handoff to R&D <team>",
    "applicant": "employee.demo",
    "approver": "manager.demo",
    "details": {},
    "validation_errors": [],
}
SOURCE = {
    "source": "vacation.md",
    "title": "Vacation policy",
    "section": "Notice",
    "category": "People",
    "version": "1.2",
    "excerpt": "Plan time off with your manager.",
    "score": 0.9,
}
HISTORY = {
    "conversation": {"id": "conversation-1", "title": "Vacation policy", "message_count": 2},
    "messages": [
        {"id": "user-message-1", "role": "user", "content": "How far in advance?"},
        {
            "id": "answer-message-1",
            "role": "assistant",
            "content": "Discuss timing with your manager.",
            "sources": [SOURCE],
        },
    ],
}


def fields(**values):
    """Slack view.state.values (not a flattened HTTP API payload)."""
    return {name: {"value": value} for name, value in values.items()}


def text(value):
    return {"type": "plain_text_input", "value": value}


def selected(value):
    return {"type": "static_select", "selected_option": None if value is None else {"value": value}}


def checked(value):
    return {"type": "checkboxes", "selected_options": [{"value": "true"}] if value else []}


def chosen_date(value):
    return {"type": "datepicker", "selected_date": value}


def pto_values(**overrides):
    values = fields(
        type=selected("pto"),
        start_date=chosen_date("2026-10-05"),
        end_date=chosen_date("2026-10-07"),
        comment=text(" Handoff to R&D <team> "),
    )
    values.update({name: {"value": value} for name, value in overrides.items()})
    return values


def sick_values(**overrides):
    values = fields(
        type=selected("sick_leave"),
        start_date=chosen_date("2026-10-05"),
        expected_return_date=chosen_date("2026-10-06"),
        expected_return_unknown=checked(False),
        time_away=selected("full_day"),
        partial_hours=text(None),
        comment=text(None),
        extended_or_recurring=checked(False),
    )
    values.update({name: {"value": value} for name, value in overrides.items()})
    return values


def action_body(action_id, value=None, *, view=None, **overrides):
    action = {
        "type": "button",
        "action_id": action_id,
        "block_id": "actions-1",
        "action_ts": "1700000000.001",
    }
    if value is not None:
        action["value"] = value
    body = {
        "type": "block_actions",
        "team": {"id": TEAM},
        "user": {"id": USER},
        "trigger_id": "trigger-1",
        "api_app_id": "ADEMO",
        "actions": [action],
    }
    if view:
        body["view"] = copy.deepcopy(view)
        body["container"] = {"type": "view", "view_id": view["id"]}
    else:
        body["container"] = {"type": "message", "channel_id": CHANNEL, "message_ts": "1.001"}
        body["channel"] = {"id": CHANNEL}
    body.update(overrides)
    return body


def modal(callback="request_submit", metadata=None, values=None, identity=VIEW):
    return {
        "id": identity,
        "type": "modal",
        "hash": "view-hash",
        "callback_id": callback,
        "private_metadata": json.dumps(metadata or {}),
        "state": {"values": values or {}},
    }


def submission(callback, values, metadata=None, **overrides):
    return {
        "type": "view_submission",
        "team": {"id": TEAM},
        "user": {"id": USER},
        "api_app_id": "ADEMO",
        "trigger_id": "submit-trigger",
        "view": modal(callback, metadata, values),
        **overrides,
    }


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def buttons(view, action_id):
    return [
        item
        for item in walk(view)
        if item.get("type") == "button" and item.get("action_id") == action_id
    ]


class Harness:
    def __init__(self, service, app, api, slack_calls):
        self.service, self.app, self.api, self.slack = service, app, api, service.slack
        self.slack_calls = slack_calls
        self.jobs = []
        self.errors = []
        self.completed = Event()
        self.real_queue = service.queue
        service.queue = self.capture
        app.listener_runner.listener_completion_handler = SimpleNamespace(
            handle=lambda **_: self.completed.set()
        )

        @app.error
        def listener_error(error):
            self.errors.append(error)

    def capture(self, function, *args):
        self.jobs.append((function, args))

    def dispatch(self, body):
        self.completed.clear()
        started = time.monotonic()
        response = self.app.dispatch(BoltRequest(body=copy.deepcopy(body), mode="socket_mode"))
        self.ack_seconds = time.monotonic() - started
        assert self.completed.wait(2), "Bolt listener did not finish after ack"
        assert not self.errors, f"Bolt listener raised after/before ack: {self.errors!r}"
        assert response.status == 200, response.body
        return json.loads(response.body) if response.body else {}

    def drain(self):
        while self.jobs:
            function, args = self.jobs.pop(0)
            function(*args)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    # Bolt creates a new WebClient for each request. Mock the class transport too,
    # so auth.test cannot accidentally access the network even with verify=False.
    def transport(api_method, **kwargs):
        assert api_method == "auth.test", f"Unexpected real Slack transport: {api_method}"
        return SlackResponse(
            client=None,
            http_verb="POST",
            api_url="https://slack.invalid/api/auth.test",
            req_args=kwargs,
            data={"ok": True, "team_id": TEAM, "user_id": "UBOT", "bot_id": "BBOT"},
            headers={},
            status_code=200,
        )

    monkeypatch.setattr(WebClient, "api_call", Mock(side_effect=transport))
    slack = WebClient(token="xoxb-test-only", retry_handlers=[])
    slack_calls = Mock()
    timestamp = itertools.count(1)
    methods = {
        "views_open": {"ok": True, "view": {"id": VIEW}},
        "views_push": {"ok": True, "view": {"id": "VSOURCES"}},
        "views_update": {"ok": True, "view": {"id": VIEW}},
        "views_publish": {"ok": True},
        "conversations_open": {"ok": True, "channel": {"id": CHANNEL}},
        "chat_update": {"ok": True},
        "chat_getPermalink": {
            "ok": True,
            "permalink": "https://example.slack.com/archives/DDEMO/p1001",
        },
    }
    for method, result in methods.items():
        stub = Mock(return_value=result)
        monkeypatch.setattr(slack, method, stub)
        slack_calls.attach_mock(stub, method)
    post = Mock(
        side_effect=lambda **kwargs: {
            "ok": True,
            "channel": kwargs["channel"],
            "ts": f"{next(timestamp)}.001",
        }
    )
    monkeypatch.setattr(slack, "chat_postMessage", post)
    slack_calls.attach_mock(post, "chat_postMessage")

    api = Mock(spec=PeopleFlowClient)
    api.requests.return_value = []
    api.conversations.return_value = []
    api.request.side_effect = lambda identity: {
        "request": {**WORKFLOW, "id": identity},
        "events": [],
        "comments": [],
    }
    api.conversation.side_effect = lambda identity: copy.deepcopy(HISTORY)
    api.create_request.return_value = copy.deepcopy(WORKFLOW)
    # The client returns a draft directly from create_request, but the API detail
    # envelope from submit_request (the controller unwraps its 'request' key).
    api.submit_request.return_value = {
        "request": {**WORKFLOW, "status": "in_review"},
        "events": [],
        "comments": [],
    }
    api.stream_chat.return_value = [
        {"type": "token", "content": "A saved answer."},
        {
            "type": "complete",
            "conversation_id": "conversation-1",
            "sources": [SOURCE],
            "workflow_request": None,
        },
    ]
    settings = Settings(
        bot_token="xoxb-test-only",
        app_token="xapp-test-only",
        employee_user_id=USER,
        team_id=TEAM,
        state_path=tmp_path / "state.sqlite",
    )
    service = EmployeeApp(settings, api, Store(settings.state_path), slack)
    app = create_bolt_app(service, verify=False)
    result = Harness(service, app, api, slack_calls)
    yield result
    app.listener_runner.listener_executor.shutdown(wait=True)
    service.close()


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"team": {"id": TEAM}, "user": {"id": USER}}, True),
        ({"team_id": TEAM, "user_id": USER}, True),
        ({"team_id": TEAM, "event": {"user": USER}}, True),
        ({"team": {"id": "TOTHER"}, "user": {"id": USER}}, False),
        ({"team": {"id": TEAM}, "user": {"id": "UOTHER"}}, False),
        ({"team_id": TEAM}, False),
        ({"user_id": USER}, False),
        ({}, False),
    ],
)
def test_allowed_user_team_and_slash_identity(harness, body, expected):
    assert harness.service.allowed(body) is expected


@pytest.mark.parametrize("overrides", [{"team": {"id": "TOTHER"}}, {"user": {"id": "UOTHER"}}])
def test_real_dispatch_blocks_wrong_team_and_employee(harness, overrides):
    harness.dispatch(action_body("new_pto", **overrides))
    assert not harness.jobs
    assert not harness.slack_calls.mock_calls
    assert not harness.api.mock_calls


def test_slash_command_uses_body_user_id(harness):
    body = {
        "command": "/peopleflow",
        "text": "new",
        "team_id": TEAM,
        "user_id": USER,
        "channel_id": CHANNEL,
        "trigger_id": "slash-trigger",
    }
    harness.dispatch(body)
    call = harness.slack.views_open.call_args.kwargs
    assert call["trigger_id"] == "slash-trigger"
    assert call["view"]["callback_id"] == "question_submit"
    assert not harness.jobs and not harness.api.mock_calls


@pytest.mark.parametrize(
    "action_id,section,key",
    [
        ("show_requests", "requests", "edit_request"),
        ("show_conversations", "conversations", "open_conversation"),
    ],
)
def test_home_numeric_pagination_runs_through_bolt(harness, action_id, section, key):
    harness.api.requests.return_value = [{**WORKFLOW, "id": str(index)} for index in range(18)]
    harness.api.conversations.return_value = [
        {"id": str(index), "title": f"Chat {index}"} for index in range(18)
    ]
    first = views.home_view(
        harness.api.requests.return_value, harness.api.conversations.return_value, section
    )
    next_button = next(
        button for button in buttons(first, action_id) if button["text"]["text"] == "Next"
    )
    assert next_button["value"] == "1"
    harness.dispatch(action_body(action_id, next_button["value"]))
    assert harness.jobs == [(harness.service.home, (section, 1))]
    assert not harness.api.mock_calls
    harness.drain()
    rendered = harness.slack.views_publish.call_args.kwargs["view"]
    assert json.loads(rendered["private_metadata"]) == {"section": section, "page": 1}
    if section == "requests":
        select = next(
            element
            for block in rendered["blocks"]
            for element in block.get("elements", [])
            if element.get("action_id") == "select_request"
        )
        assert [option["value"] for option in select["options"]] == [str(i) for i in range(8, 16)]
    else:
        assert [button["value"] for button in buttons(rendered, key)] == [
            str(i) for i in range(8, 16)
        ]


def test_history_sources_push_modal_and_read_cached_api_message(harness):
    harness.dispatch(action_body("open_conversation", "conversation-1"))
    assert harness.jobs == [
        (harness.service.show_detail, (VIEW, "open_conversation", "conversation-1"))
    ]
    harness.drain()
    rendered = harness.slack.views_update.call_args.kwargs["view"]
    source_id = buttons(rendered, "view_sources")[0]["value"]
    cached = harness.service.store.answer(source_id)
    assert cached["sources"] == [SOURCE]
    assert cached["question"] == "How far in advance?"
    assert cached["answer"] == HISTORY["messages"][1]["content"]
    assert cached["conversation_id"] == "conversation-1"
    assert HISTORY["messages"][1]["id"] == "answer-message-1"
    harness.api.reset_mock()
    harness.slack_calls.reset_mock()
    harness.dispatch(action_body("view_sources", source_id, view={**rendered, "id": VIEW}))
    harness.slack.views_push.assert_called_once()
    harness.slack.views_open.assert_not_called()
    assert not harness.api.mock_calls, "Acknowledge and open the modal before backend work."
    harness.drain()
    assert harness.slack.views_update.call_args.kwargs["view"] == views.sources_view([SOURCE])
    harness.api.conversation.assert_called_once_with("conversation-1")


def test_sources_cache_deleted_with_peopleflow_history(harness):
    key = harness.service.store.save_answer(
        {"conversation_id": "conversation-1", "sources": [SOURCE]}
    )
    harness.service.store.forget_conversation("conversation-1")
    harness.dispatch(action_body("view_sources", key, view=modal("conversation_detail")))
    harness.drain()
    rendered = harness.slack.views_update.call_args.kwargs["view"]
    assert rendered["title"]["text"] == "Sources unavailable"
    assert "Vacation policy" not in json.dumps(rendered)
    assert not harness.api.mock_calls


@pytest.mark.parametrize(
    "question", ["sources?", "show sources!", "where is this from", " SOURCE. "]
)
def test_source_command_variants_preserve_the_active_conversation(harness, question):
    harness.service.ask("When can I take leave?", CHANNEL, "100.001", "first", True)
    answer_id = harness.service.store.get("latest_answer:" + CHANNEL)
    harness.service.ask_new(question, "command:sources")

    harness.api.stream_chat.assert_called_once()
    assert harness.service.store.get("active_conversation:" + CHANNEL) == "conversation-1"
    assert harness.service.store.get("latest_answer:" + CHANNEL) == answer_id
    assert harness.slack.chat_postMessage.call_args.kwargs["text"] == "Sources for my last answer"


def test_sources_do_not_restore_a_conversation_deleted_from_the_web(harness):
    harness.service.ask("When can I take leave?", CHANNEL, "100.001", "first", True)
    answer_id = harness.service.store.get("latest_answer:" + CHANNEL)
    harness.api.conversation.side_effect = APIError(404, "Conversation not found.")

    harness.service.ask_new("sources", "command:sources")

    assert harness.service.store.answer(answer_id) is None
    assert harness.service.store.get("active_conversation:" + CHANNEL) is None
    assert "no saved sources" in harness.slack.chat_postMessage.call_args.kwargs["text"]
    harness.api.stream_chat.assert_called_once()


@pytest.mark.parametrize("new_message", [True, False])
def test_conversation_deleted_during_stream_clears_stale_context(harness, new_message):
    harness.service.ask("When can I take leave?", CHANNEL, "100.001", "first", True)
    harness.api.stream_chat.return_value = [
        {"type": "start"},
        {"type": "error", "message": "The conversation could not be found."},
    ]

    harness.service.ask("Please clarify", CHANNEL, "100.001", "second", new_message)

    assert harness.service.store.get("active_conversation:" + CHANNEL) is None
    assert harness.service.store.get("latest_answer:" + CHANNEL) is None
    assert harness.service.store.thread(CHANNEL, "100.001")["deleted"]
    assert "no longer available" in harness.slack.chat_update.call_args.kwargs["text"]
    assert harness.service.store.operation("second")["state"] == "failed"


def test_unconfirmed_stream_error_is_not_mistaken_for_a_retryable_failure(harness):
    harness.api.stream_chat.return_value = [
        {"type": "error", "message": "The conversation could not be saved."}
    ]
    harness.service.ask("Please help", CHANNEL, "100.001", "event-error", True)
    harness.service.ask("Please help", CHANNEL, "100.001", "event-error", True)

    harness.api.stream_chat.assert_called_once()
    assert harness.service.store.operation("event-error")["state"] == "uncertain"
    assert "before trying again" in harness.slack.chat_update.call_args.kwargs["text"]


def test_old_sources_button_checks_backend_deletion_before_showing_cached_excerpts(harness):
    key = harness.service.store.save_answer(
        {"conversation_id": "conversation-1", "sources": [SOURCE]}
    )
    harness.api.conversation.side_effect = APIError(404, "Conversation not found.")
    harness.dispatch(action_body("view_sources", key, view=modal("conversation_detail")))
    assert not harness.api.mock_calls
    harness.drain()

    rendered = harness.slack.views_update.call_args.kwargs["view"]
    assert rendered["title"]["text"] == "Sources unavailable"
    assert "Vacation policy" not in json.dumps(rendered)
    assert harness.service.store.answer(key) is None


@pytest.mark.parametrize(
    "error", ["edit_window_closed", "cant_update_message", "channel_not_found"]
)
def test_uneditable_old_receipt_does_not_block_presentation_upgrade_or_sync(harness, error):
    harness.api.requests.return_value = [WORKFLOW]
    answer_id = harness.service.store.save_answer(
        {
            "answer": "Old draft",
            "sources": [],
            "channel": CHANNEL,
            "ts": "100.001",
            "request_id": WORKFLOW["id"],
        }
    )
    harness.service.store.track_card(WORKFLOW["id"], CHANNEL, "100.001", answer_id)
    harness.slack.chat_update.side_effect = SlackApiError("Uneditable message", {"error": error})

    harness.service.upgrade_messages()
    harness.service.poll_once()

    assert harness.service.store.get("presentation_version") == 2
    assert not harness.service.store.cards(WORKFLOW["id"])
    assert harness.service.store.snapshot(WORKFLOW["id"])["request"]["id"] == WORKFLOW["id"]


@pytest.mark.parametrize(
    "previous,target,values",
    [
        ("pto", "sick_leave", pto_values()),
        ("sick_leave", "pto", sick_values(comment=text(" Handoff to R&D <team> "))),
    ],
)
def test_type_switch_rebuilds_form_preserving_shared_edits(harness, previous, target, values):
    body = action_body(
        "value",
        view=modal(
            "request_submit",
            {
                "request_type": previous,
                "draft_id": "draft-existing",
            },
            values,
        ),
    )
    body["actions"][0].update(
        {"type": "static_select", "block_id": "type", "selected_option": {"value": target}}
    )
    harness.dispatch(body)
    call = harness.slack.views_update.call_args.kwargs
    assert call["view_id"] == VIEW and call["hash"] == "view-hash"
    rebuilt = call["view"]
    rebuilt_metadata = json.loads(rebuilt["private_metadata"])
    assert rebuilt_metadata["request_type"] == target
    assert rebuilt_metadata["draft_id"] == "draft-existing"
    assert rebuilt_metadata["state_values"]["start_date"] == "2026-10-05"
    rebuilt_fields = {
        block["block_id"]: block["element"]
        for block in rebuilt["blocks"]
        if block["type"] == "input"
    }
    assert "type" not in rebuilt_fields
    assert rebuilt_fields["start_date"]["initial_date"] == "2026-10-05"
    assert rebuilt_fields["comment"]["initial_value"] == " Handoff to R&D <team> "
    assert ("expected_return_date" in rebuilt_fields) == (target == "sick_leave")
    assert not harness.api.mock_calls and not harness.jobs


@pytest.mark.parametrize(
    "values,error_field",
    [
        (pto_values(comment=text("  ")), "comment"),
        (pto_values(end_date=chosen_date("2026-10-04")), "end_date"),
        (pto_values(start_date=chosen_date(None)), "start_date"),
    ],
)
def test_request_submit_returns_inline_errors_without_queuing(harness, values, error_field):
    response = harness.dispatch(submission("request_submit", values, {"request_type": "pto"}))
    assert response["response_action"] == "errors"
    assert error_field in response["errors"]
    assert harness.ack_seconds < 3
    assert not harness.jobs and not harness.api.mock_calls and not harness.slack_calls.mock_calls


def test_request_submit_ack_processing_and_background_payload(harness):
    response = harness.dispatch(
        submission(
            "request_submit",
            pto_values(),
            {
                "request_type": "pto",
                "draft_id": "draft-existing",
            },
        )
    )
    assert response["response_action"] == "update"
    assert response["view"]["title"]["text"] == "Sending your request"
    assert harness.ack_seconds < 3
    assert not harness.api.mock_calls
    function, args = harness.jobs[0]
    assert function == harness.service.submit_request
    assert args == (
        VIEW,
        {
            "type": "pto",
            "start_date": "2026-10-05",
            "end_date": "2026-10-07",
            "comment": "Handoff to R&D <team>",
            "details": {},
        },
        "draft-existing",
        "submit:" + VIEW,
    )
    harness.drain()
    harness.api.create_request.assert_not_called()
    harness.api.submit_request.assert_called_once_with("draft-existing", args[1])


def test_request_ack_does_not_wait_for_blocked_backend(harness):
    entered, release = Event(), Event()
    futures = []

    def blocked_create(payload):
        entered.set()
        assert release.wait(5), "Test failed to release background API call"
        return copy.deepcopy(WORKFLOW)

    def queue(function, *args):
        future = harness.real_queue(function, *args)
        futures.append(future)
        return future

    harness.api.create_request.side_effect = blocked_create
    harness.service.queue = queue
    try:
        body = submission("request_submit", pto_values(), {"request_type": "pto"})
        response = harness.dispatch(body)
        assert harness.ack_seconds < 3
        assert response["response_action"] == "update"
        assert entered.wait(2), "Backend creation was not scheduled"
        assert not futures[0].done()
        assert not release.is_set()
        harness.api.submit_request.assert_not_called()
        # A retry arriving while the first operation is still running also acks promptly.
        harness.dispatch(body)
        assert harness.ack_seconds < 3
        assert len(futures) == 2
    finally:
        release.set()
        for future in futures:
            future.result(timeout=5)
    harness.api.create_request.assert_called_once()
    harness.api.submit_request.assert_called_once()
    assert harness.service.store.operation("submit:" + VIEW)["state"] == "complete"


def test_duplicate_request_submission_has_one_backend_mutation(harness):
    body = submission("request_submit", pto_values(), {"request_type": "pto"})
    harness.dispatch(body)
    harness.dispatch(body)
    assert len(harness.jobs) == 2
    harness.drain()
    harness.api.create_request.assert_called_once()
    harness.api.submit_request.assert_called_once()
    assert harness.service.store.operation("submit:" + VIEW) == {
        "state": "complete",
        "payload": {"request_id": "request-1"},
    }


def test_continue_button_question_submission_binds_existing_history(harness):
    harness.dispatch(
        action_body("continue_conversation", "conversation-1", view=modal("conversation_detail"))
    )
    question = harness.slack.views_update.call_args.kwargs["view"]
    assert question["callback_id"] == "question_submit"
    metadata = json.loads(question["private_metadata"])
    assert metadata == {"conversation_id": "conversation-1"}
    body = submission("question_submit", fields(question=text(" What about next week? ")), metadata)
    harness.dispatch(body)
    assert harness.jobs == [
        (harness.service.ask_new, ("What about next week?", "question:" + VIEW, "conversation-1"))
    ]
    harness.dispatch(body)
    harness.drain()
    harness.api.conversation.assert_called_once_with("conversation-1")
    harness.api.stream_chat.assert_called_once_with("What about next week?", "conversation-1")
    assert (
        harness.slack.chat_postMessage.call_count == 1
    )  # The visible answer is the conversation root.
    assert "thread_ts" not in harness.slack.chat_postMessage.call_args.kwargs
    assert harness.service.store.thread(CHANNEL, "1.001")["conversation_id"] == "conversation-1"


def test_question_inline_empty_and_fresh_question_metadata(harness):
    response = harness.dispatch(submission("question_submit", fields(question=text("  "))))
    assert response == {"response_action": "errors", "errors": {"question": "Enter a question."}}
    assert not harness.jobs
    harness.dispatch(submission("question_submit", fields(question=text("Policy?"))))
    assert harness.jobs == [(harness.service.ask_new, ("Policy?", "question:" + VIEW, None))]


def test_feedback_callback_uses_cached_answer_and_deduplicates(harness):
    key = harness.service.store.save_answer(
        {
            "question": "Policy?",
            "answer": "Saved original answer.",
            "sources": [SOURCE],
            "conversation_id": "conversation-1",
            "channel": CHANNEL,
            "thread_ts": "1.001",
        }
    )
    harness.dispatch(action_body("feedback_unhelpful", key))
    feedback = harness.slack.views_open.call_args.kwargs["view"]
    assert feedback["callback_id"] == "feedback_submit"
    assert json.loads(feedback["private_metadata"]) == {"answer_id": key}
    body = submission(
        "feedback_submit", fields(comment=text(" Missing detail ")), {"answer_id": key}
    )
    harness.dispatch(body)
    assert harness.jobs == [(harness.service.rate, (key, 1, "Missing detail"))]
    harness.dispatch(body)
    harness.drain()
    harness.api.feedback.assert_called_once_with(
        "Policy?", "Saved original answer.", 1, "Missing detail"
    )
    assert harness.service.store.operation("feedback:" + key)["state"] == "complete"
    harness.slack.chat_postMessage.assert_not_called()


def test_helpful_feedback_and_missing_cached_answer(harness):
    key = harness.service.store.save_answer(
        {"question": "Q", "answer": "A", "channel": CHANNEL, "thread_ts": "2.001"}
    )
    harness.dispatch(action_body("feedback_helpful", key))
    harness.drain()
    harness.api.feedback.assert_called_once_with("Q", "A", 5, "")
    harness.dispatch(
        submission("feedback_submit", fields(comment=text(None)), {"answer_id": "expired"})
    )
    harness.drain()
    assert harness.api.feedback.call_count == 1


def test_root_dm_answer_is_visible_and_both_followup_roots_keep_context(harness):
    def message(identity, ts, question, thread=None):
        event = {
            "type": "message",
            "user": USER,
            "channel": CHANNEL,
            "channel_type": "im",
            "text": question,
            "ts": ts,
        }
        if thread:
            event["thread_ts"] = thread
        return {"type": "event_callback", "team_id": TEAM, "event_id": identity, "event": event}

    first = message("EvROOT", "100.001", "Vacation policy?")
    harness.dispatch(first)
    harness.drain()
    assert "thread_ts" not in harness.slack.chat_postMessage.call_args.kwargs
    assert harness.service.store.thread(CHANNEL, "100.001")["conversation_id"] == "conversation-1"
    assert harness.service.store.thread(CHANNEL, "1.001")["conversation_id"] == "conversation-1"
    harness.dispatch(first)
    harness.drain()
    assert harness.api.stream_chat.call_count == 1

    for index, root in enumerate(["100.001", "1.001"]):
        harness.dispatch(message(f"EvFOLLOW{index}", f"101.{index}", "And next week?", root))
        harness.drain()
        assert harness.slack.chat_postMessage.call_args.kwargs["thread_ts"] == root
        assert harness.api.stream_chat.call_args.args == ("And next week?", "conversation-1")


def test_dynamic_absence_form_preserves_draft_dates_and_note_through_real_bolt(harness):
    values = sick_values(comment=text("Coverage arranged"), expected_return_unknown=checked(True))
    body = action_body(
        "request_field_changed",
        view=modal("request_submit", {"request_type": "sick_leave", "draft_id": "draft-1"}, values),
    )
    body["actions"][0].update({"block_id": "time_away", **selected("partial_day")})
    harness.dispatch(body)
    updated = harness.slack.views_update.call_args.kwargs
    assert updated["hash"] == "view-hash"
    form = updated["view"]
    inputs = {block["block_id"]: block for block in form["blocks"] if block.get("type") == "input"}
    assert "partial_hours" in inputs
    assert "expected_return_date" not in inputs
    assert "type" not in inputs
    assert inputs["start_date"]["element"]["initial_date"] == "2026-10-05"
    assert inputs["comment"]["element"]["initial_value"] == "Coverage arranged"
    assert json.loads(form["private_metadata"])["draft_id"] == "draft-1"
    harness.api.create_request.assert_not_called()
    assert not harness.jobs


def test_home_chat_url_click_acknowledges_without_opening_question_modal(harness):
    harness.dispatch(action_body("open_slack_chat"))
    assert not harness.jobs
    harness.slack.views_open.assert_not_called()


def test_slack_history_link_is_cached_and_does_not_create_another_conversation(harness):
    harness.service.store.bind(CHANNEL, "100.001", "conversation-1")
    harness.api.conversations.return_value = [{"id": "conversation-1", "title": "Vacation policy?"}]
    harness.service.home("conversations")
    view = harness.slack.views_publish.call_args.kwargs["view"]
    links = [node for node in buttons(view, "open_slack_conversation") if node.get("url")]
    assert len(links) == 1
    assert links[0]["url"].startswith("https://example.slack.com/")
    harness.service.home("conversations")
    harness.slack.chat_getPermalink.assert_called_once()
    harness.api.stream_chat.assert_not_called()
    harness.slack.chat_postMessage.assert_not_called()


@pytest.mark.parametrize(
    "bad_hours", ["NaN", "nan", "Infinity", "-inf", "1e309", "0", "-0.5", "24.1", ""]
)
def test_parser_and_dispatch_reject_invalid_partial_hours(harness, bad_hours):
    values = sick_values(time_away=selected("partial_day"), partial_hours=text(bad_hours))
    _, errors = request_payload(values, "sick_leave")
    assert "partial_hours" in errors
    response = harness.dispatch(
        submission("request_submit", values, {"request_type": "sick_leave"})
    )
    assert response["response_action"] == "errors" and "partial_hours" in response["errors"]
    assert not harness.jobs and not harness.api.mock_calls


def test_unknown_return_ignores_stale_date_hours_and_end_date(harness):
    values = sick_values(
        expected_return_unknown=checked(True),
        expected_return_date=chosen_date("not-a-date"),
        end_date=chosen_date("2026-10-30"),
        partial_hours=text("NaN"),
    )
    payload, errors = request_payload(values, "sick_leave")
    assert not errors
    assert payload["end_date"] is None
    assert payload["details"] == {
        "expected_return_unknown": True,
        "expected_return_date": None,
        "time_away": "full_day",
        "partial_hours": None,
        "extended_or_recurring": False,
    }
    assert payload["comment"] == ""
    harness.dispatch(submission("request_submit", values, {"request_type": "sick_leave"}))
    assert harness.jobs[0][1][1] == payload


@pytest.mark.parametrize(
    "away,return_date,hours,valid",
    [
        ("full_day", None, None, False),
        ("full_day", "2026-10-05", None, False),
        ("full_day", "2026-10-06", None, True),
        ("partial_day", "2026-10-05", "0.25", True),
        ("partial_day", "2026-10-04", "4", False),
        ("partial_day", "2026-10-05", "24", True),
    ],
)
def test_sick_return_and_fractional_hours_boundaries(away, return_date, hours, valid):
    payload, errors = request_payload(
        sick_values(
            time_away=selected(away),
            expected_return_date=chosen_date(return_date),
            partial_hours=text(hours),
        ),
        "sick_leave",
    )
    assert (not errors) is valid
    if valid:
        json.dumps(payload, allow_nan=False)
    else:
        assert "expected_return_date" in errors


@pytest.mark.parametrize(
    "field,expected",
    [
        (chosen_date(None), None),
        (selected(None), None),
        (checked(False), False),
        (checked(True), True),
        (text(None), None),
        (text("0.25"), "0.25"),
    ],
)
def test_field_parser_slack_null_and_selection_shapes(field, expected):
    assert field_value(fields(example=field), "example") == expected
    assert field_value({}, "missing") is None


def test_store_claim_survives_reopen_and_never_replays_uncertain_mutation(tmp_path):
    path = tmp_path / "state.sqlite"
    store = Store(path)
    assert store.claim("submit:1")
    assert not Store(path).claim("submit:1")
    store.finish("submit:1", "uncertain", {"request_id": "draft-1"})
    restored = Store(path)
    assert not restored.claim("submit:1")
    assert restored.operation("submit:1") == {
        "state": "uncertain",
        "payload": {"request_id": "draft-1"},
    }


def test_store_claim_is_atomic_across_connections(tmp_path):
    path = tmp_path / "race.sqlite"
    first, second = Store(path), Store(path)
    gate = Barrier(2)

    def claim(store):
        gate.wait(timeout=2)
        return store.claim("same-delivery")

    with ThreadPoolExecutor(max_workers=2) as executor:
        one, two = executor.submit(claim, first), executor.submit(claim, second)
        assert sorted((one.result(timeout=3), two.result(timeout=3))) == [False, True]


def test_history_forget_removes_only_related_answers_and_keeps_request_cards(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    store.bind(CHANNEL, "1", "chat-delete")
    store.bind(CHANNEL, "2", "chat-keep")
    removed = store.save_answer({"conversation_id": "chat-delete", "sources": [SOURCE]})
    kept = store.save_answer({"conversation_id": "chat-keep", "sources": [SOURCE]})
    store.track_card("request-1", CHANNEL, "3", removed)
    store.forget_conversation("chat-delete")
    assert store.thread(CHANNEL, "1")["deleted"] == 1
    assert store.thread(CHANNEL, "2")["deleted"] == 0
    assert store.answer(removed) is None and store.answer(kept)["sources"] == [SOURCE]
    assert len(store.cards("request-1")) == 1


def test_process_lock_rejects_second_acquisition_and_releases(tmp_path):
    path = tmp_path / "receiver.lock"
    with ProcessLock(path):
        with pytest.raises(ValueError, match="already running"):
            with ProcessLock(path):
                pytest.fail("A competing receiver acquired the same state lock")
    with ProcessLock(path) as reacquired:
        assert reacquired.file is not None
    assert reacquired.file is None


def test_normal_dm_followups_survive_restart_and_new_chat_resets_context(harness):
    service = harness.service
    service.ask("Vacation policy?", CHANNEL, "200.001", "new-dm-1", True)
    assert harness.api.stream_chat.call_args.args == ("Vacation policy?", None)
    service.store = Store(service.settings.state_path)
    service.ask("And for partial days?", CHANNEL, "201.001", "new-dm-2", True)
    assert harness.api.stream_chat.call_args.args == ("And for partial days?", "conversation-1")
    service.ask("new chat", CHANNEL, "202.001", "new-dm-3", True)
    assert harness.api.stream_chat.call_count == 2
    service.ask("Payroll?", CHANNEL, "203.001", "new-dm-4", True)
    assert harness.api.stream_chat.call_args.args == ("Payroll?", None)
    service.ask("What about my old question?", CHANNEL, "200.001", "old-thread")
    assert harness.api.stream_chat.call_args.args == (
        "What about my old question?",
        "conversation-1",
    )


def test_sources_are_read_from_current_context_without_new_ai_call(harness):
    service = harness.service
    service.ask("Vacation policy?", CHANNEL, "200.001", "source-question", True)
    before = harness.api.stream_chat.call_count
    service.ask("sources", CHANNEL, "201.001", "sources-command", True)
    assert harness.api.stream_chat.call_count == before
    posted = harness.slack.chat_postMessage.call_args.kwargs
    assert "Vacation policy" in json.dumps(posted["blocks"])
    assert not any(block.get("type") == "actions" for block in posted["blocks"])
    assert "thread_ts" not in posted
    service.ask("sources", CHANNEL, "unknown-thread", "unrelated-sources")
    assert "no saved sources" in harness.slack.chat_postMessage.call_args.kwargs["text"]
    assert service.store.get("active_conversation:" + CHANNEL) == "conversation-1"


def test_unified_request_flow_opens_both_types_without_backend_mutation(harness):
    harness.dispatch(action_body("new_request"))
    assert harness.slack.views_open.call_args.kwargs["view"]["callback_id"] == "request_type_submit"
    for kind in ("pto", "sick_leave"):
        result = harness.dispatch(
            submission("request_type_submit", fields(request_type=selected(kind)))
        )
        assert result["response_action"] == "update"
        assert json.loads(result["view"]["private_metadata"])["request_type"] == kind
    assert not harness.api.mock_calls
    assert not harness.jobs


def test_home_selects_navigate_and_review_existing_draft(harness):
    body = action_body("home_section")
    body["actions"][0]["selected_option"] = {"value": "requests"}
    harness.dispatch(body)
    harness.drain()
    assert (
        json.loads(harness.slack.views_publish.call_args.kwargs["view"]["private_metadata"])[
            "section"
        ]
        == "requests"
    )
    body = action_body("select_request")
    body["actions"][0]["selected_option"] = {"value": "request-1"}
    harness.dispatch(body)
    harness.drain()
    form = harness.slack.views_update.call_args.kwargs["view"]
    assert form["callback_id"] == "request_submit"
    assert json.loads(form["private_metadata"])["draft_id"] == "request-1"
    harness.api.create_request.assert_not_called()
    harness.api.submit_request.assert_not_called()


def test_slash_request_reviews_chat_draft_without_creating_another(harness):
    answer_id = harness.service.store.save_answer({"request_id": "request-1"})
    harness.service.store.set("latest_answer:" + CHANNEL, answer_id)
    harness.dispatch(
        {
            "command": "/peopleflow",
            "text": "request",
            "team_id": TEAM,
            "user_id": USER,
            "channel_id": CHANNEL,
            "trigger_id": "review-trigger",
        }
    )
    harness.drain()
    form = harness.slack.views_update.call_args.kwargs["view"]
    assert json.loads(form["private_metadata"])["draft_id"] == "request-1"
    harness.api.create_request.assert_not_called()
    harness.api.submit_request.assert_not_called()


def test_slash_sources_from_channel_keeps_employee_data_in_private_dm(harness):
    harness.service.ask("Vacation policy?", CHANNEL, "200.001", "source-question", True)
    harness.slack.chat_postMessage.reset_mock()
    harness.dispatch(
        {
            "command": "/peopleflow",
            "text": "sources",
            "team_id": TEAM,
            "user_id": USER,
            "channel_id": "CPUBLIC",
            "trigger_id": "sources-trigger",
        }
    )
    harness.drain()
    posted = harness.slack.chat_postMessage.call_args.kwargs
    assert posted["channel"] == CHANNEL
    assert "Vacation policy" in json.dumps(posted["blocks"])
    assert harness.service.store.get("active_conversation:" + CHANNEL) == "conversation-1"


def test_reply_below_sources_keeps_original_conversation(harness):
    service = harness.service
    service.ask("Vacation policy?", CHANNEL, "200.001", "source-question", True)
    service.ask("sources", CHANNEL, "201.001", "sources-command", True)
    # First answer is 1.001; the sources message is 2.001.
    assert service.store.thread(CHANNEL, "2.001")["conversation_id"] == "conversation-1"
    service.ask("Does this cover partial days?", CHANNEL, "2.001", "sources-followup")
    assert harness.api.stream_chat.call_args.args == (
        "Does this cover partial days?",
        "conversation-1",
    )


def test_failed_new_chat_cannot_review_previous_conversations_draft(harness):
    service = harness.service
    old = service.store.save_answer({"request_id": "old-draft", "conversation_id": "old-chat"})
    service.store.set("active_conversation:" + CHANNEL, "old-chat")
    service.store.set("latest_answer:" + CHANNEL, old)
    service.ask_new("", "empty-new-chat")
    service.request_entry(VIEW)
    assert (
        harness.slack.views_update.call_args.kwargs["view"]["callback_id"] == "request_type_submit"
    )
    harness.api.request.assert_not_called()


def test_live_workflow_card_replaces_draft_copy_after_submission(harness):
    service = harness.service
    harness.api.stream_chat.return_value = [
        {"type": "token", "content": "Draft ready"},
        {
            "type": "complete",
            "conversation_id": "conversation-1",
            "sources": [],
            "workflow_request": WORKFLOW,
        },
    ]
    service.ask("I need PTO", CHANNEL, "200.001", "workflow-question", True)
    service.refresh_cards({**WORKFLOW, "status": "in_review"})
    card = json.dumps(harness.slack.chat_update.call_args.kwargs["blocks"])
    assert "with your manager" in card
    assert "before sending" not in card
    assert "Not sent yet" not in card


def test_presentation_upgrade_is_not_hidden_by_source_history_cache(harness):
    service = harness.service
    service.store.save_answer(
        {"answer": "Old answer", "sources": [], "channel": CHANNEL, "ts": "old.001"}
    )
    for index in range(110):
        service.store.save_answer({"answer": "History excerpt", "sources": []}, f"history:{index}")
    service.upgrade_messages()
    assert harness.slack.chat_update.call_count == 1
    assert harness.slack.chat_update.call_args.kwargs["ts"] == "old.001"
    service.upgrade_messages()
    assert harness.slack.chat_update.call_count == 1
