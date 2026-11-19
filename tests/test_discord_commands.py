"""Both authenticated Discord transports must preserve account ownership and stored data."""

import pytest

from domain.notifications import IntegrationError
from integrations.discord_commands import DiscordCommandError, process_discord_interaction
from services.auth_service import DEMO_IDENTITIES
from services.notification_service import NotificationService
from services.workflow_service import WorkflowService


def service_at(path):
    WorkflowService(str(path))
    return NotificationService(
        path,
        discord_token="synthetic.discord.token",
        discord_application_id="111111111",
        app_url="http://127.0.0.1:5173",
        clock=lambda: 1000,
    )


def command(code, user_id="123456789", **overrides):
    return {
        "application_id": "111111111",
        "type": 2,
        "member": {"user": {"id": user_id}, "roles": ["manager"]},
        "data": {
            "name": "peopleflow",
            "options": [{"name": "link", "options": [{"name": "code", "value": code}]}],
        },
        **overrides,
    }


def pending(service, role):
    return service.accounts.connection("discord", DEMO_IDENTITIES[role].id, 1000)["pending"]


def test_gateway_link_requires_web_owner_confirmation_and_survives_restart(tmp_path):
    path = tmp_path / "workflow.db"
    service = service_at(path)
    employee, manager = DEMO_IDENTITIES["employee"], DEMO_IDENTITIES["manager"]
    code = service.link_code("discord", employee)["code"]
    payload = command(code)
    first = process_discord_interaction(service, payload)
    assert process_discord_interaction(service, payload) == first
    assert first["data"]["flags"] == 64
    assert first["data"]["allowed_mentions"] == {"parse": []}
    assert service.destination("discord", employee.id) is None
    challenge_id = pending(service, "employee")["challenge_id"]
    with pytest.raises(IntegrationError):
        service.confirm_connection("discord", manager, challenge_id)
    service.confirm_connection("discord", employee, challenge_id)
    restarted = service_at(path)
    restarted.confirm_connection("discord", employee, challenge_id)
    assert restarted.destination("discord", employee.id)["external_user_id"] == "123456789"
    assert restarted.destination("discord", manager.id) is None
    # A Discord role or a replay cannot grant the application's Manager role.
    assert employee.role == "employee"
    manager_code = restarted.link_code("discord", manager)["code"]
    reply = process_discord_interaction(restarted, command(manager_code))
    assert "another application user" in reply["data"]["content"]
    assert pending(restarted, "manager") is None
    process_discord_interaction(restarted, command(manager_code, "223456789"))
    restarted.confirm_connection("discord", manager, pending(restarted, "manager")["challenge_id"])
    assert restarted.destination("discord", manager.id)["external_user_id"] == "223456789"


@pytest.mark.parametrize(
    "change",
    [
        {"application_id": "999999999"},
        {"type": 3},
        {"member": "invalid"},
        {"member": {}, "user": {"id": "not-a-user"}},
        {"data": {"name": "approve", "options": []}},
    ],
)
def test_invalid_commands_cannot_claim_account(tmp_path, change):
    service = service_at(tmp_path / "workflow.db")
    code = service.link_code("discord", DEMO_IDENTITIES["employee"])["code"]
    with pytest.raises(DiscordCommandError):
        process_discord_interaction(service, command(code, **change))
    assert pending(service, "employee") is None


def test_gateway_configuration_never_bypasses_http_signature_check(tmp_path):
    service = service_at(tmp_path / "workflow.db")
    assert service.configured("discord")
    assert not service.verify_command("discord", b"{}", "1000", "")


def test_expired_and_malformed_link_codes_are_private_safe_errors(tmp_path):
    service = service_at(tmp_path / "workflow.db")
    code = service.link_code("discord", DEMO_IDENTITIES["employee"])["code"]
    service.clock = lambda: 1700
    result = process_discord_interaction(service, command(code))
    assert "expired" in result["data"]["content"]
    assert result["data"]["flags"] == 64
    result = process_discord_interaction(service, command("@everyone"))
    assert "Generate a link code" in result["data"]["content"]
