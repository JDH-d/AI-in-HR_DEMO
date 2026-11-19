import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import app
from domain.notifications import IntegrationError, IntegrationUnavailable
from integrations.direct_messages import DirectMessageTransport
from integrations.notification_transport import (
    DeliveryResult,
    public_app_url,
)
from services.auth_service import DEMO_IDENTITIES
from services.notification_service import NotificationService
from services.runtime import get_runtime
from services.workflow_service import WorkflowService

SLACK = "https://hooks.slack.com/services/TTEST/BTEST/only-a-mock-secret"
DISCORD = "https://discord.com/api/webhooks/123456/only-a-mock-secret"
APP_URL = "https://peopleflow.example.test"
BOT_CONFIG = {
    "discord_connection_mode": "http",
    "slack_token": "xoxb-only-a-mock-secret",
    "slack_signing_secret": "mock-signing-secret",
    "slack_team_id": "TTEST",
    "discord_token": "only-a-mock-secret",
    "discord_public_key": "a" * 64,
    "discord_application_id": "123456",
}
EXTERNAL = {
    "slack": {"employee": "UEMPLOYEE", "manager": "UMANAGER"},
    "discord": {"employee": "111111", "manager": "222222"},
}


def link_demo_accounts(service, now):
    for provider, users in EXTERNAL.items():
        for role, external in users.items():
            identity = DEMO_IDENTITIES[role]
            code = service.accounts.issue(provider, identity.id, now)["code"]
            scope = "TTEST" if provider == "slack" else "123456"
            service.accounts.claim_code(provider, code, external, scope, now)
            pending = service.accounts.connection(provider, identity.id, now)["pending"]
            service.accounts.confirm(provider, identity.id, pending["challenge_id"], now)


@pytest.fixture(autouse=True)
def no_live_webhooks(monkeypatch):
    monkeypatch.setattr(
        "http.client.HTTPSConnection",
        Mock(side_effect=AssertionError("Live webhooks are forbidden in tests")),
    )


@pytest.fixture
def system(tmp_path):
    workflow = WorkflowService(str(tmp_path / "workflow.db"))
    transport = Mock()
    transport.send.return_value = DeliveryResult(delivered=True)
    clock = Mock(return_value=1000.0)
    service = NotificationService(
        workflow.store.db_path,
        **BOT_CONFIG,
        app_url=APP_URL,
        transport=transport,
        clock=clock,
    )
    link_demo_accounts(service, clock())
    return workflow, service, transport, clock


def submit(workflow):
    draft = workflow.create_structured_draft(
        request_type="document",
        title="Private title @everyone",
        comment="Private medical information",
        applicant="employee.demo",
        approver="manager.demo",
    )
    return workflow.confirm_draft(draft["id"], "employee.demo", {}, revision=draft["revision"])


def enable(service, provider="slack"):
    state = next(item for item in service.overview()["items"] if item["provider"] == provider)
    service.set_enabled(provider, True, state["revision"], "admin.demo")


def test_default_disabled_drafts_and_backfill_are_private(system):
    workflow, service, transport, clock = system
    old = submit(workflow)
    service.run_once("slack")
    assert not transport.send.called
    enable(service)
    draft = workflow.create_structured_draft(
        request_type="document", applicant="employee.demo", approver="manager.demo"
    )
    workflow.act(
        draft["id"],
        "employee.demo",
        "employee",
        "cancel",
        draft["revision"],
        comment="Keep private",
    )
    service.run_once("slack")
    assert not transport.send.called
    request = submit(workflow)
    service.run_once("slack")
    assert transport.send.call_count == 1
    payload = transport.send.call_args.args[2]
    serialized = json.dumps(payload)
    assert f"REQ-{request['number']:06d}" in serialized
    assert request["id"] in serialized and old["id"] not in serialized
    assert "Private" not in serialized and "@everyone" not in serialized
    assert "employee.demo" not in serialized and "manager.demo" not in serialized
    service.run_once("slack")
    assert transport.send.call_count == 1


def test_only_role_specific_work_messages_are_delivered(system):
    workflow, service, transport, clock = system
    for provider in ("slack", "discord"):
        enable(service, provider)
    request = submit(workflow)
    for provider in ("slack", "discord"):
        service.run_once(provider)
    for name, role in (
        ("start_review", "manager"),
        ("request_information", "manager"),
        ("provide_information", "employee"),
        ("reject", "manager"),
        ("appeal", "employee"),
        ("start_review", "manager"),
        ("approve", "manager"),
        ("complete", "manager"),
    ):
        request = workflow.act(
            request["id"],
            role + ".demo",
            role,
            name,
            request["revision"],
            comment="Relevant reason",
            basis="Policy",
            fair_review_confirmed=True,
        )
        clock.return_value += 2
        service.run_once("slack")
        service.run_once("discord")
    assert transport.send.call_count == 8
    for provider in ("slack", "discord"):
        payloads = [
            call.args[2]
            for call in transport.send.call_args_list
            if call.args[0].provider == provider
        ]
        assert "New request" in json.dumps(payloads[0])
        assert "Reconsideration requested" in json.dumps(payloads[-1])
        employee_payloads = [
            call.args[2]
            for call in transport.send.call_args_list
            if call.args[0].provider == provider and call.args[1] == EXTERNAL[provider]["employee"]
        ]
        assert len(employee_payloads) == 1
        assert "More information needed from you" in json.dumps(employee_payloads[0])
        assert not any(
            word in json.dumps(payloads) for word in ("Approved", "Rejected", "Completed")
        )
        assert all(
            APP_URL + "/requests?request=" + request["id"] in json.dumps(payload)
            for payload in payloads
        )


def test_queue_and_retry_survive_restart_without_blocking_other_provider(system):
    workflow, service, transport, clock = system
    enable(service)
    enable(service, "discord")
    request = submit(workflow)
    transport.send.side_effect = lambda target, recipient, payload, delivery_id: (
        DeliveryResult(retryable=True, error_code="rate_limited", retry_after=35)
        if target.provider == "slack"
        else DeliveryResult(delivered=True)
    )
    service.run_once("slack")
    service.run_once("discord")
    states = {item["provider"]: item for item in service.overview()["items"]}
    assert states["slack"]["last_delivery"]["status"] == "pending"
    assert states["discord"]["last_delivery"]["status"] == "delivered"
    restarted = NotificationService(
        workflow.store.db_path,
        **BOT_CONFIG,
        app_url=APP_URL,
        transport=transport,
        clock=clock,
    )
    clock.return_value = 1034
    restarted.run_once("slack")
    assert transport.send.call_count == 2
    clock.return_value = 1036
    transport.send.side_effect = None
    restarted.run_once("slack")
    assert transport.send.call_count == 3
    assert workflow.get_for_user(request["id"], "employee.demo")["status"] == "submitted"
    assert (
        next(item for item in restarted.overview()["items"] if item["provider"] == "slack")[
            "last_delivery"
        ]["status"]
        == "delivered"
    )


def test_disabling_cancels_queue_and_does_not_replay_missed_events(system):
    workflow, service, transport, clock = system
    enable(service)
    submit(workflow)
    service.store.collect("slack", clock())
    service.set_enabled("slack", False, 1, "admin.demo")
    submit(workflow)
    service.run_once("slack")
    enable(service)
    service.run_once("slack")
    assert not transport.send.called
    assert (
        next(item for item in service.overview()["items"] if item["provider"] == "slack")[
            "last_delivery"
        ]["status"]
        == "cancelled"
    )


@pytest.mark.parametrize("provider,other", [("slack", "discord"), ("discord", "slack")])
def test_disabling_inflight_job_fences_completion_and_preserves_other_provider(
    system, provider, other
):
    workflow, service, transport, clock = system
    enable(service, provider)
    enable(service, other)
    submit(workflow)
    service.store.collect(provider, clock())
    inflight = service.store.claim(provider, clock())
    service.set_enabled(provider, False, 1, "admin.demo")
    service.store.finish(inflight, "delivered", "", 0, clock(), 1)
    restarted = NotificationService(
        workflow.store.db_path,
        **BOT_CONFIG,
        app_url=APP_URL,
        transport=transport,
        clock=clock,
    )
    restarted.run_once(provider)
    restarted.run_once(other)
    assert transport.send.call_count == 1
    assert transport.send.call_args.args[0].provider == other
    states = {item["provider"]: item for item in restarted.overview()["items"]}
    assert not states[provider]["enabled"] and states[other]["enabled"]
    assert states[provider]["last_delivery"]["status"] == "cancelled"
    assert states[provider]["active_delivery"] is None
    assert states[other]["last_delivery"]["status"] == "delivered"


@pytest.mark.parametrize("provider", ["slack", "discord"])
@pytest.mark.parametrize("code", ["timeout", "network", "provider_unavailable"])
def test_transient_errors_back_off_then_deliver_without_duplicate_success(system, provider, code):
    workflow, service, transport, clock = system
    enable(service, provider)
    submit(workflow)
    transport.send.side_effect = [
        DeliveryResult(retryable=True, error_code=code),
        DeliveryResult(delivered=True),
    ]
    with patch("services.notification_service.random.uniform", return_value=0):
        service.run_once(provider)
    state = next(item for item in service.overview()["items"] if item["provider"] == provider)
    assert state["active_delivery"]["next_attempt_at"] == 1002
    clock.return_value = 1001
    service.run_once(provider)
    assert transport.send.call_count == 1
    clock.return_value = 1002
    service.run_once(provider)
    clock.return_value += 100
    service.run_once(provider)
    assert transport.send.call_count == 2
    state = next(item for item in service.overview()["items"] if item["provider"] == provider)
    assert state["last_delivery"]["status"] == "delivered"
    assert state["active_delivery"] is None


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_permanent_rejection_does_not_retry_or_change_request(system, provider):
    workflow, service, transport, clock = system
    enable(service, provider)
    request = submit(workflow)
    transport.send.return_value = DeliveryResult(error_code="webhook_rejected")
    for _ in range(3):
        service.run_once(provider)
        clock.return_value += 100
    assert transport.send.call_count == 1
    state = next(item for item in service.overview()["items"] if item["provider"] == provider)
    assert state["last_delivery"]["status"] == "failed"
    assert workflow.get_for_user(request["id"], "employee.demo")["status"] == "submitted"


def test_retry_limit_and_logs_never_include_secrets(system, caplog):
    workflow, service, transport, clock = system
    caplog.set_level(logging.INFO)
    enable(service)
    submit(workflow)
    transport.send.side_effect = RuntimeError(SLACK + " " + DISCORD)
    for tick in range(8):
        clock.return_value = 1000 + tick * 100
        service.run_once("slack")
    assert transport.send.call_count == 5
    state = next(item for item in service.overview()["items"] if item["provider"] == "slack")
    assert state["last_delivery"]["status"] == "failed"
    assert "attempt=5" in caplog.text
    assert "only-a-mock-secret" not in caplog.text + json.dumps(service.overview()) + repr(
        service.targets
    )


def test_replayed_event_is_not_sent_again_after_restart(system):
    workflow, service, transport, clock = system
    for provider in ("slack", "discord"):
        enable(service, provider)
    submit(workflow)
    for provider in ("slack", "discord"):
        service.run_once(provider)
    assert transport.send.call_count == 2
    # Simulate re-reading journal entries that already have delivered outbox rows.
    with service.store.transaction() as conn:
        conn.execute("UPDATE integration_settings SET cursor=0")
    restarted = NotificationService(
        workflow.store.db_path,
        **BOT_CONFIG,
        app_url=APP_URL,
        transport=transport,
        clock=clock,
    )
    clock.return_value += 100
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: restarted.store.collect("slack", clock()), range(2)))
    for provider in ("slack", "discord"):
        restarted.run_once(provider)
    assert transport.send.call_count == 2
    with restarted.store.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notification_jobs").fetchone()[0] == 2
    assert all(item["pending"] == 0 for item in restarted.overview()["items"])


def test_both_providers_down_does_not_block_creating_and_reviewing_requests(system):
    workflow, service, transport, clock = system
    for provider in ("slack", "discord"):
        enable(service, provider)
    first = submit(workflow)
    transport.send.return_value = DeliveryResult(retryable=True, error_code="timeout")
    for provider in ("slack", "discord"):
        service.run_once(provider)
    second = submit(workflow)
    for action in ("start_review", "approve"):
        first = workflow.act(
            first["id"],
            "manager.demo",
            "manager",
            action,
            first["revision"],
            comment="Meets the documented policy",
            basis="Test policy",
            fair_review_confirmed=True,
        )
    for provider in ("slack", "discord"):
        service.run_once(provider)
    assert workflow.get_for_user(first["id"], "employee.demo")["status"] == "approved"
    assert workflow.get_for_user(second["id"], "employee.demo")["status"] == "submitted"
    assert transport.send.call_count == 2
    states = service.overview()["items"]
    assert all(item["pending"] == 2 for item in states)
    assert all(item["active_delivery"]["error"] == "The provider timed out." for item in states)


def test_multiple_workers_and_expired_lease_do_not_duplicate_claims(system):
    workflow, service, _, clock = system
    enable(service)
    submit(workflow)
    service.store.collect("slack", clock())
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _: service.store.claim("slack", clock()), range(2)))
    assert sum(item is not None for item in claimed) == 1
    old = next(item for item in claimed if item)
    clock.return_value += 61
    recovered = service.store.claim("slack", clock())
    assert recovered["id"] == old["id"] and recovered["lease_token"] != old["lease_token"]
    service.store.finish(old, "delivered", "", 0, clock(), 1)
    assert (
        next(item for item in service.overview()["items"] if item["provider"] == "slack")[
            "last_delivery"
        ]["status"]
        == "sending"
    )
    service.store.finish(recovered, "delivered", "", 0, clock(), 1)


def test_public_link_cannot_expose_a_secret():
    for value in (
        SLACK,
        DISCORD,
        "https://user:password@example.test",
        APP_URL + "?token=secret",
        "javascript:alert(1)",
    ):
        assert public_app_url(value) == ""


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_confirmed_delivery_is_not_retried_when_connection_close_fails(system, provider):
    workflow, service, _, clock = system
    enable(service, provider)
    submit(workflow)
    response = Mock(status=200)
    replies = (
        [
            {"ok": True, "channel": {"id": "DMANAGER", "is_im": True, "user": "UMANAGER"}},
            {"ok": True, "channel": "DMANAGER", "ts": "123.1"},
        ]
        if provider == "slack"
        else [
            {"id": "333333", "type": 1, "recipients": [{"id": "222222"}]},
            {"id": "444444", "channel_id": "333333"},
        ]
    )
    response.read.side_effect = [json.dumps(value).encode() for value in replies]
    response.getheader.return_value = None
    connection = Mock()
    connection.getresponse.return_value = response
    connection.close.side_effect = OSError(SLACK + DISCORD)
    factory = Mock(return_value=connection)
    service.transport = DirectMessageTransport(connection_factory=factory)
    service.run_once(provider)
    clock.return_value += 100
    service.run_once(provider)
    state = next(item for item in service.overview()["items"] if item["provider"] == provider)
    assert state["last_delivery"]["status"] == "delivered"
    assert state["last_delivery"]["attempts"] == 1
    assert factory.call_count == 2


def test_active_retry_is_visible_even_when_newer_messages_are_queued(system):
    workflow, service, transport, clock = system
    enable(service)
    submit(workflow)
    transport.send.return_value = DeliveryResult(
        retryable=True, error_code="rate_limited", retry_after=35
    )
    service.run_once("slack")
    clock.return_value += 1
    submit(workflow)
    service.run_once("slack")
    state = next(item for item in service.overview()["items"] if item["provider"] == "slack")
    assert state["pending"] == 2 and transport.send.call_count == 1
    assert state["last_delivery"]["attempts"] == 0
    assert state["active_delivery"]["attempts"] == 1
    assert state["active_delivery"]["next_attempt_at"] == 1035
    assert "pause" in state["active_delivery"]["error"]
    assert "error_code" not in state["active_delivery"]


def test_storage_failure_does_not_break_request_creation(system):
    workflow, service, _, _ = system
    with patch.object(service.store, "initialize", side_effect=RuntimeError(SLACK)):
        service.ready = False
        service._initialize()
    assert submit(workflow)["status"] == "submitted"
    with pytest.raises(IntegrationUnavailable):
        service.overview()


def test_api_controls_are_admin_only_and_test_has_no_workflow_side_effects(system):
    workflow, service, transport, clock = system
    runtime = get_runtime()

    def auth(role):
        return {
            "Authorization": "Bearer " + runtime.auth_service.issue_token(DEMO_IDENTITIES[role])
        }

    with (
        patch.object(runtime, "notification_service", service),
        patch.object(service, "start"),
        patch.object(service, "stop", new=AsyncMock()),
        TestClient(app) as client,
    ):
        path = "/api/v1/admin/integrations"
        assert client.get(path).status_code == 401
        for role in ("employee", "manager"):
            assert client.get(path, headers=auth(role)).status_code == 403
            assert (
                client.patch(
                    path + "/slack",
                    headers=auth(role),
                    json={"enabled": True, "expected_revision": 0},
                ).status_code
                == 403
            )
            assert (
                client.post(
                    path + "/slack/test", headers=auth(role), json={"audience": "manager"}
                ).status_code
                == 403
            )
        admin = auth("knowledge_admin")
        assert client.get(path, headers=admin).headers["cache-control"] == "no-store"
        assert (
            client.post(
                path + "/slack/test", headers=admin, json={"audience": "manager"}
            ).status_code
            == 400
        )
        response = client.patch(
            path + "/slack",
            headers=admin,
            json={"enabled": True, "expected_revision": 0, "webhook_url": SLACK},
        )
        assert response.status_code == 422 and "only-a-mock-secret" not in response.text
        assert (
            client.patch(
                path + "/slack", headers=admin, json={"enabled": True, "expected_revision": 0}
            ).status_code
            == 200
        )
        assert (
            client.patch(
                path + "/slack", headers=admin, json={"enabled": False, "expected_revision": 0}
            ).status_code
            == 409
        )
        response = client.post(path + "/slack/test", headers=admin, json={"audience": "manager"})
        assert response.status_code == 202 and response.json()["status"] == "pending"
        assert not transport.send.called
        assert (
            client.post(
                path + "/slack/test", headers=admin, json={"audience": "manager"}
            ).status_code
            == 429
        )
        service.run_once("slack")
        assert transport.send.call_count == 1
        response = client.get(path, headers=admin)
        assert "only-a-mock-secret" not in response.text
        assert (
            next(item for item in response.json()["items"] if item["provider"] == "slack")[
                "last_delivery"
            ]["status"]
            == "delivered"
        )
        assert workflow.list_for_user("employee.demo") == []


def test_unconfigured_integration_cannot_be_enabled_or_tested(system):
    workflow, _, transport, clock = system
    service = NotificationService(
        workflow.store.db_path, transport=transport, clock=clock, app_url=APP_URL
    )
    with pytest.raises(IntegrationError):
        enable(service)
    with pytest.raises(IntegrationError):
        service.test_notification("slack")
    assert not transport.send.called


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_missing_personal_recipient_never_falls_back_to_channel_or_employee(system, provider):
    workflow, service, transport, clock = system
    enable(service, provider)
    service.accounts.disconnect(provider, "manager.demo", clock())
    request = submit(workflow)
    service.run_once(provider)
    transport.send.assert_not_called()
    state = next(item for item in service.overview()["items"] if item["provider"] == provider)
    assert state["last_delivery"]["status"] == "failed"
    assert "has not connected" in state["last_delivery"]["error"]
    assert workflow.get_for_user(request["id"], "employee.demo")["status"] == "submitted"


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_disconnect_cancels_own_pending_messages_without_affecting_other_role(system, provider):
    _, service, transport, clock = system
    enable(service, provider)
    service.test_notification(provider, "employee")
    service.test_notification(provider, "manager")
    service.disconnect(provider, DEMO_IDENTITIES["employee"])
    service.run_once(provider)
    assert transport.send.call_count == 1
    assert transport.send.call_args.args[1] == EXTERNAL[provider]["manager"]


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_cancellation_of_submitted_requests_notifies_without_private_reason(system, provider):
    workflow, service, transport, clock = system
    enable(service, provider)
    request = submit(workflow)
    service.run_once(provider)
    workflow.act(
        request["id"],
        "employee.demo",
        "employee",
        "cancel",
        request["revision"],
        comment="Private reason",
    )
    clock.return_value += 2
    service.run_once(provider)
    assert transport.send.call_count == 2
    payload = json.dumps(transport.send.call_args.args[2])
    assert "Cancelled" in payload and "Private reason" not in payload


def test_notification_link_requires_authorized_request_participant(system):
    workflow, service, transport, _ = system
    runtime = get_runtime()
    enable(service, "discord")
    request = submit(workflow)
    service.run_once("discord")
    link = transport.send.call_args.args[2]["embeds"][0]["url"]
    assert urlsplit(link).path == "/requests"
    request_id = parse_qs(urlsplit(link).query)["request"][0]
    assert request_id == request["id"]
    unrelated = workflow.create_structured_draft(
        request_type="document", applicant="unrelated.employee", approver="unrelated.manager"
    )
    with (
        patch.object(runtime, "workflow_service", workflow),
        patch.object(runtime, "notification_service", service),
        patch.object(service, "start"),
        patch.object(service, "stop", new=AsyncMock()),
        TestClient(app) as client,
    ):
        path = "/api/v1/requests/" + request_id
        assert client.get(path).status_code == 401
        for role in ("employee", "manager", "knowledge_admin"):
            headers = {
                "Authorization": "Bearer " + runtime.auth_service.issue_token(DEMO_IDENTITIES[role])
            }
            assert client.get(path, headers=headers).status_code == (
                403 if role == "knowledge_admin" else 200
            )
            response = client.get("/api/v1/requests/" + unrelated["id"], headers=headers)
            assert response.status_code in {403, 404}
            assert "unrelated.employee" not in response.text


def test_background_workers_isolate_failures_log_safely_and_stop(system, caplog):
    _, service, _, _ = system

    async def exercise():
        loop = asyncio.get_running_loop()
        seen = set()
        both_ran = asyncio.Event()

        def record(provider):
            seen.add(provider)
            if seen == {"slack", "discord"}:
                both_ran.set()

        def run_once(provider):
            loop.call_soon_threadsafe(record, provider)
            if provider == "slack":
                raise RuntimeError(SLACK)

        with patch.object(service, "run_once", side_effect=run_once):
            service.start()
            tasks = list(service.tasks)
            service.start()
            assert service.tasks == tasks
            try:
                await asyncio.wait_for(both_ran.wait(), timeout=5)
            finally:
                await service.stop()
            assert all(task.done() for task in tasks)
            assert service.tasks == []

    with caplog.at_level(logging.INFO):
        asyncio.run(exercise())
    assert "Notification worker failed provider=slack code=internal" in caplog.text
    assert "only-a-mock-secret" not in caplog.text
