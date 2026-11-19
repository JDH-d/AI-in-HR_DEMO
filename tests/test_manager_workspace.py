"""Manager queue acceptance checks use temporary databases and no deliveries."""

from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import app
from domain.workflow import WorkflowPermissionError, WorkflowValidationError
from services.auth_service import DEMO_IDENTITIES, DemoIdentity
from services.runtime import get_runtime
from services.workflow_service import WorkflowService

NOW = datetime(2035, 6, 15, 12, tzinfo=timezone.utc)
DECISION = {
    "comment": "The relevant facts were checked.",
    "basis": "Objective policy criterion",
    "fair_review_confirmed": True,
}


@contextmanager
def recorded_at(when):
    with (
        patch("storage.request_store.utc_now", return_value=when.isoformat()),
        patch("storage.workflow_store.utc_now", return_value=when.isoformat()),
    ):
        yield


@pytest.fixture
def service(tmp_path):
    return WorkflowService(str(tmp_path / "requests.db"), clock=lambda: NOW)


def make(
    service,
    *,
    status="submitted",
    sent=None,
    applicant="employee.demo",
    approver="manager.demo",
    priority="normal",
    category="document",
):
    sent = sent or NOW - timedelta(days=6)
    with recorded_at(sent - timedelta(days=2)):
        row = service.create_structured_draft(
            request_type=category,
            start_date="2035-07-01" if category != "document" else None,
            end_date="2035-07-02" if category != "document" else None,
            title="Synthetic employment letter",
            comment="Please prepare a synthetic letter.",
            applicant=applicant,
            approver=approver,
            priority=priority,
        )
    if status != "draft":
        row = act(service, row, "submit", sent)
    if status in {"in_review", "needs_information", "approved", "rejected", "completed"}:
        row = act(service, row, "start_review", sent + timedelta(hours=1))
    if status == "needs_information":
        row = act(service, row, "request_information", sent + timedelta(hours=2))
    if status in {"approved", "rejected", "completed"}:
        row = act(
            service, row, "reject" if status == "rejected" else "approve", sent + timedelta(hours=2)
        )
    if status == "completed":
        row = act(service, row, "complete", sent + timedelta(hours=3))
    return row


def act(service, row, action, when=NOW):
    role = (
        "employee" if action in {"submit", "provide_information", "appeal", "cancel"} else "manager"
    )
    actor = row["applicant"] if role == "employee" else row["approver"]
    with recorded_at(when):
        return service.act(row["id"], actor, role, action, row["revision"], **DECISION)


def attention(service, row, manager=None):
    return service.detail(row["id"], manager or row["approver"], "manager")["request"][
        "manager_attention"
    ]


@pytest.mark.parametrize("seconds, overdue", [(-1, False), (0, False), (1, True)])
def test_deadline_five_calendar_days_exact_boundary_and_read_only(service, seconds, overdue):
    row = make(service, sent=NOW - timedelta(days=5, seconds=seconds))
    before = service.history(row["id"])
    result = attention(service, row)
    assert result["due_at"] == (NOW - timedelta(seconds=seconds)).isoformat()
    assert result["overdue"] is overdue
    listed = service.list_visible("manager.demo", "manager", attention="overdue")
    assert listed["total"] == int(overdue)
    assert service.manager_overview("manager.demo", "manager")["summary"]["overdue"] == int(overdue)
    assert service.history(row["id"]) == before
    assert (
        "manager_attention" not in service.detail(row["id"], "employee.demo", "employee")["request"]
    )


def test_review_comments_and_reassignment_never_extend_review_deadline(service):
    row = make(service)
    due = attention(service, row)["due_at"]
    row = act(service, row, "start_review", NOW - timedelta(days=4))
    with recorded_at(NOW - timedelta(days=2)):
        row = service.comment(row["id"], "manager.demo", "manager", "Review note", row["revision"])[
            "request"
        ]
    other = DemoIdentity("manager.other", "other", "Other manager", "manager")
    with patch.dict(DEMO_IDENTITIES, other=other), recorded_at(NOW):
        row = service.assign(
            row["id"],
            "manager.demo",
            other.id,
            "Transfer to the assigned specialist",
            row["revision"],
        )
    assert attention(service, row)["due_at"] == due
    assert attention(service, row)["overdue"] is True
    assert service.list_visible("manager.demo", "manager")["total"] == 0
    assert service.manager_activity("manager.demo", "manager")["total"] == 0
    assert service.manager_overview("manager.demo", "manager")["summary"]["overdue"] == 0


def test_waiting_is_not_overdue_and_employee_reply_starts_fresh_period(service):
    row = make(
        service, status="needs_information", sent=NOW - timedelta(days=30), priority="urgent"
    )
    assert attention(service, row) == {"due_at": None, "overdue": False, "reasons": []}
    summary = service.manager_overview("manager.demo", "manager")["summary"]
    assert summary["waiting_for_employee"] == 1 and summary["overdue"] == 0
    row = act(service, row, "provide_information", NOW - timedelta(days=1))
    assert attention(service, row) == {
        "due_at": (NOW + timedelta(days=4)).isoformat(),
        "overdue": False,
        "reasons": ["high_priority", "employee_reply"],
    }
    assert (
        service.list_visible("manager.demo", "manager", attention="needs_attention")["total"] == 1
    )


def test_reconsideration_keeps_original_decision_and_gets_new_deadline(service):
    row = make(service, status="rejected", sent=NOW - timedelta(days=30))
    original = service.history(row["id"])["events"][-1]
    row = act(service, row, "appeal", NOW - timedelta(days=1))
    row = act(service, row, "start_review")
    assert attention(service, row) == {
        "due_at": (NOW + timedelta(days=4)).isoformat(),
        "overdue": False,
        "reasons": ["reconsideration"],
    }
    assert original in service.history(row["id"])["events"]


def test_manager_filters_and_summary_never_expand_access(service):
    old = make(service, priority="high")
    recent = make(service, sent=NOW - timedelta(days=1))
    make(service, status="in_review", sent=NOW - timedelta(days=1))
    make(service, status="needs_information")
    make(service, status="approved")
    make(service, status="draft", priority="urgent")
    private = make(service, status="draft")
    act(service, private, "cancel")
    foreign = make(service, approver="manager.other", priority="urgent")
    result = service.list_visible(
        "manager.demo",
        "manager",
        status="submitted",
        priority="high",
        category="document",
        attention="overdue",
        assignee="manager.demo",
    )
    assert [item["id"] for item in result["requests"]] == [old["id"]]
    assert result["total"] == 1
    assert service.list_visible("manager.demo", "manager", assignee="manager.other")["total"] == 0
    assert service.list_visible("manager.demo", "manager", q=foreign["id"])["total"] == 0
    summary = service.manager_overview("manager.demo", "manager")["summary"]
    assert summary == {
        "new": 2,
        "in_review": 1,
        "waiting_for_employee": 1,
        "awaiting_completion": 1,
        "overdue": 1,
        "needs_attention": 1,
        "completed_last_30_days": 0,
    }
    assert (
        "manager_attention" not in service.list_visible("employee.demo", "employee")["requests"][0]
    )
    with pytest.raises(WorkflowPermissionError):
        service.list_visible("employee.demo", "employee", attention="overdue")
    assert recent["id"] != old["id"]


def test_completed_metric_uses_completion_event_not_new_comments(service):
    old = make(service, status="completed", sent=NOW - timedelta(days=31))
    recent = make(service, status="completed", sent=NOW - timedelta(days=29))
    make(service, status="completed", sent=NOW - timedelta(days=1), approver="manager.other")
    with recorded_at(NOW):
        service.comment(old["id"], "employee.demo", "employee", "Recent follow-up", old["revision"])
    assert (
        service.manager_overview("manager.demo", "manager")["summary"]["completed_last_30_days"]
        == 1
    )
    reopened = act(service, recent, "appeal")
    assert (
        service.manager_overview("manager.demo", "manager")["summary"]["completed_last_30_days"]
        == 1
    )
    reopened = act(service, reopened, "start_review")
    reopened = act(service, reopened, "approve")
    act(service, reopened, "complete")
    assert (
        service.manager_overview("manager.demo", "manager")["summary"]["completed_last_30_days"]
        == 1
    )


def test_activity_is_paginated_stable_and_restricted_to_current_access(service):
    row = make(service, status="in_review")
    make(service, status="draft")
    make(service, approver="manager.other")
    expected = service.detail(row["id"], "manager.demo", "manager")["events"]
    first = service.manager_activity("manager.demo", "manager", limit=2)
    second = service.manager_activity("manager.demo", "manager", limit=2, offset=2)
    assert first["total"] == second["total"] == len(expected)
    combined = first["events"] + second["events"]
    assert [event["id"] for event in combined] == [event["id"] for event in reversed(expected)]
    assert all(
        event["request_id"] == row["id"]
        and event["request_number"] == row["number"]
        and event["request_title"] == row["title"]
        for event in combined
    )


def test_bulk_start_review_has_per_item_scope_revision_and_status_checks(service):
    okay = make(service)
    stale = make(service)
    with recorded_at(NOW):
        service.comment(stale["id"], "employee.demo", "employee", "A newer note", stale["revision"])
    done = make(service, status="approved")
    foreign = make(service, approver="manager.other")
    private = make(service, status="draft")
    unselected = make(service)
    # A failure before a valid row must not prevent that row from being handled;
    # unrelated requests and inaccessible draft content must remain untouched.
    rows = [stale, okay, done, foreign, private]
    before = {row["id"]: service.history(row["id"]) for row in [*rows, unselected]}
    payload = [{"id": row["id"], "expected_revision": row["revision"]} for row in rows]
    payload.append({"id": "missing-request", "expected_revision": 1})
    result = service.bulk_start_review("manager.demo", "manager", payload)["results"]
    assert [item["id"] for item in result] == [item["id"] for item in payload]
    assert [item["success"] for item in result] == [False, True, False, False, False, False]
    assert result[1]["request"]["status"] == "in_review"
    for item in result:
        if not item["success"]:
            assert "request" not in item and item["error"]
    assert foreign["title"] not in result[3]["error"]
    assert private["comment"] not in result[4]["error"]
    for row in [stale, done, foreign, private, unselected]:
        assert service.history(row["id"]) == before[row["id"]]
    after = service.history(okay["id"])
    assert len(after["events"]) == len(before[okay["id"]]["events"]) + 1
    retry = service.bulk_start_review("manager.demo", "manager", payload)["results"]
    assert not any(item["success"] for item in retry)
    assert service.history(okay["id"]) == after


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [{"id": "x", "expected_revision": 1}] * 2,
        [{"id": str(i), "expected_revision": 1} for i in range(21)],
    ],
)
def test_bulk_rejects_invalid_selection_before_writing(service, bad):
    row = make(service)
    before = service.history(row["id"])
    with pytest.raises(WorkflowValidationError):
        service.bulk_start_review("manager.demo", "manager", bad)
    assert service.history(row["id"]) == before


@pytest.mark.parametrize("role", ["employee", "knowledge_admin"])
def test_manager_services_refuse_other_roles(service, role):
    with pytest.raises(WorkflowPermissionError):
        service.manager_overview("manager.demo", role)
    with pytest.raises(WorkflowPermissionError):
        service.manager_activity("manager.demo", role)
    with pytest.raises(WorkflowPermissionError):
        service.bulk_start_review(
            "manager.demo", role, [{"id": "anything", "expected_revision": 1}]
        )


def test_manager_api_contract_auth_validation_and_bulk(service):
    row = make(service)
    runtime = get_runtime()

    def headers(role):
        return {
            "Authorization": "Bearer " + runtime.auth_service.issue_token(DEMO_IDENTITIES[role])
        }

    with patch.object(runtime, "workflow_service", service), TestClient(app) as client:
        for path in ("/manager/overview", "/manager/activity"):
            assert client.get("/api/v1" + path).status_code == 401
            for role in ("employee", "knowledge_admin"):
                assert client.get("/api/v1" + path, headers=headers(role)).status_code == 403
            assert client.get("/api/v1" + path, headers=headers("manager")).status_code == 200
        overview = client.get("/api/v1/manager/overview", headers=headers("manager")).json()
        assert overview["policy"]["review_days"] == 5
        assert overview["summary"]["new"] == 1
        listed = client.get(
            "/api/v1/requests?attention=overdue&assignee=manager.demo", headers=headers("manager")
        ).json()
        assert listed["total"] == 1 and listed["requests"][0]["manager_attention"]["overdue"]
        assert (
            client.get("/api/v1/requests?attention=invalid", headers=headers("manager")).status_code
            == 422
        )
        path = "/api/v1/manager/bulk-start-review"
        item = {"id": row["id"], "expected_revision": row["revision"]}
        for role in ("employee", "knowledge_admin"):
            assert (
                client.post(path, headers=headers(role), json={"items": [item]}).status_code == 403
            )
        assert (
            client.post(path, headers=headers("manager"), json={"items": [item, item]}).status_code
            == 422
        )
        assert (
            client.post(
                path, headers=headers("manager"), json={"items": [item], "action": "approve"}
            ).status_code
            == 422
        )
        result = client.post(path, headers=headers("manager"), json={"items": [item]}).json()
        assert result["results"][0]["success"] is True
        assert result["results"][0]["request"]["status"] == "in_review"


def test_legacy_submission_without_history_has_stable_fallback_without_migration(service):
    created = (NOW - timedelta(days=10)).isoformat()
    with closing(service.store._connect()) as conn, conn:
        conn.execute(
            """INSERT INTO workflow_requests
            (id,number,type,title,priority,comment,applicant,approver,status,created_at,updated_at)
            VALUES ('legacy-submitted',999,'document','Legacy letter','normal','Relevant facts',
                'employee.demo','manager.demo','submitted',?,?)""",
            [created, created],
        )
    row = service.store.get_request("legacy-submitted")
    before = service.history(row["id"])
    assert attention(service, row)["due_at"] == (NOW - timedelta(days=5)).isoformat()
    assert service.list_visible("manager.demo", "manager", attention="overdue")["total"] == 1
    assert service.history(row["id"]) == before


def test_bulk_cannot_review_a_malformed_legacy_self_assignment(service):
    row = make(service)
    with closing(service.store._connect()) as conn, conn:
        conn.execute(
            "UPDATE workflow_requests SET applicant='manager.demo' WHERE id=?", [row["id"]]
        )
    before = service.history(row["id"])
    result = service.bulk_start_review(
        "manager.demo", "manager", [{"id": row["id"], "expected_revision": row["revision"]}]
    )
    assert result["results"][0]["success"] is False
    assert "own requests" in result["results"][0]["error"]
    assert service.history(row["id"]) == before


def test_attention_filter_paginates_after_filter_and_sorts_visible_results(service):
    old = [make(service, priority=priority) for priority in ("normal", "high", "urgent")]
    make(service, sent=NOW - timedelta(days=1))
    page = service.list_visible(
        "manager.demo",
        "manager",
        attention="overdue",
        sort="priority",
        order="desc",
        offset=1,
        limit=1,
    )
    assert page["total"] == 3
    assert [row["id"] for row in page["requests"]] == [old[1]["id"]]
    assert page["counts"] == {"submitted": 4}


def test_manager_api_filters_work_independently_and_in_combination(service):
    document = make(service)
    pto = make(service, category="pto", priority="high")
    sick = make(service, category="sick_leave", priority="high", status="in_review")
    waiting = make(service, status="needs_information")
    make(service, approver="manager.other", priority="urgent")
    make(service, status="draft", priority="urgent")
    visible = {row["id"] for row in (document, pto, sick, waiting)}
    cases = [
        ({"status": "submitted"}, {document["id"], pto["id"]}),
        ({"category": "pto"}, {pto["id"]}),
        ({"priority": "high"}, {pto["id"], sick["id"]}),
        ({"assignee": "manager.demo"}, visible),
        ({"assignee": "manager.other"}, set()),
        ({"attention": "overdue"}, {document["id"], pto["id"], sick["id"]}),
        ({"q": f"REQ-{pto['number']:06d}"}, {pto["id"]}),
        (
            {
                "status": "submitted",
                "category": "pto",
                "priority": "high",
                "assignee": "manager.demo",
                "attention": "overdue",
            },
            {pto["id"]},
        ),
        ({"category": "pto", "priority": "normal"}, set()),
    ]
    runtime = get_runtime()
    headers = {
        "Authorization": "Bearer " + runtime.auth_service.issue_token(DEMO_IDENTITIES["manager"])
    }
    with patch.object(runtime, "workflow_service", service), TestClient(app) as client:
        for filters, expected in cases:
            response = client.get("/api/v1/requests", headers=headers, params=filters)
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == len(expected), filters
            assert {row["id"] for row in body["requests"]} == expected, filters
            # Visible queue counts do not shrink when a list filter is applied.
            assert body["counts"] == {"submitted": 2, "in_review": 1, "needs_information": 1}


def test_api_submission_assignment_and_summary_match_persisted_queue(service):
    runtime = get_runtime()
    other = DemoIdentity("manager.other", "other_manager", "Other Manager", "manager")

    def headers(identity):
        return {"Authorization": "Bearer " + runtime.auth_service.issue_token(identity)}

    employee = headers(DEMO_IDENTITIES["employee"])
    manager = headers(DEMO_IDENTITIES["manager"])
    second_manager = headers(other)
    empty = {
        "new": 0,
        "in_review": 0,
        "waiting_for_employee": 0,
        "awaiting_completion": 0,
        "overdue": 0,
        "needs_attention": 0,
        "completed_last_30_days": 0,
    }
    with (
        recorded_at(NOW),
        patch.dict(DEMO_IDENTITIES, other_manager=other),
        patch.object(runtime, "workflow_service", service),
        TestClient(app) as client,
    ):

        def assert_workspace(auth, ids, **expected):
            listed = client.get("/api/v1/requests", headers=auth)
            overview = client.get("/api/v1/manager/overview", headers=auth)
            assert listed.status_code == overview.status_code == 200
            rows = listed.json()["requests"]
            assert listed.json()["total"] == len(ids)
            assert {row["id"] for row in rows} == set(ids)
            summary = overview.json()["summary"]
            assert summary == {**empty, **expected}
            for counter, status in (
                ("new", "submitted"),
                ("in_review", "in_review"),
                ("waiting_for_employee", "needs_information"),
                ("awaiting_completion", "approved"),
            ):
                assert summary[counter] == sum(row["status"] == status for row in rows)
            assert summary["overdue"] == sum(row["manager_attention"]["overdue"] for row in rows)
            assert summary["needs_attention"] == sum(
                bool(row["manager_attention"]["reasons"]) for row in rows
            )

        created = client.post(
            "/api/v1/requests",
            headers=employee,
            json={
                "type": "document",
                "title": "Synthetic payroll letter",
                "comment": "Please prepare a confirmation letter.",
            },
        )
        assert created.status_code == 201
        row = created.json()["request"]
        request_id = row["id"]
        path = f"/api/v1/requests/{request_id}"
        assert_workspace(manager, [])

        def transition(auth, name):
            nonlocal row
            response = client.post(
                path + "/actions/" + name,
                headers=auth,
                json={"expected_revision": row["revision"], **DECISION},
            )
            assert response.status_code == 200, response.text
            row = response.json()["request"]

        transition(employee, "submit")
        assert_workspace(manager, [request_id], new=1)
        transition(manager, "start_review")
        assert_workspace(manager, [request_id], in_review=1)
        before = service.history(request_id)
        for action_name in ("request_information", "approve", "reject"):
            denied = client.post(
                path + "/actions/" + action_name,
                headers=manager,
                json={"expected_revision": row["revision"], **DECISION, "comment": "   "},
            )
            assert denied.status_code == 422
            assert service.history(request_id) == before
        transition(manager, "request_information")
        assert_workspace(manager, [request_id], waiting_for_employee=1)
        transition(employee, "provide_information")
        assert_workspace(manager, [request_id], in_review=1, needs_attention=1)

        assigned = client.post(
            path + "/assign",
            headers=manager,
            json={
                "expected_revision": row["revision"],
                "assignee": other.id,
                "comment": "Specialist takes over this review.",
            },
        )
        assert assigned.status_code == 200
        row = assigned.json()["request"]
        assert_workspace(manager, [])
        assert_workspace(second_manager, [request_id], in_review=1, needs_attention=1)
        assert client.get(path, headers=manager).status_code == 404
        assert client.get(path, headers=employee).json()["request"]["approver"] == other.id
        restarted = WorkflowService(str(service.store.db_path), clock=lambda: NOW)
        detail = restarted.detail(request_id, other.id, "manager")
        assert detail["request"]["approver"] == other.id
        assignment = detail["events"][-1]
        assert assignment["event_type"] == "assignee_changed"
        assert assignment["actor"] == "manager.demo"
        assert assignment["created_at"] == NOW.isoformat()
        assert assignment["details"]["changes"]["approver"] == {
            "before": "manager.demo",
            "after": other.id,
        }

        transition(second_manager, "approve")
        assert_workspace(second_manager, [request_id], awaiting_completion=1)
        transition(second_manager, "complete")
        assert_workspace(second_manager, [request_id], completed_last_30_days=1)
        assert_workspace(manager, [])
