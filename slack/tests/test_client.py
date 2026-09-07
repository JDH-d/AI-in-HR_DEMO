"""HTTP contract tests: no backend imports, Slack credentials, or network calls."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from types import SimpleNamespace

import httpx
import pytest

from peopleflow_slack import client as client_module
from peopleflow_slack.client import APIError, PeopleFlowClient

USER = {
    "id": "employee.demo",
    "username": "employee",
    "display_name": "Demo Employee",
    "role": "employee",
    "manager_id": "manager.demo",
}
WORKFLOW = {
    "id": "request-1",
    "type": "pto",
    "type_label": "Paid time off",
    "status": "draft",
    "details": {},
    "validation_errors": [],
    "comment": "Holiday",
}
SUMMARY = {"id": "conversation-1", "title": "Holiday", "message_count": 2}
COMPLETE = {
    "type": "complete",
    "intent": "knowledge_question",
    "language": "en",
    "outcome_code": "grounded",
    "sources": [],
    "workflow_request": None,
    "conversation_id": "conversation-1",
}
CHAT = {
    **{key: value for key, value in COMPLETE.items() if key != "type"},
    "message": {"role": "assistant", "content": "Your answer."},
}
CONVERSATION = {
    "conversation": SUMMARY,
    "messages": [
        {"id": "message-1", "role": "user", "content": "Holiday"},
        {
            "id": "message-2",
            "role": "assistant",
            "content": "Your answer.",
            "sources": [],
            "workflow": WORKFLOW,
        },
    ],
}
DETAIL = {"request": WORKFLOW, "events": [], "comments": []}


def login_body(token="employee-token", **overrides):
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 28800,
        "user": dict(USER),
        **overrides,
    }


@pytest.fixture
def client_factory():
    clients = []

    def create(handler, *, login=None, **options):
        calls = []

        def dispatch(request):
            calls.append(request)
            if request.url.path.endswith("/auth/login"):
                assert request.method == "POST"
                assert "authorization" not in request.headers
                assert json.loads(request.content) == {
                    "username": "employee",
                    "password": options.get("password", "demo-password"),
                }
                return login(request) if login else httpx.Response(200, json=login_body())
            return handler(request)

        client = PeopleFlowClient(
            options.pop("base_url", "https://peopleflow.example"),
            transport=httpx.MockTransport(dispatch),
            **options,
        )
        clients.append(client)
        return client, calls

    yield create
    for client in clients:
        client.close()


def auth_calls(calls):
    return [call for call in calls if call.url.path.endswith("/auth/login")]


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error
        self.closed = False

    def __iter__(self):
        yield from self.chunks
        if self.error:
            raise self.error("private transport diagnostic")

    def close(self):
        self.closed = True


def stream_response(events=None, *, stream=None):
    if stream is None:
        raw = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
        stream = ChunkStream([raw.encode("utf-8")])
    return httpx.Response(200, headers={"content-type": "application/x-ndjson"}, stream=stream)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://peopleflow.example",
        "https://peopleflow.example/",
        "https://peopleflow.example/api/v1",
        "https://peopleflow.example/api/v1/",
    ],
)
def test_health_is_anonymous_and_normalizes_base_url(client_factory, base_url):
    body = {"status": "ok", "api_version": "v1", "knowledge_index": {}}
    client, calls = client_factory(lambda _: httpx.Response(200, json=body), base_url=base_url)
    assert client.health() == body
    assert len(calls) == 1
    assert calls[0].url.path == "/api/v1/health"
    assert "authorization" not in calls[0].headers


def test_me_authenticates_employee_once_and_caches_token(client_factory):
    client, calls = client_factory(lambda _: httpx.Response(200, json={"user": USER}))
    assert client.me() == {"user": USER}
    assert client.me() == {"user": USER}
    assert len(auth_calls(calls)) == 1
    for call in calls[1:]:
        assert call.headers["authorization"] == "Bearer employee-token"
        assert "x-user" not in call.headers


@pytest.mark.parametrize(
    ("method", "args", "verb", "path", "payload", "body", "expected"),
    [
        (
            "chat",
            (" Hello \n",),
            "POST",
            "chat",
            {"messages": [{"role": "user", "content": " Hello \n"}]},
            CHAT,
            CHAT,
        ),
        (
            "chat",
            ("Next", "conversation-1"),
            "POST",
            "chat",
            {
                "messages": [{"role": "user", "content": "Next"}],
                "conversation_id": "conversation-1",
            },
            CHAT,
            CHAT,
        ),
        (
            "conversations",
            (),
            "GET",
            "conversations",
            None,
            {"conversations": [SUMMARY]},
            [SUMMARY],
        ),
        (
            "conversation",
            ("conversation-1",),
            "GET",
            "conversations/conversation-1",
            None,
            CONVERSATION,
            CONVERSATION,
        ),
        ("requests", (), "GET", "requests", None, {"requests": [WORKFLOW]}, [WORKFLOW]),
        ("request", ("request-1",), "GET", "requests/request-1", None, DETAIL, DETAIL),
        (
            "create_request",
            ({"type": "pto", "details": {"full_day": True}},),
            "POST",
            "requests",
            {"type": "pto", "details": {"full_day": True}},
            {"request": WORKFLOW},
            WORKFLOW,
        ),
        (
            "submit_request",
            ("request-1", {"comment": "Ready"}),
            "POST",
            "requests/request-1/submit",
            {"comment": "Ready"},
            {"request": WORKFLOW},
            {"request": WORKFLOW},
        ),
        (
            "cancel_request",
            ("request-1",),
            "POST",
            "requests/request-1/cancel",
            {"comment": ""},
            {"request": WORKFLOW},
            {"request": WORKFLOW},
        ),
        (
            "cancel_request",
            ("request-1", "Plans changed"),
            "POST",
            "requests/request-1/cancel",
            {"comment": "Plans changed"},
            {"request": WORKFLOW},
            {"request": WORKFLOW},
        ),
        (
            "feedback",
            ("Question", "Answer", 5),
            "POST",
            "feedback",
            {"question": "Question", "answer": "Answer", "rating": 5, "comment": ""},
            {"feedback": {"id": "feedback-1"}},
            {"feedback": {"id": "feedback-1"}},
        ),
        (
            "feedback",
            ("Question", "Answer", 1, "Incorrect"),
            "POST",
            "feedback",
            {"question": "Question", "answer": "Answer", "rating": 1, "comment": "Incorrect"},
            {"feedback": {"id": "feedback-1"}},
            {"feedback": {"id": "feedback-1"}},
        ),
    ],
)
def test_exact_endpoint_payload_and_response_envelope(
    client_factory, method, args, verb, path, payload, body, expected
):
    client, calls = client_factory(lambda _: httpx.Response(200, json=body))
    assert getattr(client, method)(*args) == expected
    call = calls[-1]
    assert call.method == verb
    assert call.url.path == "/api/v1/" + path
    assert call.headers["authorization"] == "Bearer employee-token"
    assert json.loads(call.content) == payload if payload is not None else not call.content


def test_delete_handles_empty_204(client_factory):
    client, calls = client_factory(lambda _: httpx.Response(204))
    assert client.delete_conversation("conversation-1") is None
    assert calls[-1].method == "DELETE"
    assert calls[-1].url.path == "/api/v1/conversations/conversation-1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "manager"),
        ("role", "knowledge_admin"),
        ("id", "other.employee"),
        ("username", "manager"),
    ],
)
def test_role_lock_refuses_non_employee_login_before_business_request(client_factory, field, value):
    user = {**USER, field: value}
    client, calls = client_factory(
        lambda _: pytest.fail("A business endpoint must not run with a different identity"),
        login=lambda _: httpx.Response(200, json=login_body(user=user)),
    )
    with pytest.raises(APIError) as error:
        client.requests()
    assert error.value.status == 403
    assert error.value.uncertain is False
    assert len(calls) == 1


def test_me_rechecks_role_and_discards_changed_identity(client_factory):
    client, calls = client_factory(
        lambda _: httpx.Response(200, json={"user": {**USER, "role": "manager"}})
    )
    for _ in range(2):
        with pytest.raises(APIError, match="employee.demo"):
            client.me()
    assert len(auth_calls(calls)) == 2


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        {"access_token": "token"},
        login_body(user=None),
        login_body(expires_in="28800"),
        login_body(expires_in=None),
        login_body(expires_in=0),
        login_body(expires_in=True),
        login_body(expires_in=float("inf")),
        login_body(access_token=""),
        login_body(access_token=123),
        login_body(access_token="token\r\ninjected"),
        login_body(token_type="basic"),
    ],
)
def test_invalid_login_is_safe_and_never_sends_business_request(client_factory, body):
    # The non-finite TTL case needs a raw JSON body because httpx disallows NaN/Infinity output.
    client, calls = client_factory(
        lambda _: pytest.fail("Invalid authentication response must stop here"),
        login=lambda _: httpx.Response(200, content=json.dumps(body)),
    )
    with pytest.raises(APIError) as error:
        client.me()
    assert error.value.status == 502
    assert not error.value.uncertain
    assert len(calls) == 1


def test_token_expires_and_refreshes_before_next_call(client_factory, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(client_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    issued = []

    def login(_):
        token = f"employee-{len(issued)}"
        issued.append(token)
        return httpx.Response(200, json=login_body(token, expires_in=10))

    client, calls = client_factory(
        lambda _: httpx.Response(200, json={"user": USER}),
        login=login,
    )
    client.me()
    now[0] = 108.0
    client.me()
    assert len(issued) == 1
    now[0] = 110.0
    client.me()
    assert len(issued) == 2
    assert calls[-1].headers["authorization"] == "Bearer employee-1"


def test_401_reauthenticates_and_retries_post_once(client_factory):
    attempts = []

    def chat(request):
        attempts.append(request)
        return (
            httpx.Response(401, json={"detail": "expired"})
            if len(attempts) == 1
            else (httpx.Response(200, json=CHAT))
        )

    client, calls = client_factory(chat)
    assert client.chat("Question") == CHAT
    assert len(auth_calls(calls)) == 2
    assert len(attempts) == 2
    assert attempts[0].content == attempts[1].content


def test_second_401_stops_without_third_login(client_factory):
    client, calls = client_factory(lambda _: httpx.Response(401, json={"detail": "denied"}))
    with pytest.raises(APIError) as error:
        client.me()
    assert error.value.status == 401
    assert not error.value.uncertain
    assert len(auth_calls(calls)) == 2
    assert len(calls) == 4


def test_login_401_itself_is_not_retried(client_factory):
    client, calls = client_factory(
        lambda _: pytest.fail("No login, no business request"),
        login=lambda _: httpx.Response(401, json={"detail": "Invalid demo credentials."}),
    )
    with pytest.raises(APIError, match="Invalid demo credentials"):
        client.me()
    assert len(calls) == 1


def test_concurrent_initial_authentication_only_logs_in_once(client_factory):
    gate = Barrier(8)
    client, calls = client_factory(lambda _: httpx.Response(200, json={"user": USER}))

    def worker(_):
        gate.wait(timeout=5)
        return client.me()

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(worker, range(8))) == [{"user": USER}] * 8
    assert len(auth_calls(calls)) == 1


def test_concurrent_401_responses_share_one_refresh(client_factory):
    gate = Barrier(6)
    counter_lock = Lock()
    logins = [0]

    def login(_):
        with counter_lock:
            logins[0] += 1
            return httpx.Response(200, json=login_body(f"employee-{logins[0]}"))

    def handler(request):
        if request.headers["authorization"] == "Bearer employee-1":
            gate.wait(timeout=5)
            return httpx.Response(401)
        return httpx.Response(200, json={"user": USER})

    client, calls = client_factory(handler, login=login)
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(lambda _: client.me(), range(6))) == [{"user": USER}] * 6
    assert len(auth_calls(calls)) == 2
    assert len(calls) == 14


@pytest.mark.parametrize(
    ("exception", "status", "uncertain"),
    [
        (httpx.ReadTimeout, 504, True),
        (httpx.WriteTimeout, 504, True),
        (httpx.ReadError, 503, True),
        (httpx.WriteError, 503, True),
        (httpx.RemoteProtocolError, 503, True),
        (httpx.ConnectTimeout, 504, False),
        (httpx.ConnectError, 503, False),
        (httpx.PoolTimeout, 504, False),
    ],
)
def test_transport_errors_never_retry_post(client_factory, exception, status, uncertain):
    def fail(_):
        raise exception("secret-password and private question")

    client, calls = client_factory(fail)
    with pytest.raises(APIError) as error:
        client.create_request({"type": "pto"})
    assert error.value.status == status
    assert error.value.uncertain is uncertain
    assert "secret-password" not in str(error.value)
    assert "private question" not in repr(error.value)
    assert len(calls) == 2


def test_get_timeout_is_not_an_uncertain_mutation(client_factory):
    def fail(_):
        raise httpx.ReadTimeout("private diagnostic")

    client, calls = client_factory(fail)
    with pytest.raises(APIError) as error:
        client.requests()
    assert error.value.status == 504
    assert not error.value.uncertain
    assert len(calls) == 2


def test_timeout_applies_to_every_http_operation(client_factory):
    client, calls = client_factory(
        lambda _: httpx.Response(200, json={"user": USER}),
        timeout=12.5,
    )
    client.me()
    for call in calls:
        assert call.extensions["timeout"] == dict.fromkeys(
            ["connect", "read", "write", "pool"], 12.5
        )


@pytest.mark.parametrize("status", [400, 403, 404, 409, 422, 429, 500, 502, 503])
def test_http_errors_are_safe_and_not_retried(client_factory, status, caplog):
    private = "<@U123> secret-password private-answer"
    client, calls = client_factory(
        lambda _: httpx.Response(status, json={"detail": private}),
        password="secret-password",
    )
    with pytest.raises(APIError) as error:
        client.chat("private-question")
    assert error.value.status == status
    assert error.value.uncertain is (status >= 500)
    assert private not in error.value.detail
    assert len(calls) == 2
    assert "secret-password" not in caplog.text
    assert "private-question" not in caplog.text


@pytest.mark.parametrize(
    "detail",
    [
        [{"type": "string_type", "loc": ["body", "comment"], "msg": "private", "input": "secret"}],
        {"nested": "secret"},
        ["secret"],
        None,
    ],
)
def test_validation_objects_never_echo_original_input(client_factory, detail):
    client, _ = client_factory(lambda _: httpx.Response(422, json={"detail": detail}))
    with pytest.raises(APIError) as error:
        client.submit_request("request-1", {})
    assert error.value.detail == "Check the request fields and try again."


def test_static_workflow_validation_messages_are_preserved(client_factory):
    detail = ["Start date is required.", "Comment is required."]
    client, _ = client_factory(lambda _: httpx.Response(422, json={"detail": detail}))
    with pytest.raises(APIError) as error:
        client.create_request({"type": "pto"})
    assert error.value.detail == " ".join(detail)


def test_redirect_never_forwards_token_or_post(client_factory):
    client, calls = client_factory(
        lambda _: httpx.Response(307, headers={"location": "https://other.example/private"})
    )
    with pytest.raises(APIError) as error:
        client.chat("Question")
    assert error.value.status == 307
    assert len(calls) == 2
    assert all(call.url.host == "peopleflow.example" for call in calls)


@pytest.mark.parametrize(
    ("method", "args", "body", "uncertain"),
    [
        ("health", (), [], False),
        ("health", (), {"status": []}, False),
        ("me", (), {"user": []}, False),
        ("chat", ("Q",), {**CHAT, "message": []}, True),
        ("chat", ("Q",), {**CHAT, "conversation_id": None}, True),
        ("chat", ("Q",), {**CHAT, "sources": [None]}, True),
        ("chat", ("Q",), {**CHAT, "workflow_request": []}, True),
        ("conversations", (), {"conversations": {}}, False),
        ("conversations", (), {"conversations": [{}]}, False),
        ("conversation", ("conversation-1",), {"conversation": SUMMARY, "messages": [None]}, False),
        ("conversation", ("conversation-1",), {"conversation": SUMMARY, "messages": [{}]}, False),
        ("requests", (), {"requests": ["wrong"]}, False),
        ("requests", (), {"requests": [{**WORKFLOW, "details": []}]}, False),
        ("requests", (), {"requests": [{**WORKFLOW, "type_label": None}]}, False),
        ("request", ("request-1",), {**DETAIL, "events": {}}, False),
        ("request", ("request-1",), {**DETAIL, "comments": [{}]}, False),
        (
            "conversation",
            ("conversation-1",),
            {**CONVERSATION, "conversation": {"id": "conversation-1"}},
            False,
        ),
        ("create_request", ({},), {"request": {}}, True),
        ("submit_request", ("request-1", {}), {"request": []}, True),
        ("cancel_request", ("request-1",), {"request": None}, True),
        ("feedback", ("Q", "A", 5), {"feedback": []}, True),
    ],
)
def test_malformed_response_shapes_raise_apierror(client_factory, method, args, body, uncertain):
    client, _ = client_factory(lambda _: httpx.Response(200, json=body))
    with pytest.raises(APIError) as error:
        getattr(client, method)(*args)
    assert error.value.status == 502
    assert error.value.uncertain is uncertain


def test_invalid_json_post_response_is_uncertain_and_not_retried(client_factory):
    client, calls = client_factory(lambda _: httpx.Response(200, text="<html>private</html>"))
    with pytest.raises(APIError) as error:
        client.chat("Q")
    assert error.value.status == 502
    assert error.value.uncertain
    assert len(calls) == 2


def test_stream_preserves_replace_and_whitespace_across_utf8_chunks(client_factory):
    events = [
        {"type": "start"},
        {"type": "token", "content": " Old\n"},
        {"type": "replace", "content": "New café\n"},
        {"type": "token", "content": " next"},
        {**COMPLETE, "workflow_request": WORKFLOW},
    ]
    raw = ("\r\n" + "\r\n\r\n".join(json.dumps(e, ensure_ascii=False) for e in events)).encode()
    stream = ChunkStream([raw[i : i + 1] for i in range(len(raw))])
    client, calls = client_factory(lambda _: stream_response(stream=stream))
    assert list(client.stream_chat("Question", "conversation-1")) == events
    assert stream.closed
    assert calls[-1].url.path == "/api/v1/chat/stream"
    assert calls[-1].headers["accept"] == "application/x-ndjson"
    assert json.loads(calls[-1].content) == {
        "messages": [{"role": "user", "content": "Question"}],
        "conversation_id": "conversation-1",
    }


@pytest.mark.parametrize(
    "message",
    [
        "The conversation could not be saved.",
        "The conversation could not be found.",
        "The request must include at least one user message.",
    ],
)
def test_stream_error_including_persistence_is_terminal(client_factory, message):
    events = [
        {"type": "start"},
        {"type": "token", "content": "Unsaved answer"},
        {"type": "error", "message": message},
        COMPLETE,
    ]
    response = stream_response(events)
    client, calls = client_factory(lambda _: response)
    assert list(client.stream_chat("Question")) == events[:3]
    assert response.is_closed
    assert len(calls) == 2


def test_unknown_stream_error_does_not_expose_diagnostics(client_factory):
    client, _ = client_factory(
        lambda _: stream_response(
            [{"type": "start"}, {"type": "error", "message": "secret-password internal path"}]
        )
    )
    event = list(client.stream_chat("Question"))[-1]
    assert event["type"] == "error"
    assert "secret-password" not in event["message"]


@pytest.mark.parametrize(
    "raw",
    [
        b"not JSON\n",
        b"[]\n",
        b"null\n",
        b"{}\n",
        b'{"type": []}\n',
        b'{"type": "start"}\n{"type": "start"}\n',
        b'{"type": "token", "content": "missing start"}\n',
        b'{"type": "start"}\n{"type": "token", "content": null}\n',
        b'{"type": "start"}\n{"type": "replace", "content": []}\n',
        b'{"type": "start"}\n{"type": "complete"}\n',
        b'{"type": "start"}\n{"type": "error", "message": {}}\n',
        b'{"type": "start"}\n{"type": "unrecognized"}\n',
        b'{"type": "start"}\n{"type": "token", "content": "partial"}',
        b'{"type": "start"}\n{"type": "token", "content": "\xff"}\n',
        b"",
        b" \r\n\n",
    ],
)
def test_invalid_or_incomplete_ndjson_fails_safely_and_closes(client_factory, raw):
    stream = ChunkStream([raw])
    client, calls = client_factory(lambda _: stream_response(stream=stream))
    with pytest.raises(APIError) as error:
        list(client.stream_chat("Question"))
    assert error.value.status == 502
    assert error.value.uncertain
    assert stream.closed
    assert len(calls) == 2


def test_non_ndjson_content_type_is_rejected(client_factory):
    client, _ = client_factory(lambda _: httpx.Response(200, json={"type": "start"}))
    with pytest.raises(APIError) as error:
        list(client.stream_chat("Question"))
    assert error.value.status == 502


def test_stream_read_timeout_is_uncertain_without_post_retry(client_factory):
    stream = ChunkStream([b'{"type":"start"}\n'], error=httpx.ReadTimeout)
    client, calls = client_factory(lambda _: stream_response(stream=stream))
    iterator = client.stream_chat("Question")
    assert next(iterator) == {"type": "start"}
    with pytest.raises(APIError) as error:
        next(iterator)
    assert error.value.status == 504
    assert error.value.uncertain
    assert stream.closed
    assert len(calls) == 2


def test_stream_401_is_retried_before_any_events(client_factory):
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(401)
        return stream_response([{"type": "start"}, COMPLETE])

    client, calls = client_factory(handler)
    assert list(client.stream_chat("Question")) == [{"type": "start"}, COMPLETE]
    assert len(auth_calls(calls)) == 2
    assert len(attempts) == 2


def test_abandoned_stream_can_be_closed_without_consuming_response(client_factory):
    stream = ChunkStream([b'{"type":"start"}\n', b'{"type":"token","content":"later"}\n'])
    client, _ = client_factory(lambda _: stream_response(stream=stream))
    iterator = client.stream_chat("Question")
    assert next(iterator) == {"type": "start"}
    assert not stream.closed
    iterator.close()
    assert stream.closed


@pytest.mark.parametrize(
    "id", ["../admin", ".", "..", "x/approve", "x?role=manager", "x%2fapprove", ""]
)
def test_ids_cannot_select_other_routes(client_factory, id):
    client, calls = client_factory(lambda _: pytest.fail("Invalid ID must not reach HTTP"))
    with pytest.raises(APIError) as error:
        client.request(id)
    assert error.value.status == 400
    assert calls == []


def test_close_is_idempotent_and_prevents_further_requests(client_factory):
    client, calls = client_factory(lambda _: pytest.fail("Closed client must not send HTTP"))
    client.close()
    client.close()
    with pytest.raises(APIError, match="closed"):
        client.me()
    assert calls == []


def test_apierror_positional_constructor_contract():
    error = APIError(503, "The answer was not confirmed.")
    assert error.status == 503
    assert error.detail == str(error) == "The answer was not confirmed."
    assert error.uncertain is False


def test_unicode_line_separators_are_content_not_ndjson_delimiters(client_factory):
    events = [{"type": "start"}, {"type": "token", "content": "one\u2028two\u2029three"}, COMPLETE]
    client, _ = client_factory(lambda _: stream_response(events))
    assert list(client.stream_chat("Question")) == events


def test_confirmed_http_persistence_failure_is_not_uncertain(client_factory):
    client, calls = client_factory(
        lambda _: httpx.Response(503, json={"detail": "The conversation could not be saved."})
    )
    with pytest.raises(APIError) as error:
        client.chat("Question")
    assert error.value.status == 503
    assert error.value.detail == "The conversation could not be saved."
    assert not error.value.uncertain
    assert len(calls) == 2


def test_expired_token_is_refreshed_once_for_concurrent_callers(client_factory, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(client_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    gate = Barrier(6)
    client, calls = client_factory(
        lambda _: httpx.Response(200, json={"user": USER}),
        login=lambda _: httpx.Response(200, json=login_body(expires_in=10)),
    )
    client.me()
    now[0] = 111.0

    def worker(_):
        gate.wait(timeout=5)
        return client.me()

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(worker, range(6))) == [{"user": USER}] * 6
    assert len(auth_calls(calls)) == 2


def test_refresh_cannot_switch_to_manager_identity(client_factory):
    issued = [0]

    def login(_):
        issued[0] += 1
        user = USER if issued[0] == 1 else {**USER, "role": "manager"}
        return httpx.Response(200, json=login_body(user=user))

    client, calls = client_factory(lambda _: httpx.Response(401), login=login)
    with pytest.raises(APIError) as error:
        client.requests()
    assert error.value.status == 403
    assert len(auth_calls(calls)) == 2
    assert len(calls) == 3


def test_login_read_timeout_does_not_mark_business_action_uncertain(client_factory):
    def fail(_):
        raise httpx.ReadTimeout("private authentication diagnostic")

    client, calls = client_factory(lambda _: pytest.fail("Login failed"), login=fail)
    with pytest.raises(APIError) as error:
        client.chat("Question")
    assert error.value.status == 504
    assert not error.value.uncertain
    assert len(calls) == 1


def test_configured_api_ignores_environment_proxies(client_factory, monkeypatch):
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    original_client = httpx.Client
    constructor_options = {}

    def capture_constructor(**options):
        constructor_options.update(options)
        return original_client(**options)

    monkeypatch.setattr(client_module.httpx, "Client", capture_constructor)
    client, calls = client_factory(
        lambda _: httpx.Response(200, json={"status": "ok"}),
        base_url="http://localhost:8000",
    )
    assert client.health() == {"status": "ok"}
    # MockTransport isolates this test from sockets; inspect the actual constructor
    # argument because a mock transport alone would bypass environment proxies.
    assert constructor_options["trust_env"] is False
    assert str(calls[0].url) == "http://localhost:8000/api/v1/health"


@pytest.mark.parametrize(
    "method,args,body,uncertain",
    [
        ("request", ("other-request",), DETAIL, False),
        ("submit_request", ("other-request", {}), {"request": WORKFLOW}, True),
        ("cancel_request", ("other-request",), {"request": WORKFLOW}, True),
        ("conversation", ("other-conversation",), CONVERSATION, False),
        ("chat", ("Follow up", "other-conversation"), CHAT, True),
    ],
)
def test_response_cannot_rebind_the_requested_resource(
    client_factory, method, args, body, uncertain
):
    client, calls = client_factory(lambda _: httpx.Response(200, json=body))
    with pytest.raises(APIError) as error:
        getattr(client, method)(*args)
    assert error.value.status == 502
    assert error.value.uncertain is uncertain
    assert len(calls) == 2


def test_stream_cannot_rebind_an_existing_conversation(client_factory):
    stream = stream_response([{"type": "start"}, COMPLETE])
    client, calls = client_factory(lambda _: stream)
    with pytest.raises(APIError) as error:
        list(client.stream_chat("Follow up", "other-conversation"))
    assert error.value.uncertain
    assert stream.is_closed
    assert len(calls) == 2


def test_foreign_employee_record_never_reaches_slack(client_factory):
    client, _ = client_factory(
        lambda _: httpx.Response(
            200, json={"requests": [{**WORKFLOW, "applicant": "another.employee"}]}
        )
    )
    with pytest.raises(APIError, match="invalid response"):
        client.requests()


@pytest.mark.parametrize(
    "backend_id", [None, "", 123, "not-a-uuid", "235D880C-7A1D-4315-8D60-F18D1C2DA720"]
)
def test_malformed_backend_identity_is_rejected(client_factory, backend_id):
    client, _ = client_factory(
        lambda _: httpx.Response(200, json={"user": USER, "backend_id": backend_id})
    )
    with pytest.raises(APIError, match="invalid response"):
        client.me()


def test_backend_identity_is_preserved_for_transport_state_binding(client_factory):
    body = {"user": USER, "backend_id": "235d880c-7a1d-4315-8d60-f18d1c2da720"}
    client, _ = client_factory(lambda _: httpx.Response(200, json=body))
    assert client.me() == body


def test_oversized_unterminated_ndjson_record_is_bounded_and_closed(client_factory):
    stream = ChunkStream([b" " * 65536] * 17)
    client, calls = client_factory(lambda _: stream_response(stream=stream))
    with pytest.raises(APIError) as error:
        list(client.stream_chat("Question"))
    assert error.value.uncertain
    assert stream.closed
    assert len(calls) == 2
