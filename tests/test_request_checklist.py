"""API acceptance checks, including actual process restart and concurrent writers."""

import json
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import app
from services.auth_service import DEMO_IDENTITIES, DemoAuthService, DemoIdentity
from services.runtime import get_runtime
from services.workflow_service import WorkflowService

PAYLOAD = {
    "type": "pto",
    "title": "Проверка сохранения",
    "comment": "Relevant request facts",
    "priority": "urgent",
    "start_date": "2031-02-03",
    "end_date": "2031-02-07",
}
REASON = {
    "comment": "Reason based on the submitted evidence",
    "basis": "Policy section 2",
    "fair_review_confirmed": True,
}
EMPLOYEE_ACTIONS = {"submit", "provide_information", "cancel", "appeal"}
# Acceptance matrix is independent of the implementation's policy constants.
TRANSITIONS = {
    "draft": {"submit": "submitted", "cancel": "cancelled"},
    "submitted": {"start_review": "in_review", "cancel": "cancelled"},
    "in_review": {
        "request_information": "needs_information",
        "approve": "approved",
        "reject": "rejected",
        "cancel": "cancelled",
    },
    "needs_information": {"provide_information": "in_review", "cancel": "cancelled"},
    "approved": {"complete": "completed", "appeal": "submitted"},
    "rejected": {"appeal": "submitted"},
    "cancelled": {},
    "completed": {"appeal": "submitted"},
}
PATHS = {
    "draft": (),
    "submitted": ("submit",),
    "in_review": ("submit", "start_review"),
    "needs_information": ("submit", "start_review", "request_information"),
    "approved": ("submit", "start_review", "approve"),
    "rejected": ("submit", "start_review", "reject"),
    "cancelled": ("submit", "cancel"),
    "completed": ("submit", "start_review", "approve", "complete"),
}


@pytest.fixture
def workflow(tmp_path):
    return WorkflowService(str(tmp_path / "requests.db"))


@pytest.fixture
def client(workflow):
    with patch.object(get_runtime(), "workflow_service", workflow), TestClient(app) as api:
        yield api


def headers(role):
    return {
        "Authorization": "Bearer " + get_runtime().auth_service.issue_token(DEMO_IDENTITIES[role])
    }


def make_request(workflow, status="draft"):
    request = workflow.create_structured_draft(
        request_type=PAYLOAD["type"],
        applicant="employee.demo",
        approver="manager.demo",
        **{key: value for key, value in PAYLOAD.items() if key != "type"},
    )
    for name in PATHS[status]:
        role = "employee" if name in EMPLOYEE_ACTIONS else "manager"
        request = workflow.act(
            request["id"], role + ".demo", role, name, request["revision"], **REASON
        )
    return request


@pytest.mark.parametrize("status", TRANSITIONS)
def test_api_transition_matrix_and_role_guards(client, workflow, status):
    actions = {action for targets in TRANSITIONS.values() for action in targets}
    for role in ("employee", "manager"):
        for name in sorted(actions):
            request = make_request(workflow, status)
            before = workflow.history(request["id"])
            required_role = "employee" if name in EMPLOYEE_ACTIONS else "manager"
            response = client.post(
                f"/api/v1/requests/{request['id']}/actions/{name}",
                headers=headers(role),
                json={"expected_revision": request["revision"], **REASON},
            )
            expected = (
                403
                if role != required_role
                else 404
                if role == "manager" and status == "draft"
                else 200
                if name in TRANSITIONS[status]
                else 409
            )
            assert response.status_code == expected, (status, role, name, response.text)
            after = workflow.history(request["id"])
            if expected != 200:
                assert after == before
                continue
            assert after["request"]["status"] == TRANSITIONS[status][name]
            assert after["request"]["revision"] == request["revision"] + 1
            assert len(after["events"]) == len(before["events"]) + 1
            event = after["events"][-1]
            assert event["actor"] == role + ".demo"
            assert datetime.fromisoformat(event["created_at"]).tzinfo is not None
            assert event["details"]["changes"]["status"] == {
                "before": status,
                "after": TRANSITIONS[status][name],
            }


def test_authenticated_employee_and_legacy_self_assigned_manager_cannot_self_review(
    client, workflow
):
    request = make_request(workflow, "in_review")
    path = f"/api/v1/requests/{request['id']}"
    response = client.post(
        path + "/actions/approve",
        headers={**headers("employee"), "X-Role": "manager"},
        json={"expected_revision": request["revision"], **REASON},
    )
    assert response.status_code == 403
    assert (
        client.post("/api/v1/requests", headers=headers("manager"), json=PAYLOAD).status_code == 403
    )
    # Simulate a malformed legacy assignment; even a real manager token cannot decide it.
    with closing(sqlite3.connect(workflow.store.db_path)) as connection, connection:
        connection.execute(
            "UPDATE workflow_requests SET applicant='manager.demo' WHERE id=?", (request["id"],)
        )
    before = workflow.history(request["id"])
    assert client.get(path, headers=headers("manager")).json()["allowed_actions"] == []
    for action in ("approve", "reject", "request_information"):
        assert (
            client.post(
                path + "/actions/" + action,
                headers=headers("manager"),
                json={"expected_revision": request["revision"], **REASON},
            ).status_code
            == 403
        )
    assert workflow.history(request["id"]) == before


def test_concurrent_api_draft_updates_reject_one_writer_without_lost_fields(client, workflow):
    request = make_request(workflow)
    path = f"/api/v1/requests/{request['id']}"
    changes = [{"title": "First editor title"}, {"priority": "low"}]

    def update(fields):
        return client.patch(
            path,
            headers=headers("employee"),
            json={"expected_revision": request["revision"], **fields},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(update, changes))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(i for i, response in enumerate(responses) if response.status_code == 200)
    persisted = client.get(path, headers=headers("employee")).json()
    assert persisted["request"] == responses[winner].json()["request"]
    assert len(persisted["events"]) == 2
    # Explicitly reload and apply the other field: both edits now survive.
    merged = client.patch(
        path,
        headers=headers("employee"),
        json={"expected_revision": persisted["request"]["revision"], **changes[1 - winner]},
    )
    assert merged.status_code == 200
    assert merged.json()["request"]["title"] == "First editor title"
    assert merged.json()["request"]["priority"] == "low"


def test_concurrent_numbers_and_all_fields_are_persistent(workflow):
    with ThreadPoolExecutor(max_workers=4) as pool:
        created = list(pool.map(lambda _: make_request(workflow), range(8)))
    assert len({request["number"] for request in created}) == len(created)
    assert len({request["id"] for request in created}) == len(created)
    restarted = WorkflowService(str(workflow.store.db_path))
    for request in created:
        assert restarted.detail(request["id"], "employee.demo", "employee")["request"] == {
            key: value for key, value in request.items() if key != "validation_errors"
        }
        assert all(request[key] == value for key, value in PAYLOAD.items())
        assert request["applicant"] == "employee.demo" and request["approver"] == "manager.demo"
        assert request["duration_days"] == 5
    assert make_request(restarted)["number"] > max(item["number"] for item in created)


@pytest.mark.parametrize("sort", ["created_at", "updated_at", "number", "title", "priority"])
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_api_filters_and_sort_orders(client, workflow, sort, order):
    requests = []
    for title, priority in (
        ("Янтарь", "normal"),
        ("Бета", "urgent"),
        ("alpha", "low"),
        ("delta", "high"),
    ):
        request = make_request(workflow)
        requests.append(
            workflow.edit_draft(
                request["id"],
                "employee.demo",
                {"title": title, "priority": priority},
                request["revision"],
            )
        )

    def key(item):
        return (
            {"low": 0, "normal": 1, "high": 2, "urgent": 3}[item[sort]]
            if sort == "priority"
            else item[sort].casefold()
            if sort == "title"
            else item[sort]
        )

    expected = sorted(requests, key=key, reverse=order == "desc")
    actual = client.get(
        "/api/v1/requests",
        headers=headers("employee"),
        params={"sort": sort, "order": order, "limit": 2, "offset": 1},
    ).json()
    assert actual["total"] == 4
    assert [item["id"] for item in actual["requests"]] == [item["id"] for item in expected[1:3]]
    found = client.get(
        "/api/v1/requests",
        headers=headers("employee"),
        params={"q": "БЕТА", "status": "draft", "category": "pto", "priority": "urgent"},
    ).json()
    assert [item["id"] for item in found["requests"]] == [requests[1]["id"]]
    assert (
        client.get("/api/v1/requests", headers=headers("manager"), params={"q": "БЕТА"}).json()[
            "total"
        ]
        == 0
    )


@contextmanager
def running_api(folder, env, *, extra_identity=None, proxy_headers=False):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    # Windows venv Python can be a redirector with a separate child process.
    # Ask the actual server to exit, rather than terminating only its launcher
    # and racing its child for the temporary log file during pytest cleanup.
    runner = (
        "import json, sys, threading, uvicorn\n"
        "from services.auth_service import DEMO_IDENTITIES, DemoIdentity\n"
        "extra = json.loads(sys.argv[2])\n"
        "if extra:\n"
        "    DEMO_IDENTITIES[extra['username']] = DemoIdentity(**extra)\n"
        "server = uvicorn.Server(uvicorn.Config('app:app', host='127.0.0.1', "
        "port=int(sys.argv[1]), proxy_headers=json.loads(sys.argv[3]), "
        "log_level='warning', access_log=False))\n"
        "def stop_when_requested():\n"
        "    sys.stdin.buffer.read(1)\n"
        "    server.should_exit = True\n"
        "threading.Thread(target=stop_when_requested, daemon=True).start()\n"
        "server.run()\n"
    )
    with (folder / "server.log").open("ab") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                runner,
                str(port),
                json.dumps(extra_identity.public_dict() if extra_identity else None),
                json.dumps(proxy_headers),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                deadline = time.monotonic() + 45
                while True:
                    try:
                        if client.get("/api/v1/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    assert process.poll() is None, (
                        "Test API failed to start: "
                        + (folder / "server.log").read_text(errors="replace")[-2000:]
                    )
                    assert time.monotonic() < deadline, "Test API startup timed out"
                    time.sleep(0.1)
                yield client, process.pid
        finally:
            try:
                process.communicate(input=b"x", timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                        timeout=10,
                    )
                else:
                    process.kill()
                process.communicate(timeout=10)


@pytest.mark.parametrize(
    "startup_source", ["README.md", "run_demo.ps1", "Dockerfile", "smoke_check.ps1"]
)
def test_documented_server_startups_cannot_spoof_login_throttle_peer(tmp_path, startup_source):
    source = Path(__file__).resolve().parents[1] / startup_source
    command = next(
        line for line in source.read_text(encoding="utf-8").splitlines() if "uvicorn" in line
    )
    # Exercise the actual Uvicorn transport boundary, which TestClient bypasses.
    # Derive its proxy option from each supported command, including the default
    # when the protective flag is missing. The last explicit option wins.
    proxy_headers = True
    for option in re.findall(r"--[\w-]+", command):
        if option in {"--proxy-headers", "--no-proxy-headers"}:
            proxy_headers = option == "--proxy-headers"
    env = {
        **os.environ,
        "WORKFLOW_DB": str(tmp_path / "login.db"),
        "DEMO_AUTH_SECRET": secrets.token_urlsafe(32),
        "DEMO_LOGIN_PASSWORD": secrets.token_urlsafe(20),
        "PYTHON_DOTENV_DISABLED": "1",
        "OPENAI_API_KEY": "",
        "FORWARDED_ALLOW_IPS": "*",
    }
    with running_api(tmp_path, env, proxy_headers=proxy_headers) as (client, _):
        credentials = {"username": "employee", "password": "incorrect-synthetic-password"}
        for _ in range(10):
            assert client.post("/api/v1/auth/login", json=credentials).status_code == 401
        assert client.post("/api/v1/auth/login", json=credentials).status_code == 429
        for forwarded_ip in ("198.51.100.33", "203.0.113.10, 198.51.100.34"):
            response = client.post(
                "/api/v1/auth/login",
                json=credentials,
                headers={"X-Forwarded-For": forwarded_ip, "X-Forwarded-Proto": "https"},
            )
            assert response.status_code == 429, startup_source
            assert 1 <= int(response.headers["retry-after"]) <= 60


def test_draft_decisions_journal_and_attachments_survive_actual_api_restart(tmp_path):
    env = {
        **os.environ,
        "WORKFLOW_DB": str(tmp_path / "restart.db"),
        "DEMO_AUTH_SECRET": secrets.token_urlsafe(32),
        "DEMO_LOGIN_PASSWORD": secrets.token_urlsafe(20),
        "PYTHON_DOTENV_DISABLED": "1",
        "OPENAI_API_KEY": "",
    }
    # This identity is registered only inside the isolated test subprocesses.
    # Production accounts and the working database are never modified.
    specialist = DemoIdentity(
        "manager.restart.test", "restart_manager", "Synthetic Restart Manager", "manager"
    )
    # The demo login form intentionally supports only its three built-in names.
    # Give the synthetic registered identity a normally signed token; every
    # request still goes through the server's identity and permission checks.
    specialist_auth = DemoAuthService(env["DEMO_AUTH_SECRET"], env["DEMO_LOGIN_PASSWORD"])

    def login(client, role):
        response = client.post(
            "/api/v1/auth/login", json={"username": role, "password": env["DEMO_LOGIN_PASSWORD"]}
        )
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    with running_api(tmp_path, env, extra_identity=specialist) as (client, first_pid):
        employee, manager = login(client, "employee"), login(client, "manager")
        other_manager = {"Authorization": "Bearer " + specialist_auth.issue_token(specialist)}
        snapshots, attachment_paths = [], []
        for complete in (False, True):
            response = client.post("/api/v1/requests", headers=employee, json=PAYLOAD)
            assert response.status_code == 201
            request = response.json()["request"]
            path = f"/api/v1/requests/{request['id']}"
            upload = client.post(
                path + "/attachments",
                headers=employee,
                data={"expected_revision": request["revision"]},
                files={"file": ("сведения.txt", "Сохранённое вложение".encode(), "text/plain")},
            )
            assert upload.status_code == 201
            request = upload.json()["request"]
            attachment_paths.append(path + "/attachments/" + upload.json()["attachment"]["id"])
            if complete:
                assigned_manager = manager
                for name in (
                    "submit",
                    "start_review",
                    "request_information",
                    "provide_information",
                    "reject",
                    "appeal",
                    "start_review",
                    "approve",
                    "complete",
                ):
                    response = client.post(
                        path + "/actions/" + name,
                        headers=employee if name in EMPLOYEE_ACTIONS else assigned_manager,
                        json={"expected_revision": request["revision"], **REASON},
                    )
                    assert response.status_code == 200, response.text
                    request = response.json()["request"]
                    if name == "provide_information":
                        reassigned = client.post(
                            path + "/assign",
                            headers=manager,
                            json={
                                "expected_revision": request["revision"],
                                "assignee": specialist.id,
                                "comment": "The specialist will finish the evidence review.",
                            },
                        )
                        assert reassigned.status_code == 200, reassigned.text
                        request = reassigned.json()["request"]
                        assigned_manager = other_manager
            snapshots.append(client.get(path, headers=employee).json())
        assert [item["request"]["status"] for item in snapshots] == ["draft", "completed"]
        decisions = [
            event for event in snapshots[1]["events"] if event["event_type"] == "decision_recorded"
        ]
        assert [event["to_status"] for event in decisions] == ["rejected", "approved"]
        assert all(event["details"]["comment"] == REASON["comment"] for event in decisions)
        assert all(event["actor"] == specialist.id for event in decisions)
        assert len(snapshots[1]["comments"]) == 2
        assignments = [
            event for event in snapshots[1]["events"] if event["event_type"] == "assignee_changed"
        ]
        assert len(assignments) == 1
        assert assignments[0]["actor"] == "manager.demo"
        assert datetime.fromisoformat(assignments[0]["created_at"]).tzinfo is not None
        assert assignments[0]["details"]["changes"]["approver"] == {
            "before": "manager.demo",
            "after": specialist.id,
        }
        assert (
            assignments[0]["details"]["comment"]
            == "The specialist will finish the evidence review."
        )
        completed_path = f"/api/v1/requests/{snapshots[1]['request']['id']}"
        assert client.get(completed_path, headers=manager).status_code == 404
        manager_snapshot_response = client.get(completed_path, headers=other_manager)
        assert manager_snapshot_response.status_code == 200
        manager_snapshot = manager_snapshot_response.json()
        assert manager_snapshot["request"]["approver"] == specialist.id
    with running_api(tmp_path, env, extra_identity=specialist) as (client, second_pid):
        assert second_pid != first_pid
        employee, manager = login(client, "employee"), login(client, "manager")
        other_manager = {"Authorization": "Bearer " + specialist_auth.issue_token(specialist)}
        for snapshot, attachment_path in zip(snapshots, attachment_paths):
            path = f"/api/v1/requests/{snapshot['request']['id']}"
            assert client.get(path, headers=employee).json() == snapshot
            assert (
                client.get(attachment_path, headers=employee).content
                == "Сохранённое вложение".encode()
            )
            assert client.get(path, headers=manager).status_code == 404
            assert client.get(path, headers=other_manager).status_code == (
                404 if snapshot["request"]["status"] == "draft" else 200
            )
            assert client.get(attachment_path, headers=manager).status_code == 404
        assert client.get(attachment_paths[0], headers=manager).status_code == 404
        assert client.get(attachment_paths[0], headers=other_manager).status_code == 404
        assert client.get(completed_path, headers=other_manager).json() == manager_snapshot
        assert (
            client.get(attachment_paths[1], headers=other_manager).content
            == "Сохранённое вложение".encode()
        )
        queue = client.get("/api/v1/requests", headers=manager).json()
        assert queue["total"] == 0 and queue["requests"] == []
        assert client.get("/api/v1/manager/activity", headers=manager).json()["total"] == 0
        queue = client.get("/api/v1/requests", headers=other_manager).json()
        assert [item["id"] for item in queue["requests"]] == [snapshots[1]["request"]["id"]]
        activity = client.get("/api/v1/manager/activity", headers=other_manager).json()
        assert activity["total"] == len(manager_snapshot["events"])
        assert {event["id"] for event in activity["events"]} == {
            event["id"] for event in manager_snapshot["events"]
        }
        draft = snapshots[0]["request"]
        cancelled = client.post(
            f"/api/v1/requests/{draft['id']}/actions/cancel",
            headers=employee,
            json={
                "expected_revision": draft["revision"],
                "comment": "Keep this unsubmitted draft private",
            },
        )
        assert cancelled.status_code == 200
        assert client.get(attachment_paths[0], headers=manager).status_code == 404
        assert (
            client.get("/api/v1/requests", headers=manager, params={"status": "cancelled"}).json()[
                "total"
            ]
            == 0
        )
