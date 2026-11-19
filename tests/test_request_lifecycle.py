import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.v1_dependencies import current_identity
from app import app
from domain.request_policy import RequestConflictError
from domain.workflow import (
    InvalidTransitionError,
    WorkflowDecisionError,
    WorkflowNotFoundError,
    WorkflowPermissionError,
    WorkflowValidationError,
)
from services.auth_service import DEMO_IDENTITIES, DemoIdentity
from services.runtime import get_runtime
from services.workflow_service import WorkflowService


@pytest.fixture
def workflow(tmp_path):
    return WorkflowService(str(tmp_path / "requests.db"))


def draft(service, **fields):
    return service.create_structured_draft(
        request_type="document",
        title="Employment letter",
        comment="Please provide a letter for my application.",
        applicant="employee.demo",
        approver="manager.demo",
        **fields,
    )


def action(service, request, name, **fields):
    employee_actions = {"submit", "provide_information", "appeal", "cancel"}
    role = "employee" if name in employee_actions else "manager"
    return service.act(request["id"], role + ".demo", role, name, request["revision"], **fields)


def review(service):
    return action(service, action(service, draft(service), "submit"), "start_review")


def decision(service, request, name="approve"):
    return action(
        service,
        request,
        name,
        comment="The required objective condition was checked.",
        basis="Employment letter policy, section 2",
        fair_review_confirmed=True,
    )


def test_full_lifecycle_with_evidence_reconsideration_and_restart(workflow):
    request = draft(workflow)
    assert request["number"] > 0 and request["status"] == "draft"
    assert workflow.list_visible("manager.demo", "manager")["total"] == 0
    request = workflow.edit_draft(
        request["id"],
        "employee.demo",
        {"priority": "high", "title": "Revised letter"},
        request["revision"],
    )
    request = action(workflow, request, "submit")
    request = action(workflow, request, "start_review")
    request = action(
        workflow,
        request,
        "request_information",
        comment="Which recipient should appear in the letter?",
    )
    assert request["status"] == "needs_information"
    attachment = workflow.attach(
        request["id"],
        "employee.demo",
        "employee",
        "реквизиты.txt",
        "Recipient: Acme".encode(),
        request["revision"],
    )
    request = action(
        workflow, attachment["request"], "provide_information", comment="Please address it to Acme."
    )
    request = decision(workflow, request, "reject")
    initial_decision = workflow.history(request["id"])["events"][-1]
    request = action(
        workflow,
        request,
        "appeal",
        comment="The relevant evidence was attached; please reconsider it.",
    )
    assert request["review_round"] == 2
    assert (
        workflow.history(request["id"])["events"][-1]["details"]["previous_decision_id"]
        == initial_decision["id"]
    )
    request = action(workflow, request, "start_review")
    request = decision(workflow, request)
    request = action(
        workflow, request, "complete", comment="The requested letter has been provided."
    )
    assert request["status"] == "completed"
    history = workflow.detail(request["id"], "employee.demo", "employee")
    assert initial_decision in history["events"]
    assert (
        len([item for item in history["events"] if item["event_type"] == "decision_recorded"]) == 2
    )
    assert [c["author"] for c in history["comments"]] == ["manager.demo", "employee.demo"]
    assert history["events"][1]["details"]["changes"]["title"] == {
        "before": "Employment letter",
        "after": "Revised letter",
    }
    assert history["events"] == sorted(history["events"], key=lambda item: item["created_at"])
    restarted = WorkflowService(str(workflow.store.db_path))
    assert restarted.detail(request["id"], "employee.demo", "employee") == history
    assert (
        restarted.attachment(
            request["id"], attachment["attachment"]["id"], "manager.demo", "manager"
        )["content"]
        == b"Recipient: Acme"
    )
    assert draft(restarted)["number"] > request["number"]


@pytest.mark.parametrize("missing", ["comment", "basis", "fair_review_confirmed"])
@pytest.mark.parametrize("kind", ["approve", "reject"])
def test_decisions_require_reason_criteria_and_equal_treatment_confirmation(
    workflow, missing, kind
):
    request = review(workflow)
    before = workflow.history(request["id"])
    fields = {
        "comment": "Checked facts",
        "basis": "Policy section 2",
        "fair_review_confirmed": True,
    }
    fields[missing] = False if missing == "fair_review_confirmed" else "   "
    with pytest.raises((WorkflowValidationError, WorkflowDecisionError)):
        action(workflow, request, kind, **fields)
    assert workflow.history(request["id"]) == before


@pytest.mark.parametrize("status", ["draft", "submitted", "in_review", "needs_information"])
def test_employee_can_cancel_every_active_state(workflow, status):
    request = draft(workflow)
    for name in {
        "draft": [],
        "submitted": ["submit"],
        "in_review": ["submit", "start_review"],
        "needs_information": ["submit", "start_review", "request_information"],
    }[status]:
        request = action(workflow, request, name, comment="Clarify the recipient")
    cancelled = action(workflow, request, "cancel", comment="The request is no longer needed")
    assert cancelled["status"] == "cancelled"
    with pytest.raises(InvalidTransitionError):
        action(workflow, cancelled, "submit")


def test_draft_can_be_incomplete_but_not_submitted_until_valid(workflow):
    request = workflow.create_structured_draft(
        request_type="pto", applicant="employee.demo", approver="manager.demo", title="", comment=""
    )
    with pytest.raises(WorkflowValidationError):
        action(workflow, request, "submit")
    request = workflow.edit_draft(
        request["id"],
        "employee.demo",
        {
            "title": "Family vacation",
            "comment": "Request for two days",
            "start_date": "2030-04-01",
            "end_date": "2030-04-02",
        },
        request["revision"],
    )
    assert action(workflow, request, "submit")["duration_days"] == 2


def test_stale_decision_cannot_overwrite_a_later_review_round(workflow):
    first = review(workflow)
    rejected = decision(workflow, first, "reject")
    appealed = action(workflow, rejected, "appeal", comment="Please review the new facts")
    current = action(workflow, appealed, "start_review")
    before = workflow.history(first["id"])
    with pytest.raises(RequestConflictError):
        decision(workflow, first)
    assert workflow.history(first["id"]) == before
    assert decision(workflow, current)["status"] == "approved"


@pytest.mark.parametrize(
    "role,actor",
    [
        ("employee", "other.employee"),
        ("manager", "other.manager"),
        ("knowledge_admin", "admin.demo"),
    ],
)
def test_unrelated_users_cannot_read_comment_or_download(workflow, role, actor):
    request = review(workflow)
    upload = workflow.attach(
        request["id"],
        "employee.demo",
        "employee",
        "evidence.txt",
        b"Private evidence",
        request["revision"],
    )
    request = upload["request"]
    for read in [
        lambda: workflow.detail(request["id"], actor, role),
        lambda: workflow.comment(request["id"], actor, role, "intrusion", request["revision"]),
        lambda: workflow.attachment(request["id"], upload["attachment"]["id"], actor, role),
    ]:
        with pytest.raises(WorkflowNotFoundError):
            read()
    assert workflow.list_visible(actor, role, q="Private")["total"] == 0
    assert workflow.list_visible(actor, role)["counts"] == {}


def test_employee_cannot_decide_and_manager_cannot_edit_content(workflow):
    request = review(workflow)
    with pytest.raises(WorkflowPermissionError):
        workflow.act(request["id"], "employee.demo", "employee", "approve", request["revision"])
    with pytest.raises(WorkflowNotFoundError):
        workflow.edit_draft(
            request["id"], "manager.demo", {"title": "Changed secretly"}, request["revision"]
        )
    approved = decision(workflow, request)
    with pytest.raises(InvalidTransitionError):
        workflow.edit_draft(
            request["id"],
            "employee.demo",
            {"comment": "Changed after decision"},
            approved["revision"],
        )
    with pytest.raises(InvalidTransitionError):
        decision(workflow, approved, "reject")


def test_comments_and_audit_cannot_be_rewritten_or_deleted(workflow):
    request = review(workflow)
    workflow.comment(request["id"], "employee.demo", "employee", "Evidence", request["revision"])
    for statement in [
        "UPDATE request_events SET details='{}'",
        "DELETE FROM request_events",
        "UPDATE request_comments SET body='changed'",
        "DELETE FROM request_comments",
    ]:
        with closing(sqlite3.connect(workflow.store.db_path)) as conn, conn:
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                conn.execute(statement)


def test_search_filters_sorting_pagination_are_scoped_and_unicode_aware(workflow):
    high = draft(workflow, priority="high")
    high = workflow.edit_draft(
        high["id"], "employee.demo", {"title": "Справка о работе"}, high["revision"]
    )
    normal = draft(workflow)
    workflow.create_structured_draft(
        request_type="document",
        title="Private",
        comment="Not visible",
        applicant="other",
        approver="other.manager",
    )
    found = workflow.list_visible(
        "employee.demo",
        "employee",
        q="СПРАВКА",
        category="document",
        priority="high",
        status="draft",
    )
    assert [r["id"] for r in found["requests"]] == [high["id"]]
    first = workflow.list_visible("employee.demo", "employee", sort="number", order="asc", limit=1)
    second = workflow.list_visible(
        "employee.demo", "employee", sort="number", order="asc", limit=1, offset=1
    )
    assert first["total"] == second["total"] == 2
    assert first["requests"][0]["id"] == high["id"] and second["requests"][0]["id"] == normal["id"]
    assert (
        workflow.list_visible("employee.demo", "employee", q=f"REQ-{high['number']:06d}")["total"]
        == 1
    )
    assert workflow.list_visible("employee.demo", "employee", q="' OR 1=1 --")["total"] == 0
    request = action(workflow, high, "submit")
    workflow.comment(
        request["id"],
        "employee.demo",
        "employee",
        "Unique additional evidence",
        request["revision"],
    )
    assert workflow.list_visible("manager.demo", "manager", q="additional evidence")["total"] == 1


@pytest.mark.parametrize(
    "filename,content",
    [
        ("../secret.txt", b"x"),
        ("program.exe", b"MZ"),
        ("spoof.pdf", b"not a pdf"),
        ("invalid.txt", b"\x00"),
        ("empty.txt", b""),
        ("large.txt", b"a" * (5 * 1024 * 1024 + 1)),
    ],
    ids=["traversal", "executable", "spoof", "binary-text", "empty", "too-large"],
)
def test_invalid_attachments_leave_no_partial_rows(workflow, filename, content):
    request = draft(workflow)
    before = workflow.history(request["id"])
    with pytest.raises(WorkflowValidationError):
        workflow.attach(
            request["id"], "employee.demo", "employee", filename, content, request["revision"]
        )
    assert workflow.history(request["id"]) == before


def test_api_access_filters_fields_and_attachment_download(workflow):
    runtime = get_runtime()
    identity = DEMO_IDENTITIES["employee"]
    app.dependency_overrides[current_identity] = lambda: identity
    try:
        with patch.object(runtime, "workflow_service", workflow), TestClient(app) as client:
            payload = {"type": "document", "title": "Letter", "comment": "Relevant facts"}
            for field in ("applicant", "approver", "status", "gender", "race", "religion"):
                assert (
                    client.post(
                        "/api/v1/requests", json={**payload, field: "untrusted"}
                    ).status_code
                    == 422
                )
            request = client.post("/api/v1/requests", json=payload).json()["request"]
            path = f"/api/v1/requests/{request['id']}"
            assert client.post(path + "/submit", json={}).status_code == 422
            uploaded = client.post(
                path + "/attachments",
                data={"expected_revision": request["revision"]},
                files={"file": ("evidence.txt", b"Private evidence", "text/plain")},
            )
            assert uploaded.status_code == 201
            upload = uploaded.json()
            download_path = path + "/attachments/" + upload["attachment"]["id"]
            response = client.get(download_path)
            assert (
                response.content == b"Private evidence"
                and response.headers["x-content-type-options"] == "nosniff"
            )
            assert response.headers["content-disposition"].startswith("attachment;")
            assert (
                client.post(
                    path + "/submit", json={"expected_revision": upload["request"]["revision"]}
                ).status_code
                == 200
            )
            for identity in [
                DemoIdentity("other", "other", "Other", "employee"),
                DemoIdentity("other.manager", "other.manager", "Other manager", "manager"),
                DEMO_IDENTITIES["knowledge_admin"],
            ]:
                expected = 403 if identity.role == "knowledge_admin" else 404
                assert client.get(path).status_code == expected
                assert client.get(download_path).status_code == expected
                assert (
                    client.post(
                        path + "/comments", json={"body": "Intrusion", "expected_revision": 3}
                    ).status_code
                    == expected
                )
            identity = DEMO_IDENTITIES["manager"]
            assert client.get(path).status_code == 200
            assert client.get("/api/v1/requests?sort=malicious").status_code == 422
            assert client.get("/api/v1/requests?status=declined").status_code == 422
    finally:
        app.dependency_overrides.pop(current_identity, None)


def test_reassignment_revokes_previous_manager_access_and_is_audited(workflow):
    request = review(workflow)
    with patch.dict(
        DEMO_IDENTITIES,
        {
            "second_manager": DemoIdentity(
                "second.manager", "second_manager", "Second Manager", "manager"
            )
        },
    ):
        moved = workflow.assign(
            request["id"],
            "manager.demo",
            "second.manager",
            "Reassigned for another review",
            request["revision"],
        )
    with pytest.raises(WorkflowNotFoundError):
        workflow.detail(request["id"], "manager.demo", "manager")
    detail = workflow.detail(request["id"], "second.manager", "manager")
    assert detail["request"]["approver"] == "second.manager"
    assert detail["events"][-1]["details"]["changes"]["approver"] == {
        "before": "manager.demo",
        "after": "second.manager",
    }
    with pytest.raises(WorkflowNotFoundError):
        workflow.act(
            request["id"],
            "manager.demo",
            "manager",
            "reject",
            moved["revision"],
            comment="Old manager",
            basis="Policy",
            fair_review_confirmed=True,
        )


def test_attachment_limit_and_stale_retry_are_atomic(workflow):
    request = draft(workflow)
    first_revision = request["revision"]
    for index in range(5):
        request = workflow.attach(
            request["id"],
            "employee.demo",
            "employee",
            f"evidence-{index}.txt",
            b"Evidence",
            request["revision"],
        )["request"]
    before = workflow.history(request["id"])
    with pytest.raises(WorkflowValidationError):
        workflow.attach(
            request["id"],
            "employee.demo",
            "employee",
            "sixth.txt",
            b"Evidence",
            request["revision"],
        )
    with pytest.raises(RequestConflictError):
        workflow.attach(
            request["id"], "employee.demo", "employee", "retry.txt", b"Evidence", first_revision
        )
    assert workflow.history(request["id"]) == before


def test_identical_rules_apply_to_different_employee_identities(workflow):
    for employee in ("employee.one", "employee.two"):
        request = workflow.create_structured_draft(
            request_type="document",
            title="Letter",
            comment="Same relevant facts",
            applicant=employee,
            approver="manager.demo",
        )
        request = workflow.act(request["id"], employee, "employee", "submit", request["revision"])
        request = action(workflow, request, "start_review")
        assert decision(workflow, request)["status"] == "approved"


def test_cancelled_private_draft_never_discloses_content_or_attachments_to_manager(workflow):
    request = draft(workflow)
    uploaded = workflow.attach(
        request["id"],
        "employee.demo",
        "employee",
        "private.txt",
        b"Private draft evidence",
        request["revision"],
    )
    cancelled = action(
        workflow, uploaded["request"], "cancel", comment="Do not submit this private draft"
    )
    for service in (workflow, WorkflowService(str(workflow.store.db_path))):
        assert service.list_visible("manager.demo", "manager")["total"] == 0
        assert service.list_visible("manager.demo", "manager")["counts"] == {}
        assert (
            service.detail(request["id"], "employee.demo", "employee")["request"]["status"]
            == "cancelled"
        )
        with pytest.raises(WorkflowNotFoundError):
            service.detail(request["id"], "manager.demo", "manager")
        with pytest.raises(WorkflowNotFoundError):
            service.attachment(
                request["id"], uploaded["attachment"]["id"], "manager.demo", "manager"
            )
        with pytest.raises(WorkflowNotFoundError):
            service.comment(
                request["id"], "manager.demo", "manager", "Not shared", cancelled["revision"]
            )


def test_cancellation_after_submission_remains_visible_to_assigned_manager(workflow):
    request = action(workflow, draft(workflow), "submit")
    cancelled = action(workflow, request, "cancel", comment="Plans changed after submission")
    assert workflow.detail(request["id"], "manager.demo", "manager")["request"] == {
        **cancelled,
        "manager_attention": {"due_at": None, "overdue": False, "reasons": []},
    }
    assert workflow.list_visible("manager.demo", "manager", status="cancelled")["total"] == 1
