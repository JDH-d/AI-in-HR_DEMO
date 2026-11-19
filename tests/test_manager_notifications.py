"""Delivery follows the assigned account, including additional demo managers."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from domain.notifications import IntegrationError
from integrations.notification_transport import DeliveryResult
from services.auth_service import DEMO_IDENTITIES, DemoIdentity
from services.notification_service import NotificationService
from services.workflow_service import WorkflowService


@pytest.fixture
def manager_notifications(tmp_path, monkeypatch, provider):
    monkeypatch.setattr(
        "http.client.HTTPSConnection",
        Mock(side_effect=AssertionError("Real notifications are forbidden")),
    )
    other = DemoIdentity("manager.other", "other_manager", "Other Manager", "manager")
    monkeypatch.setitem(DEMO_IDENTITIES, other.username, other)
    workflow = WorkflowService(str(tmp_path / "workflow.db"))
    transport = Mock()
    transport.send.return_value = DeliveryResult(delivered=True)
    clock = Mock(return_value=1000.0)
    service = NotificationService(
        workflow.store.db_path,
        slack_token="xoxb-synthetic-token",
        slack_signing_secret="synthetic-signing-secret",
        slack_team_id="TTEST",
        discord_token="synthetic.discord.token",
        discord_application_id="123456",
        discord_public_key="a" * 64,
        discord_connection_mode="http",
        app_url="https://peopleflow.example.test",
        transport=transport,
        clock=clock,
    )
    destinations = {
        "slack": {
            "employee.demo": "UEMPLOYEE",
            "manager.demo": "UMANAGER",
            other.id: "UOTHER",
        },
        "discord": {
            "employee.demo": "111111",
            "manager.demo": "222222",
            other.id: "333333",
        },
    }
    scope = "TTEST" if provider == "slack" else "123456"
    for user_id, external_id in destinations[provider].items():
        code = service.accounts.issue(provider, user_id, clock())["code"]
        service.accounts.claim_code(provider, code, external_id, scope, clock())
        challenge = service.accounts.connection(provider, user_id, clock())["pending"]
        service.accounts.confirm(provider, user_id, challenge["challenge_id"], clock())
    service.set_enabled(provider, True, 0, "admin.demo")
    return SimpleNamespace(
        workflow=workflow,
        service=service,
        transport=transport,
        clock=clock,
        destinations=destinations,
        other=other,
    )


def submit(system, manager="manager.demo"):
    draft = system.workflow.create_structured_draft(
        request_type="document",
        applicant="employee.demo",
        approver=manager,
        title="Synthetic request",
        comment="Relevant synthetic information",
    )
    return system.workflow.confirm_draft(
        draft["id"],
        draft["applicant"],
        {},
        revision=draft["revision"],
    )


def deliver(system, provider):
    system.clock.return_value += 2
    system.service.run_once(provider)


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_reassignment_delivers_to_new_verified_manager_never_previous_one(
    manager_notifications,
    provider,
):
    system = manager_notifications
    request = submit(system)
    system.service.store.collect(provider, system.clock())
    request = system.workflow.assign(
        request["id"],
        "manager.demo",
        system.other.id,
        "Transfer review to the available manager",
        request["revision"],
    )
    # The first claim cancels the obsolete manager job; the next delivers assignment.
    deliver(system, provider)
    deliver(system, provider)
    system.transport.send.assert_called_once()
    assert system.transport.send.call_args.args[1] == system.destinations[provider][system.other.id]
    assert request["id"] in str(system.transport.send.call_args.args[2])
    assert "Request assigned to you" in str(system.transport.send.call_args.args[2])
    with system.service.store.transaction() as conn:
        statuses = [
            row[0]
            for row in conn.execute(
                "SELECT status FROM notification_jobs WHERE provider=? ORDER BY rowid",
                (provider,),
            )
        ]
    assert statuses == ["cancelled", "delivered"]
    assert (
        system.workflow.get_for_user(request["id"], "employee.demo")["approver"] == system.other.id
    )


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_employee_reply_routes_to_actual_manager_but_decision_is_not_pushed_to_employee(
    manager_notifications,
    provider,
):
    system = manager_notifications
    request = submit(system, system.other.id)
    deliver(system, provider)
    for action, actor, role in (
        ("start_review", system.other.id, "manager"),
        ("request_information", system.other.id, "manager"),
        ("provide_information", "employee.demo", "employee"),
        ("approve", system.other.id, "manager"),
    ):
        request = system.workflow.act(
            request["id"],
            actor,
            role,
            action,
            request["revision"],
            comment="Relevant explanation for this request",
            basis="Objective criterion",
            fair_review_confirmed=True,
        )
        deliver(system, provider)
    assert [call.args[1] for call in system.transport.send.call_args_list] == [
        system.destinations[provider][system.other.id],
        system.destinations[provider]["employee.demo"],
        system.destinations[provider][system.other.id],
    ]
    assert request["status"] == "approved"


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_personal_test_targets_additional_manager_and_admin_default_still_works(
    manager_notifications,
    provider,
):
    system = manager_notifications
    system.service.test_notification(provider, "manager", system.other.id)
    deliver(system, provider)
    assert system.transport.send.call_args.args[1] == system.destinations[provider][system.other.id]
    system.service.test_notification(provider)
    deliver(system, provider)
    assert system.transport.send.call_args.args[1] == system.destinations[provider]["manager.demo"]
    assert system.transport.send.call_count == 2
    assert system.workflow.list_for_user("employee.demo") == []


@pytest.mark.parametrize("provider", ["slack", "discord"])
@pytest.mark.parametrize("change", ["remove", "demote"])
def test_current_identity_and_role_are_checked_again_before_delivery(
    manager_notifications,
    provider,
    change,
    monkeypatch,
):
    system = manager_notifications
    request = submit(system, system.other.id)
    system.service.store.collect(provider, system.clock())
    if change == "remove":
        monkeypatch.delitem(DEMO_IDENTITIES, system.other.username)
    else:
        monkeypatch.setitem(
            DEMO_IDENTITIES,
            system.other.username,
            replace(system.other, role="employee"),
        )
    deliver(system, provider)
    system.transport.send.assert_not_called()
    with system.service.store.transaction() as conn:
        job = conn.execute(
            "SELECT status,error_code FROM notification_jobs WHERE provider=?",
            (provider,),
        ).fetchone()
    assert tuple(job) == ("cancelled", "recipient_unavailable")
    assert system.workflow.get_for_user(request["id"], "employee.demo")["status"] == "submitted"


@pytest.mark.parametrize("provider", ["slack", "discord"])
@pytest.mark.parametrize(
    "audience,recipient",
    [
        ("manager", "employee.demo"),
        ("employee", "manager.other"),
        ("manager", "unknown.manager"),
        ("manager", ""),
        ("knowledge_admin", "admin.demo"),
    ],
)
def test_personal_test_rejects_unknown_or_mismatched_account_without_fallback(
    manager_notifications,
    provider,
    audience,
    recipient,
):
    system = manager_notifications
    with pytest.raises(IntegrationError, match="recipient is not available"):
        system.service.test_notification(provider, audience, recipient)
    system.transport.send.assert_not_called()
    with system.service.store.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notification_jobs").fetchone()[0] == 0
