import json
from unittest.mock import Mock

import pytest

from domain.notification_policy import notification_for_event
from domain.notifications import IntegrationError, IntegrationRateLimited
from services.auth_service import DEMO_IDENTITIES, DemoIdentity
from services.workflow_service import WorkflowService
from storage.notification_store import NotificationStore


@pytest.fixture(autouse=True)
def no_live_delivery(monkeypatch):
    monkeypatch.setattr(
        "http.client.HTTPSConnection",
        Mock(side_effect=AssertionError("Real notifications are forbidden")),
    )


@pytest.fixture
def routed(tmp_path):
    workflow = WorkflowService(str(tmp_path / "workflow.db"))
    store = NotificationStore(workflow.store.db_path)
    store.initialize()
    for provider in ("slack", "discord"):
        store.set_enabled(provider, True, 0, "admin.demo", 1000)
    return workflow, store


def submit(workflow, applicant="employee.demo", approver="manager.demo"):
    draft = workflow.create_structured_draft(
        request_type="document",
        applicant=applicant,
        approver=approver,
        title="Private request title",
        comment="Private description",
    )
    return workflow.confirm_draft(draft["id"], applicant, {}, revision=draft["revision"])


def act(workflow, request, action, role):
    return workflow.act(
        request["id"],
        request["applicant"] if role == "employee" else request["approver"],
        role,
        action,
        request["revision"],
        comment="Private relevant explanation",
        basis="Policy",
        fair_review_confirmed=True,
    )


def delivery(store, provider, now):
    store.collect(provider, now)
    job = store.claim(provider, now)
    if job:
        store.finish(job, "delivered", "", 0, now, 0)
        return job["payload"]
    return None


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_employee_and_manager_receive_only_their_workflow_messages(routed, provider):
    workflow, store = routed
    request = submit(workflow)
    message = delivery(store, provider, 1001)
    assert (message["kind"], message["audience"], message["recipient_id"]) == (
        "new_request",
        "manager",
        "manager.demo",
    )
    assert message["request_id"] == request["id"] and message["number"] == request["number"]
    assert "Private" not in json.dumps(message)
    request = act(workflow, request, "start_review", "manager")
    assert delivery(store, provider, 1002) is None
    request = act(workflow, request, "request_information", "manager")
    message = delivery(store, provider, 1003)
    assert (message["kind"], message["audience"], message["recipient_id"]) == (
        "information_requested",
        "employee",
        "employee.demo",
    )
    request = act(workflow, request, "provide_information", "employee")
    message = delivery(store, provider, 1004)
    assert (message["kind"], message["audience"], message["recipient_id"]) == (
        "information_provided",
        "manager",
        "manager.demo",
    )
    request = act(workflow, request, "reject", "manager")
    assert delivery(store, provider, 1005) is None
    request = act(workflow, request, "appeal", "employee")
    assert delivery(store, provider, 1006)["kind"] == "reconsideration_requested"
    request = act(workflow, request, "start_review", "manager")
    request = act(workflow, request, "approve", "manager")
    assert delivery(store, provider, 1007) is None
    act(workflow, request, "complete", "manager")
    assert delivery(store, provider, 1008) is None


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_unrelated_participants_never_replace_the_intended_recipient(routed, provider):
    workflow, store = routed
    request = submit(workflow, "employee.other", "manager.other")
    message = delivery(store, provider, 1001)
    assert message["recipient_id"] == "manager.other"
    assert not store.is_current_recipient({**message, "recipient_id": "manager.demo"})
    assert not store.is_current_recipient({**message, "recipient_id": "employee.other"})
    assert not store.is_current_recipient({**message, "audience": "employee"})
    request = act(workflow, request, "start_review", "manager")
    act(workflow, request, "request_information", "manager")
    employee_message = delivery(store, provider, 1002)
    assert employee_message["recipient_id"] == "employee.other"
    assert not store.is_current_recipient({**employee_message, "recipient_id": "employee.demo"})
    assert not store.is_current_recipient({**employee_message, "recipient_id": "manager.other"})


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_reassignment_cancels_old_manager_job_and_routes_new_assignment(
    routed, provider, monkeypatch
):
    workflow, store = routed
    monkeypatch.setitem(
        DEMO_IDENTITIES,
        "other_manager",
        DemoIdentity(
            id="manager.other",
            username="other_manager",
            display_name="Other manager",
            role="manager",
        ),
    )
    request = submit(workflow)
    store.collect(provider, 1001)
    workflow.assign(
        request["id"], "manager.demo", "manager.other", "Different reviewer", request["revision"]
    )
    store.collect(provider, 1002)
    assert store.claim(provider, 1002) is None
    message = delivery(store, provider, 1003)
    assert message["kind"] == "assigned" and message["recipient_id"] == "manager.other"
    with store.transaction() as conn:
        assert [
            row[0]
            for row in conn.execute(
                "SELECT status FROM notification_jobs WHERE provider=? ORDER BY rowid", (provider,)
            )
        ] == ["cancelled", "delivered"]


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_answered_information_request_is_cancelled_before_employee_delivery(routed, provider):
    workflow, store = routed
    request = submit(workflow)
    request = act(workflow, request, "start_review", "manager")
    request = act(workflow, request, "request_information", "manager")
    store.collect(provider, 1001)
    act(workflow, request, "provide_information", "employee")
    assert store.claim(provider, 1002) is None
    message = delivery(store, provider, 1003)
    assert message["kind"] == "information_provided" and message["audience"] == "manager"


@pytest.mark.parametrize("provider", ["slack", "discord"])
def test_cancelled_private_draft_never_notifies_but_submitted_cancellation_does(routed, provider):
    workflow, store = routed
    draft = workflow.create_structured_draft(
        request_type="document",
        applicant="employee.demo",
        approver="manager.demo",
    )
    act(workflow, draft, "cancel", "employee")
    assert delivery(store, provider, 1001) is None
    request = submit(workflow)
    act(workflow, request, "cancel", "employee")
    message = delivery(store, provider, 1002)
    assert message["kind"] == "cancelled" and message["recipient_id"] == "manager.demo"
    assert message["audience"] == "manager"


def test_personal_test_messages_require_an_explicit_audience_and_recipient(routed):
    _, store = routed
    for recipient, audience in (("", "manager"), ("employee.demo", "administrator")):
        with pytest.raises(IntegrationError):
            store.enqueue_test("slack", 1001, recipient, audience)
    store.enqueue_test("slack", 1001, "employee.demo", "employee")
    message = store.claim("slack", 1001)["payload"]
    assert message == {"kind": "test", "recipient_id": "employee.demo", "audience": "employee"}
    store.enqueue_test("slack", 1001, "manager.demo", "manager")
    with pytest.raises(IntegrationRateLimited):
        store.enqueue_test("slack", 1002, "employee.demo", "employee")
    assert not store.is_current_recipient({"kind": "test"})
    assert not store.is_current_recipient(
        {"kind": "status_changed", "recipient_id": "employee.demo", "audience": "employee"}
    )


def test_migration_cancels_legacy_broadcasts_and_preserves_delivered_and_request_data(routed):
    workflow, store = routed
    old_request = submit(workflow)
    with store.transaction() as conn:
        before = {
            table: [tuple(row) for row in conn.execute("SELECT * FROM " + table)]
            for table in (
                "workflow_requests",
                "request_events",
                "request_comments",
                "users",
            )
        }
        conn.execute("DELETE FROM notification_migrations WHERE name='personal_routing_v1'")
        conn.execute("UPDATE integration_settings SET cursor=0")
        for status in ("pending", "sending", "delivered"):
            conn.execute(
                "INSERT INTO notification_jobs(id,provider,event_id,payload,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    status,
                    "slack",
                    "legacy-" + status,
                    '{"kind":"status_changed"}',
                    status,
                    999,
                    999,
                ),
            )
    store.initialize()
    with store.transaction() as conn:
        after = {
            table: [tuple(row) for row in conn.execute("SELECT * FROM " + table)]
            for table in before
        }
        assert before == after
        statuses = {
            row["id"]: row["status"] for row in conn.execute("SELECT * FROM notification_jobs")
        }
        assert statuses == {
            "pending": "cancelled",
            "sending": "cancelled",
            "delivered": "delivered",
        }
        assert (
            conn.execute(
                "SELECT updated_at FROM notification_jobs WHERE id='delivered'"
            ).fetchone()[0]
            == 999
        )
        assert all(
            row["enabled"] == 0 and row["revision"] == 2
            for row in conn.execute("SELECT * FROM integration_settings")
        )
    assert delivery(store, "slack", 1001) is None
    store.set_enabled("slack", True, 2, "admin.demo", 1001)
    new_request = submit(workflow)
    store.initialize()  # The one-time migration must not skip new events on restart.
    message = delivery(store, "slack", 1002)
    assert message["request_id"] == new_request["id"] != old_request["id"]


def test_routed_jobs_survive_restart_and_event_replay_does_not_duplicate(routed):
    workflow, store = routed
    request = submit(workflow)
    store.collect("discord", 1001)
    restarted = NotificationStore(workflow.store.db_path)
    restarted.initialize()
    message = delivery(restarted, "discord", 1002)
    assert message["request_id"] == request["id"]
    with restarted.transaction() as conn:
        conn.execute("UPDATE integration_settings SET cursor=0 WHERE provider='discord'")
    assert delivery(restarted, "discord", 1003) is None
    with restarted.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notification_jobs").fetchone()[0] == 1


def test_unknown_events_and_wrong_actor_do_not_enter_notification_stream(routed):
    workflow, _ = routed
    request = submit(workflow)
    event = {
        "event_type": "status_changed",
        "from_status": "draft",
        "to_status": "submitted",
        "actor": "unrelated",
        "created_at": "2026-01-01",
    }
    assert notification_for_event(event, request) is None
    for event_type in ("chat_message", "decision_recorded", "comment_added", "attachment_added"):
        assert (
            notification_for_event(
                {**event, "event_type": event_type, "actor": request["applicant"]}, request
            )
            is None
        )


def test_malformed_pending_route_is_cancelled_instead_of_delivered(routed):
    workflow, store = routed
    request = submit(workflow)
    payload = {
        "kind": [],
        "recipient_id": "manager.demo",
        "audience": "manager",
        "request_id": request["id"],
    }
    with store.transaction() as conn:
        identifier = store._insert(conn, "slack", "malformed-test-event", payload, 1001)
    assert store.claim("slack", 1002) is None
    with store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT status FROM notification_jobs WHERE id=?", (identifier,)
            ).fetchone()[0]
            == "cancelled"
        )
