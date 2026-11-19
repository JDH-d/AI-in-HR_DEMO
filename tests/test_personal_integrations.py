"""Signed provider callbacks and authenticated account linking, with no live delivery."""

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import app
from integrations.notification_transport import DeliveryResult
from services.auth_service import DEMO_IDENTITIES
from services.notification_service import NotificationService
from services.runtime import get_runtime
from services.workflow_service import WorkflowService
from storage.personal_notification_store import PersonalNotificationStore

PERSONAL = "/api/v1/me/integrations"
SLACK_CALLBACK = "/api/v1/integrations/slack/commands"
DISCORD_CALLBACK = "/api/v1/integrations/discord/interactions"
SLACK_SECRET = "synthetic-signing-secret"
SLACK_TEAM = "TTEST123"
DISCORD_APP = "111111111"
REMOTE_IDS = {"slack": "UEMP123", "discord": "123456789"}
OTHER_REMOTE_IDS = {"slack": "UMAN123", "discord": "223456789"}


@pytest.fixture
def linked_system(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "http.client.HTTPSConnection",
        Mock(side_effect=AssertionError("Live provider calls are forbidden")),
    )
    workflow = WorkflowService(str(tmp_path / "workflow.db"))
    private = Ed25519PrivateKey.generate()
    clock = Mock(return_value=1000.0)
    transport = Mock()
    transport.send.return_value = DeliveryResult(delivered=True)
    service = NotificationService(
        workflow.store.db_path,
        slack_token="xoxb-synthetic-bot-token",
        slack_signing_secret=SLACK_SECRET,
        slack_team_id=SLACK_TEAM,
        discord_token="synthetic.discord.token",
        discord_public_key=private.public_key().public_bytes_raw().hex(),
        discord_application_id=DISCORD_APP,
        app_url="https://peopleflow.example.test",
        transport=transport,
        clock=clock,
    )
    runtime = get_runtime()
    auth = {
        role: {"Authorization": "Bearer " + runtime.auth_service.issue_token(identity)}
        for role, identity in DEMO_IDENTITIES.items()
    }
    with (
        patch.object(runtime, "notification_service", service),
        patch.object(service, "start"),
        patch.object(service, "stop", new=AsyncMock()),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        yield SimpleNamespace(
            client=client,
            service=service,
            clock=clock,
            transport=transport,
            private=private,
            auth=auth,
            workflow=workflow,
        )


def state(system, role, provider):
    response = system.client.get(PERSONAL, headers=system.auth[role])
    assert response.status_code == 200
    return next(item for item in response.json()["items"] if item["provider"] == provider)


def issue(system, role, provider):
    response = system.client.post(PERSONAL + f"/{provider}/link-code", headers=system.auth[role])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()["code"]


def slack(system, fields=None, *, raw=None, timestamp=None, valid=True):
    body = raw if raw is not None else urlencode(fields or {}).encode()
    stamp = str(int(system.clock())) if timestamp is None else timestamp
    signature = (
        "v0="
        + hmac.new(
            SLACK_SECRET.encode(), b"v0:" + stamp.encode() + b":" + body, hashlib.sha256
        ).hexdigest()
    )
    return system.client.post(
        SLACK_CALLBACK,
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": stamp,
            "X-Slack-Signature": signature if valid else "v0=" + "0" * 64,
        },
    )


def discord(system, data=None, *, raw=None, timestamp=None, valid=True):
    body = raw if raw is not None else json.dumps(data).encode()
    stamp = str(int(system.clock())) if timestamp is None else timestamp
    signature = system.private.sign(stamp.encode() + body).hex()
    return system.client.post(
        DISCORD_CALLBACK,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature-Timestamp": stamp,
            "X-Signature-Ed25519": signature if valid else "0" * 128,
        },
    )


def command_data(code, user_id=None):
    return {
        "id": "333333333",
        "application_id": DISCORD_APP,
        "type": 2,
        "user": {"id": user_id or REMOTE_IDS["discord"]},
        "data": {
            "name": "peopleflow",
            "options": [
                {
                    "name": "link",
                    "type": 1,
                    "options": [{"name": "code", "type": 3, "value": code}],
                },
            ],
        },
    }


def claim(system, provider, code, user_id=None):
    if provider == "slack":
        return slack(
            system,
            {
                "team_id": SLACK_TEAM,
                "user_id": user_id or REMOTE_IDS[provider],
                "command": "/peopleflow",
                "text": "link " + code,
                "role": "manager",
                "channel_id": "CPUBLIC",
            },
        )
    data = command_data(code, user_id)
    data["member"] = {"user": data.pop("user"), "roles": ["manager"]}
    data["guild_id"] = "444444444"
    return discord(system, data)


def confirm(system, role, provider, challenge=None):
    challenge = challenge or state(system, role, provider)["pending"]["challenge_id"]
    return system.client.post(
        PERSONAL + f"/{provider}/confirm",
        headers=system.auth[role],
        json={"challenge_id": challenge},
    )


def assert_private(provider, response):
    assert response.status_code == 200, response.text
    if provider == "slack":
        assert response.json()["response_type"] == "ephemeral"
    else:
        assert response.json()["type"] == 4
        assert response.json()["data"]["flags"] == 64
        assert response.json()["data"]["allowed_mentions"] == {"parse": []}


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("GET", PERSONAL, None),
        ("POST", PERSONAL + "/slack/link-code", None),
        ("POST", PERSONAL + "/slack/confirm", {"challenge_id": "a" * 32}),
        ("DELETE", PERSONAL + "/slack", None),
        ("POST", PERSONAL + "/slack/test", None),
    ],
)
def test_personal_endpoints_require_participant_identity(linked_system, method, path, payload):
    system = linked_system
    assert system.client.request(method, path, json=payload).status_code == 401
    response = system.client.request(
        method, path, headers=system.auth["knowledge_admin"], json=payload
    )
    assert response.status_code == 403
    system.transport.send.assert_not_called()


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_two_step_link_uses_app_role_only_and_is_private(linked_system, provider):
    system = linked_system
    code = issue(system, "employee", provider)
    assert not state(system, "employee", provider)["connected"]
    response = claim(system, provider, code)
    assert_private(provider, response)
    assert code not in response.text
    pending = state(system, "employee", provider)
    assert (
        not pending["connected"] and pending["pending"]["external_user_id"] == REMOTE_IDS[provider]
    )
    assert system.service.destination(provider, "employee.demo") is None
    assert system.service.destination(provider, "manager.demo") is None
    assert state(system, "manager", provider)["pending"] is None
    assert (
        confirm(system, "manager", provider, pending["pending"]["challenge_id"]).status_code == 400
    )
    assert confirm(system, "employee", provider).status_code == 200
    assert state(system, "employee", provider)["connected"]
    assert not state(system, "manager", provider)["connected"]
    assert (
        system.service.destination(provider, "employee.demo")["external_user_id"]
        == REMOTE_IDS[provider]
    )
    system.transport.send.assert_not_called()
    assert system.workflow.list_for_user("employee.demo") == []


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_code_hash_and_confirmed_link_survive_restart_without_replaying_codes(
    linked_system, provider
):
    system = linked_system
    code = issue(system, "employee", provider)
    with system.service.accounts.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM personal_link_challenges WHERE provider=?", (provider,)
        ).fetchone()
        assert row["code_hash"] == hashlib.sha256(code.encode()).hexdigest()
        assert code not in repr(tuple(row))
    assert_private(provider, claim(system, provider, code))
    challenge = state(system, "employee", provider)["pending"]["challenge_id"]
    assert_private(provider, claim(system, provider, code))
    assert state(system, "employee", provider)["pending"]["challenge_id"] == challenge
    assert confirm(system, "employee", provider, challenge).status_code == 200
    assert confirm(system, "employee", provider, challenge).status_code == 200
    restarted = PersonalNotificationStore(system.workflow.store.db_path)
    restarted.initialize()
    assert (
        restarted.destination(provider, "employee.demo")["external_user_id"] == REMOTE_IDS[provider]
    )
    assert_private(provider, claim(system, provider, code, OTHER_REMOTE_IDS[provider]))
    assert (
        restarted.destination(provider, "employee.demo")["external_user_id"] == REMOTE_IDS[provider]
    )
    with restarted.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM personal_notification_links").fetchone()[0] == 1


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_same_remote_account_cannot_be_employee_and_manager(linked_system, provider):
    system = linked_system
    employee_code = issue(system, "employee", provider)
    manager_code = issue(system, "manager", provider)
    claim(system, provider, employee_code)
    claim(system, provider, manager_code)
    # Both may prove their identity while pending; the transactional confirmation is exclusive.
    assert confirm(system, "employee", provider).status_code == 200
    assert confirm(system, "manager", provider).status_code == 409
    assert not state(system, "manager", provider)["connected"]
    result = claim(system, provider, manager_code)
    assert_private(provider, result)
    assert "another" in result.text and "separate" in result.text
    system.transport.send.assert_not_called()


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_expired_or_superseded_link_code_cannot_bind_an_account(linked_system, provider):
    system = linked_system
    old = issue(system, "employee", provider)
    assert (
        system.client.post(
            PERSONAL + f"/{provider}/link-code", headers=system.auth["employee"]
        ).status_code
        == 429
    )
    system.clock.return_value += 31
    current = issue(system, "employee", provider)
    assert current != old
    invalid = claim(system, provider, old)
    assert_private(provider, invalid)
    assert "invalid or expired" in invalid.text
    claim(system, provider, current)
    challenge = state(system, "employee", provider)["pending"]["challenge_id"]
    system.clock.return_value += 601
    expired = claim(system, provider, current)
    assert_private(provider, expired)
    assert "invalid or expired" in expired.text
    assert confirm(system, "employee", provider, challenge).status_code == 400
    assert not state(system, "employee", provider)["connected"]


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_disconnect_invalidates_old_codes_and_affects_only_caller(linked_system, provider):
    system = linked_system
    code = issue(system, "employee", provider)
    claim(system, provider, code)
    confirm(system, "employee", provider)
    manager_code = issue(system, "manager", provider)
    claim(system, provider, manager_code, OTHER_REMOTE_IDS[provider])
    confirm(system, "manager", provider)
    result = system.client.delete(PERSONAL + f"/{provider}", headers=system.auth["employee"])
    assert result.status_code == 200
    assert not state(system, "employee", provider)["connected"]
    assert state(system, "manager", provider)["connected"]
    assert "invalid or expired" in claim(system, provider, code).text


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_changed_provider_scope_requires_new_proof(linked_system, provider):
    system = linked_system
    code = issue(system, "employee", provider)
    claim(system, provider, code)
    challenge = state(system, "employee", provider)["pending"]["challenge_id"]
    if provider == "slack":
        system.service.slack_team_id = "TOTHER123"
    else:
        system.service.discord_application_id = "999999999"
    assert confirm(system, "employee", provider, challenge).status_code in {400, 409}
    assert system.service.accounts.destination(provider, "employee.demo") is None


def test_slack_rejects_forged_stale_wrong_workspace_and_duplicate_fields(linked_system):
    system = linked_system
    code = issue(system, "employee", "slack")
    fields = {
        "team_id": SLACK_TEAM,
        "user_id": REMOTE_IDS["slack"],
        "command": "/peopleflow",
        "text": "link " + code,
    }
    assert slack(system, fields, valid=False).status_code == 401
    assert slack(system, fields, timestamp="699").status_code == 401
    assert slack(system, {**fields, "team_id": "TOTHER"}).status_code == 403
    assert slack(system, raw=urlencode(fields).encode() + b"&user_id=UOTHER").status_code == 400
    assert not state(system, "employee", "slack")["connected"]
    assert state(system, "employee", "slack")["pending"] is None


def test_discord_requires_signature_application_and_valid_ping(linked_system):
    system = linked_system
    data = {"type": 1, "application_id": DISCORD_APP}
    assert discord(system, data, valid=False).status_code == 401
    assert discord(system, data, timestamp="699").status_code == 401
    assert discord(system, {**data, "application_id": "999999999"}).status_code == 403
    response = discord(system, data)
    assert response.status_code == 200 and response.json() == {"type": 1}
    system.transport.send.assert_not_called()


@pytest.mark.parametrize("body", [b"{", b"null", b"[]", b'"text"', b"123"])
def test_discord_bad_json_and_top_level_shapes_return_400(linked_system, body):
    assert discord(linked_system, raw=body).status_code == 400


@pytest.mark.parametrize(
    "field,value",
    [
        ("member", [1]),
        ("member", "bad"),
        ("member", True),
        ("user", [1]),
        ("data", [1]),
        ("data", "bad"),
    ],
)
def test_discord_malformed_nested_shapes_never_return_500(linked_system, field, value):
    data = command_data("unused")
    data[field] = value
    response = discord(linked_system, data)
    assert response.status_code == 400


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_link_and_confirm_do_not_accept_role_or_destination_overrides(linked_system, provider):
    system = linked_system
    code = issue(system, "employee", provider)
    claim(system, provider, code)
    challenge = state(system, "employee", provider)["pending"]["challenge_id"]
    response = system.client.post(
        PERSONAL + f"/{provider}/confirm",
        headers=system.auth["employee"],
        json={"challenge_id": challenge, "role": "manager", "secret": code},
    )
    assert response.status_code == 422 and code not in response.text
    assert not state(system, "employee", provider)["connected"]
    assert not state(system, "manager", provider)["connected"]


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_personal_test_can_only_queue_to_current_user(linked_system, provider):
    system = linked_system
    system.service.set_enabled(provider, True, 0, "admin.demo")
    assert (
        system.client.post(
            PERSONAL + f"/{provider}/test", headers=system.auth["employee"]
        ).status_code
        == 400
    )
    code = issue(system, "employee", provider)
    claim(system, provider, code)
    confirm(system, "employee", provider)
    response = system.client.post(
        PERSONAL + f"/{provider}/test",
        headers=system.auth["employee"],
        json={"audience": "manager", "recipient_id": "manager.demo"},
    )
    assert response.status_code == 202
    system.service.run_once(provider)
    system.transport.send.assert_called_once()
    assert system.transport.send.call_args.args[1] == REMOTE_IDS[provider]
    assert "Employee" in json.dumps(system.transport.send.call_args.args[2])
    assert system.workflow.list_for_user("employee.demo") == []


def test_payload_size_limits_precede_signature_parsing(linked_system):
    oversized = b"x" * 32769
    assert slack(linked_system, raw=oversized).status_code == 413
    assert discord(linked_system, raw=oversized).status_code == 413


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_confirmed_connection_can_be_removed_after_provider_scope_changes(linked_system, provider):
    system = linked_system
    code = issue(system, "employee", provider)
    assert claim(system, provider, code).status_code == 200
    assert confirm(system, "employee", provider).status_code == 200
    if provider == "slack":
        system.service.slack_team_id = "TOTHER"
    else:
        system.service.discord_application_id = "999999999"
    view = state(system, "employee", provider)
    assert not view["connected"]
    assert view["external_user_id"] == REMOTE_IDS[provider]
    assert "Disconnect" in view["connection_error"]
    assert system.service.destination(provider, "employee.demo") is None
    response = system.client.delete(PERSONAL + f"/{provider}", headers=system.auth["employee"])
    assert response.status_code == 200
    assert state(system, "employee", provider)["external_user_id"] is None
    assert issue(system, "employee", provider)
