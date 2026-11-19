"""Create retries are scoped to the author and never silently replace saved content."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from api.v1_dependencies import current_identity
from app import app
from domain.request_policy import RequestConflictError
from services.auth_service import DEMO_IDENTITIES, DemoIdentity
from services.runtime import get_runtime
from services.workflow_service import WorkflowService

CREATION_KEY = "d050b474-5c33-4607-8533-6a1a93a7dd04"
FIELDS = {
    "request_type": "document",
    "title": "Employment letter",
    "comment": "Please confirm my role and dates.",
    "priority": "high",
    "start_date": "2030-05-01",
    "end_date": "2030-05-03",
    "applicant": "employee.demo",
    "approver": "manager.demo",
}


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch):
    monkeypatch.setattr(
        "http.client.HTTPSConnection",
        Mock(side_effect=AssertionError("No live delivery in request tests")),
    )


@pytest.fixture
def workflow(tmp_path):
    return WorkflowService(str(tmp_path / "creation.db"))


def create(workflow, **changes):
    return workflow.create_structured_draft(**{**FIELDS, "creation_key": CREATION_KEY, **changes})


def test_parallel_create_retries_share_one_number_and_history_event(workflow):
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: create(workflow), range(8)))
    assert len({item["id"] for item in records}) == 1
    assert len({item["number"] for item in records}) == 1
    history = workflow.history(records[0]["id"])
    assert len(history["events"]) == 1
    assert history["events"][0]["event_type"] == "draft_created"
    assert workflow.list_for_user("employee.demo") == [history["request"]]
    assert create(workflow, creation_key=str(uuid.uuid4()))["number"] == records[0]["number"] + 1


def test_retry_after_restart_recovers_the_same_draft_without_changing_saved_data(workflow):
    created = create(workflow)
    before = workflow.history(created["id"])
    restarted = WorkflowService(str(workflow.store.db_path))
    retried = create(restarted)
    assert retried == created
    assert restarted.history(created["id"]) == before
    assert len(restarted.list_for_user("employee.demo")) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Changed title"},
        {"comment": "Changed explanation"},
        {"priority": "urgent"},
        {"request_type": "pto"},
        {"start_date": "2030-04-30"},
        {"end_date": "2030-05-04"},
        {"approver": "another.manager"},
    ],
)
def test_changed_retry_fields_conflict_and_preserve_the_original_record(workflow, changes):
    original = create(workflow)
    before = workflow.history(original["id"])
    with pytest.raises(RequestConflictError, match=f"REQ-{original['number']:06d}.*My requests"):
        create(workflow, **changes)
    assert workflow.history(original["id"]) == before
    assert len(workflow.list_for_user("employee.demo")) == 1


def test_same_key_for_another_owner_creates_an_independent_private_draft(workflow):
    first = create(workflow)
    other = create(workflow, applicant="other.employee")
    assert first["id"] != other["id"] and first["number"] != other["number"]
    assert [item["id"] for item in workflow.list_for_user("employee.demo")] == [first["id"]]
    assert [item["id"] for item in workflow.list_for_user("other.employee")] == [other["id"]]
    assert create(workflow, applicant="other.employee")["id"] == other["id"]


@pytest.mark.parametrize("action", ["edit", "submit"])
def test_later_changes_are_not_silently_replayed_or_overwritten(workflow, action):
    original = create(workflow)
    if action == "edit":
        workflow.edit_draft(
            original["id"], "employee.demo", {"title": "A later edit"}, original["revision"]
        )
    else:
        workflow.confirm_draft(original["id"], "employee.demo", {}, revision=original["revision"])
    before = workflow.history(original["id"])
    with pytest.raises(RequestConflictError, match="already saved"):
        create(workflow)
    assert workflow.history(original["id"]) == before
    assert len(workflow.list_for_user("employee.demo")) == 1


def test_legacy_creates_remain_compatible_and_existing_records_are_untouched(workflow):
    legacy = workflow.create_structured_draft(**FIELDS)
    before = workflow.history(legacy["id"])
    another = workflow.create_structured_draft(**FIELDS)
    keyed = create(workflow)
    assert len({legacy["id"], another["id"], keyed["id"]}) == 3
    assert workflow.history(legacy["id"]) == before


def test_create_api_recovers_a_lost_response_and_reports_changed_retry_without_exposing_another_owner(
    workflow,
):
    payload = {
        key: value
        for key, value in FIELDS.items()
        if key not in {"applicant", "approver", "request_type"}
    }
    payload.update(type=FIELDS["request_type"], creation_key=CREATION_KEY)
    identity = DEMO_IDENTITIES["employee"]
    app.dependency_overrides[current_identity] = lambda: identity
    try:
        with patch.object(get_runtime(), "workflow_service", workflow), TestClient(app) as client:
            first = client.post("/api/v1/requests", json=payload)
            assert first.status_code == 201
            repeated = client.post("/api/v1/requests", json=payload)
            assert repeated.status_code == 201 and repeated.json() == first.json()
            number = first.json()["request"]["number"]
            changed = client.post("/api/v1/requests", json={**payload, "title": "New local title"})
            assert changed.status_code == 409
            assert f"REQ-{number:06d}" in changed.json()["detail"]
            assert "My requests" in changed.json()["detail"]
            assert len(workflow.list_for_user("employee.demo")) == 1
            assert (
                client.post(
                    "/api/v1/requests", json={**payload, "creation_key": "not-a-uuid"}
                ).status_code
                == 422
            )
            identity = DemoIdentity(
                "other.employee",
                "other.employee",
                "Other Employee",
                "employee",
                manager_id="manager.demo",
            )
            other = client.post("/api/v1/requests", json=payload)
            assert (
                other.status_code == 201
                and other.json()["request"]["id"] != first.json()["request"]["id"]
            )
            identity = DEMO_IDENTITIES["manager"]
            assert client.post("/api/v1/requests", json=payload).status_code == 403
    finally:
        app.dependency_overrides.pop(current_identity, None)
