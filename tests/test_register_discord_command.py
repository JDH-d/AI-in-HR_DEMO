import json
import ssl
from unittest.mock import Mock

import pytest

from core import settings
from scripts.register_discord_command import (
    RegistrationError,
    command_payload,
    main,
    register_command,
)

APPLICATION_ID = "123456789012345678"
TOKEN = "test-bot-token-never-print-me"


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    monkeypatch.setattr(
        "http.client.HTTPSConnection",
        Mock(side_effect=AssertionError("Real requests are forbidden")),
    )
    monkeypatch.setattr(settings, "DISCORD_APPLICATION_ID", APPLICATION_ID)
    monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", TOKEN)


def connection(status=201, body=None):
    response = Mock(status=status)
    response.read.return_value = (
        body
        if body is not None
        else json.dumps(
            {
                "id": "987654321098765432",
                "application_id": APPLICATION_ID,
                "name": "peopleflow",
                "type": 1,
            }
        ).encode()
    )
    client = Mock()
    client.getresponse.return_value = response
    return client, Mock(return_value=client)


@pytest.mark.parametrize("arguments", [[], ["--preview"]])
def test_preview_is_offline_and_does_not_print_the_token(arguments, capsys):
    assert main(arguments) == 0
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err
    assert "No request was sent" in output.out
    assert (
        "POST https://discord.com/api/v10/applications/" + APPLICATION_ID + "/commands"
        in output.out
    )
    assert '"code"' in output.out


def test_preview_without_config_shows_placeholder_not_credentials(monkeypatch, capsys):
    monkeypatch.setattr(settings, "DISCORD_APPLICATION_ID", "")
    monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", "")
    assert main(["--preview"]) == 0
    assert "<DISCORD_APPLICATION_ID>" in capsys.readouterr().out


@pytest.mark.parametrize("status", [200, 201])
def test_registration_upserts_one_command_without_bulk_replacing_others(status):
    client, factory = connection(status)
    register_command(APPLICATION_ID, TOKEN, connection_factory=factory)
    factory.assert_called_once()
    assert factory.call_args.args == ("discord.com",)
    assert factory.call_args.kwargs["timeout"] == 10
    context = factory.call_args.kwargs["context"]
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    client.set_debuglevel.assert_called_once_with(0)
    client.request.assert_called_once()
    call = client.request.call_args
    assert call.args == ("POST", f"/api/v10/applications/{APPLICATION_ID}/commands")
    payload = json.loads(call.kwargs["body"])
    assert payload == command_payload() and isinstance(payload, dict)
    assert payload["name"] == "peopleflow" and payload["type"] == 1
    assert payload["contexts"] == [0, 1] and payload["integration_types"] == [0]
    (subcommand,) = payload["options"]
    assert subcommand["name"] == "link" and subcommand["type"] == 1
    (code,) = subcommand["options"]
    assert code["name"] == "code" and code["type"] == 3 and code["required"] is True
    assert call.kwargs["headers"]["Authorization"] == "Bot " + TOKEN
    client.close.assert_called_once()


@pytest.mark.parametrize("status", [302, 400, 401, 403, 429, 500])
def test_http_failures_are_sanitized_and_never_redirect_or_retry(status):
    client, factory = connection(status, TOKEN.encode())
    with pytest.raises(RegistrationError) as failure:
        register_command(APPLICATION_ID, TOKEN, connection_factory=factory)
    assert TOKEN not in str(failure.value)
    client.request.assert_called_once()
    client.getresponse.return_value.read.assert_not_called()
    client.close.assert_called_once()


@pytest.mark.parametrize("failure_type", [TimeoutError, OSError, RuntimeError])
def test_network_error_text_cannot_expose_credentials(failure_type):
    client, factory = connection()
    client.request.side_effect = failure_type(TOKEN)
    with pytest.raises(RegistrationError) as failure:
        register_command(APPLICATION_ID, TOKEN, connection_factory=factory)
    assert TOKEN not in str(failure.value)
    client.close.assert_called_once()


@pytest.mark.parametrize(
    "application_id,token",
    [
        ("", TOKEN),
        ("../../bad", TOKEN),
        (TOKEN, TOKEN),
        (APPLICATION_ID, ""),
        (APPLICATION_ID, "secret\r\nInjected: yes"),
    ],
)
def test_invalid_config_does_not_open_a_connection(application_id, token):
    factory = Mock()
    with pytest.raises(RegistrationError) as failure:
        register_command(application_id, token, connection_factory=factory)
    assert TOKEN not in str(failure.value)
    factory.assert_not_called()


def test_only_register_flag_performs_post_and_reports_safe_success(monkeypatch, capsys):
    client, factory = connection()
    monkeypatch.setattr("http.client.HTTPSConnection", factory)
    assert main(["--register"]) == 0
    client.request.assert_called_once()
    output = capsys.readouterr()
    assert "Registered /peopleflow link" in output.out
    assert TOKEN not in output.out + output.err


@pytest.mark.parametrize(
    "body",
    [TOKEN.encode(), b"[]", b'{"id":"1","name":"other"}', b"x" * 65537],
    ids=["non-json", "array", "wrong-command", "oversized"],
)
def test_malformed_success_response_is_not_reported_as_success(body):
    client, factory = connection(201, body)
    with pytest.raises(RegistrationError) as failure:
        register_command(APPLICATION_ID, TOKEN, connection_factory=factory)
    assert TOKEN not in str(failure.value)
    client.getresponse.return_value.read.assert_called_once_with(65537)


def test_cli_error_is_sanitized_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr("http.client.HTTPSConnection", Mock(side_effect=RuntimeError(TOKEN)))
    assert main(["--register"]) == 1
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err
    assert "Traceback" not in output.err
