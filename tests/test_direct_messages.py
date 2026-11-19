import json
import ssl
from unittest.mock import Mock

import pytest

from integrations.direct_messages import DirectMessageTarget, DirectMessageTransport
from integrations.notification_transport import notification_payload

TOKENS = {"slack": "xoxb-only-a-mock-secret", "discord": "only.a.mock-token"}
USERS = {"slack": "U123ABC", "discord": "123456789"}
CHANNELS = {"slack": "D123ABC", "discord": "987654321"}


@pytest.fixture(autouse=True)
def no_live_provider_calls(monkeypatch):
    monkeypatch.setattr(
        "http.client.HTTPSConnection",
        Mock(side_effect=AssertionError("No live bot calls in tests")),
    )


def response(payload, status=200, headers=None):
    result = Mock(status=status)
    result.read.return_value = (
        json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
    )
    result.getheader.side_effect = (headers or {}).get
    return result


def opened(provider):
    if provider == "slack":
        return {
            "ok": True,
            "channel": {"id": CHANNELS[provider], "is_im": True, "user": USERS[provider]},
        }
    return {"id": CHANNELS[provider], "type": 1, "recipients": [{"id": USERS[provider]}]}


def sent(provider):
    if provider == "slack":
        return {"ok": True, "channel": CHANNELS[provider], "ts": "123456789.123"}
    return {"id": "555555555", "channel_id": CHANNELS[provider]}


def transport_with(*responses):
    connections = []
    for reply in responses:
        connection = Mock()
        connection.getresponse.return_value = reply
        connections.append(connection)
    factory = Mock(side_effect=connections)
    return DirectMessageTransport(timeout=7, connection_factory=factory), factory, connections


def deliver(transport, provider="slack", payload=None, identifier="event-1"):
    return transport.send(
        DirectMessageTarget(provider, TOKENS[provider]),
        USERS[provider],
        payload or notification_payload(provider, {"kind": "test"}, "https://example.test"),
        identifier,
    )


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_opens_and_verifies_one_person_dm_then_sends_with_private_route(provider):
    transport, factory, connections = transport_with(
        response(opened(provider)), response(sent(provider))
    )
    payload = notification_payload(provider, {"kind": "test"}, "https://example.test")
    payload.update(
        {
            "channel": "PUBLIC",
            "channel_id": "PUBLIC",
            "allowed_mentions": {"parse": ["everyone"]},
            "thread_ts": "public-thread",
        }
    )
    result = deliver(transport, provider, payload)
    assert result.delivered
    assert factory.call_count == 2
    for call in factory.call_args_list:
        assert call.args[0] == ("slack.com" if provider == "slack" else "discord.com")
        assert call.kwargs["timeout"] == 7
        assert call.kwargs["context"].check_hostname
        assert call.kwargs["context"].verify_mode == ssl.CERT_REQUIRED
    first, second = [json.loads(c.request.call_args.kwargs["body"]) for c in connections]
    assert first == (
        {"users": USERS[provider], "return_im": True}
        if provider == "slack"
        else {"recipient_id": USERS[provider]}
    )
    assert "PUBLIC" not in json.dumps(second)
    if provider == "slack":
        assert connections[1].request.call_args.args == ("POST", "/api/chat.postMessage")
        assert second["channel"] == CHANNELS[provider] and second["client_msg_id"]
        assert second["parse"] == "none" and not second["unfurl_links"]
    else:
        assert connections[1].request.call_args.args == (
            "POST",
            f"/api/v10/channels/{CHANNELS[provider]}/messages",
        )
        assert second["allowed_mentions"] == {"parse": []}
        assert second["enforce_nonce"] is True and len(second["nonce"]) <= 25
    for connection in connections:
        connection.set_debuglevel.assert_called_once_with(0)
        connection.close.assert_called_once()


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_retry_reuses_provider_deduplication_id(provider):
    transport, _, connections = transport_with(
        *[response(v) for v in [opened(provider), sent(provider), opened(provider), sent(provider)]]
    )
    assert deliver(transport, provider).delivered
    assert deliver(transport, provider).delivered
    key = "client_msg_id" if provider == "slack" else "nonce"
    assert (
        json.loads(connections[1].request.call_args.kwargs["body"])[key]
        == json.loads(connections[3].request.call_args.kwargs["body"])[key]
    )


@pytest.mark.parametrize(
    "provider,wrong",
    [
        (
            "slack",
            {"ok": True, "channel": {"id": "C123ABC", "is_im": False, "user": USERS["slack"]}},
        ),
        ("slack", {"ok": True, "channel": {"id": "D123ABC", "is_im": True, "user": "UOTHER"}}),
        ("slack", {"ok": True, "channel": {"id": "D123ABC"}}),
        ("discord", {"id": "987654321", "type": 0, "recipients": [{"id": USERS["discord"]}]}),
        (
            "discord",
            {
                "id": "987654321",
                "type": 3,
                "recipients": [{"id": USERS["discord"]}, {"id": "111111111"}],
            },
        ),
        ("discord", {"id": "987654321", "type": 1, "recipients": [{"id": "111111111"}]}),
        ("discord", {"id": "987654321", "type": 1}),
    ],
)
def test_public_group_wrong_or_unproven_recipient_never_receives_message(provider, wrong):
    transport, factory, _ = transport_with(response(wrong))
    assert deliver(transport, provider).error_code == "recipient_unavailable"
    assert factory.call_count == 1


@pytest.mark.parametrize("provider", ["slack", "discord"])
@pytest.mark.parametrize("stage", [0, 1])
@pytest.mark.parametrize(
    "status,body,code,retryable",
    [
        (429, {"retry_after": 31}, "rate_limited", True),
        (503, {}, "provider_unavailable", True),
        (302, {}, "bot_rejected", False),
        (401, {"error": "secret-details"}, "bot_rejected", False),
    ],
)
def test_both_provider_steps_bound_retries_without_echoing_errors(
    provider, stage, status, body, code, retryable
):
    replies = ([response(opened(provider))] if stage else []) + [
        response(body, status, {"Retry-After": "20"})
    ]
    transport, factory, _ = transport_with(*replies)
    result = deliver(transport, provider)
    assert result.error_code == code and result.retryable is retryable
    assert factory.call_count == stage + 1
    assert "secret-details" not in repr(result)
    if status == 429:
        assert result.retry_after == 31


@pytest.mark.parametrize("provider", ["slack", "discord"])
@pytest.mark.parametrize("stage", [0, 1])
@pytest.mark.parametrize("failure,code", [(TimeoutError, "timeout"), (OSError, "network")])
def test_network_errors_are_sanitized_at_either_step(provider, stage, failure, code):
    transport, factory, connections = transport_with(
        response(opened(provider)), response(sent(provider))
    )
    connections[stage].request.side_effect = failure(TOKENS[provider])
    result = deliver(transport, provider)
    assert result.error_code == code and result.retryable
    assert TOKENS[provider] not in repr(result)
    assert factory.call_count == stage + 1


@pytest.mark.parametrize(
    "provider,user",
    [
        ("slack", "UONE,UTWO"),
        ("slack", "C123ABC"),
        ("discord", "12345/elsewhere"),
        ("discord", "@everyone"),
    ],
)
def test_invalid_recipients_do_not_make_network_requests(provider, user):
    factory = Mock()
    result = DirectMessageTransport(connection_factory=factory).send(
        DirectMessageTarget(provider, TOKENS[provider]), user, {}, "job"
    )
    assert result.error_code == "recipient_unavailable"
    factory.assert_not_called()


@pytest.mark.parametrize(
    "provider,token",
    [
        ("slack", "xoxp-user-token"),
        ("slack", "https://hooks.slack.com/x"),
        ("discord", "https://discord.com/api/webhooks/x"),
        ("discord", "bad\r\nAuthorization:bad"),
        ("other", "mock"),
    ],
)
def test_bad_token_configuration_and_webhooks_never_fall_back(provider, token):
    factory = Mock()
    target = DirectMessageTarget(provider, token)
    assert not target.configured and token not in repr(target)
    result = DirectMessageTransport(connection_factory=factory).send(target, "123456", {}, "job")
    assert result.error_code == "configuration"
    factory.assert_not_called()


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_confirmed_delivery_survives_close_errors(provider):
    transport, _, connections = transport_with(response(opened(provider)), response(sent(provider)))
    for connection in connections:
        connection.close.side_effect = OSError(TOKENS[provider])
    assert deliver(transport, provider).delivered


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_wrong_acknowledgement_is_not_success(provider):
    transport, _, _ = transport_with(
        response(opened(provider)),
        response(
            {"ok": True, "channel": "WRONG", "ts": "1", "id": "123456", "channel_id": "WRONG"}
        ),
    )
    assert deliver(transport, provider).error_code == "unexpected_response"


@pytest.mark.parametrize("stage", [0, 1])
def test_discord_cannot_dm_user_is_a_permanent_safe_error(stage):
    replies = ([response(opened("discord"))] if stage else []) + [
        response({"code": 50007, "message": "secret provider details"}, 403)
    ]
    transport, factory, _ = transport_with(*replies)
    result = deliver(transport, "discord")
    assert result.error_code == "direct_messages_disabled" and not result.retryable
    assert not result.delivered and "secret provider details" not in repr(result)
    assert factory.call_count == stage + 1


def test_oversized_response_is_not_parsed_or_forwarded():
    reply = response(b" " * 65537)
    transport, factory, _ = transport_with(reply)
    assert deliver(transport).error_code == "unexpected_response"
    reply.read.assert_called_once_with(65537)
    assert factory.call_count == 1
