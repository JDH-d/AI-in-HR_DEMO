"""Employee integration against a real, isolated FastAPI subprocess.

After installing the repository's requirements-dev.txt, the root pytest command
includes this suite. To run it alone from the repository root:
    .venv/Scripts/python.exe -B -m pytest slack/tests/test_end_to_end.py -p no:cacheprovider
On POSIX, use .venv/bin/python. Backend and Slack share this interpreter.

The backend interpreter is discovered in this order:
1. PEOPLEFLOW_TEST_PYTHON (an explicit executable path; relative to ROOT if needed).
2. ROOT/.venv/Scripts/python.exe on Windows, or ROOT/.venv/bin/python on POSIX.
The selected environment must already contain the backend dependencies. A missing
interpreter fails with setup guidance; an invalid explicit override never falls
back silently. Root pytest adds the local Slack package to its import path; CI
sets PEOPLEFLOW_TEST_PYTHON to its configured Python runtime.

Only Slack delivery is faked. Employee operations use the installed
PeopleFlowClient; manager/admin HTTP calls are external test actors. The replace
test additionally injects an NDJSON fault at the HTTP transport boundary, while
retaining the real backend's persisted answer and complete event.
"""

from __future__ import annotations

import copy
import ctypes
import html
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from slack_sdk import WebClient

from peopleflow_slack.application import EmployeeApp
from peopleflow_slack.client import APIError, PeopleFlowClient
from peopleflow_slack.config import Settings
from peopleflow_slack.store import Store

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work" / "slack-e2e"
TEAM = "TE2EWORKSPACE"
MEMBER = "UE2EEMPLOYEE"
DM = "DE2EEMPLOYEE"
PASSWORD = "isolated-e2e-password"
QUESTION = "When is payroll processed?"
ROOT_TS = "1800000000.000001"
PTO = {
    "type": "pto",
    "start_date": "2030-04-01",
    "end_date": "2030-04-03",
    "comment": "Coverage is arranged with my team.",
    "details": {},
}


def backend_python(root: Path) -> Path:
    """Resolve an existing backend interpreter without modifying any environment."""
    explicit = os.environ.get("PEOPLEFLOW_TEST_PYTHON", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_file():
            return candidate.resolve()
        pytest.fail(
            f"PEOPLEFLOW_TEST_PYTHON is not an existing executable file: {candidate}. "
            "Set it to a Python interpreter with the backend dependencies installed.",
            pytrace=False,
        )

    executable = Path("Scripts/python.exe" if os.name == "nt" else "bin/python")
    candidates = [root / ".venv" / executable]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    pytest.fail(
        "No backend Python interpreter was found. Checked: "
        + ", ".join(str(path) for path in candidates)
        + ". Install the backend dependencies in ROOT/.venv, or set "
        "PEOPLEFLOW_TEST_PYTHON to an existing backend Python executable.",
        pytrace=False,
    )


@pytest.fixture
def tmp_path():
    """Keep generated state in the project's ignored work directory."""
    WORK.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="employee-e2e-", dir=WORK) as directory:
        path = Path(directory).resolve()
        assert path.is_relative_to(WORK.resolve())
        yield path


@pytest.mark.parametrize("preferred", ["explicit", "checkout"])
def test_backend_python_discovery_priority(tmp_path, monkeypatch, preferred):
    root = tmp_path / "normal-checkout"
    executable = Path("Scripts/python.exe" if os.name == "nt" else "bin/python")
    candidates = {
        "explicit": root / "custom-environment" / executable,
        "checkout": root / ".venv" / executable,
    }
    names = list(candidates)
    for name in names[names.index(preferred) :]:
        candidates[name].parent.mkdir(parents=True, exist_ok=True)
        candidates[name].touch()
    monkeypatch.delenv("PEOPLEFLOW_TEST_PYTHON", raising=False)
    if preferred == "explicit":
        # Relative overrides are anchored to the checkout, not pytest's working directory.
        monkeypatch.setenv("PEOPLEFLOW_TEST_PYTHON", str(candidates[preferred].relative_to(root)))
    assert backend_python(root) == candidates[preferred].resolve()


@pytest.mark.parametrize("invalid_override", [False, True])
def test_backend_python_missing_fails_with_setup_guidance(tmp_path, monkeypatch, invalid_override):
    root = tmp_path / "normal-checkout"
    monkeypatch.delenv("PEOPLEFLOW_TEST_PYTHON", raising=False)
    if invalid_override:
        executable = Path("Scripts/python.exe" if os.name == "nt" else "bin/python")
        fallback = root / ".venv" / executable
        fallback.parent.mkdir(parents=True)
        fallback.touch()
        monkeypatch.setenv("PEOPLEFLOW_TEST_PYTHON", str(tmp_path / "missing-python"))
    with pytest.raises(pytest.fail.Exception, match="PEOPLEFLOW_TEST_PYTHON") as error:
        backend_python(root)
    if invalid_override:
        assert "not an existing executable file" in str(error.value)
    else:
        assert "No backend Python interpreter was found" in str(error.value)
        assert str(root / ".venv") in str(error.value)


def descendant_pids(parent_pid, parents, created):
    """Reject stale parent links left by Windows PID reuse, including their subtrees."""
    owned = {parent_pid}
    while (
        children := {
            pid
            for pid, parent in parents.items()
            if parent in owned and pid in created and created[pid] >= created[parent]
        }
        - owned
    ):
        owned.update(children)
    return owned - {parent_pid}


def test_child_discovery_excludes_reused_parent_pid_and_unrelated_subtree():
    parents = {200: 100, 201: 200, 202: 100, 203: 202}
    # PID 100 now belongs to the test launcher. PID 202 predates that launcher,
    # despite naming it as parent; even its newer child 203 must remain excluded.
    created = {100: 10, 200: 11, 201: 12, 202: 9, 203: 13}
    assert descendant_pids(100, parents, created) == {200, 201}


@contextmanager
def windows_child_handles(parent_pid):
    """Pin handles to this Popen's descendants before taskkill removes their parent."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD),
            ("heap", ctypes.c_size_t),
            ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD),
            ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
            ("executable", wintypes.WCHAR * 260),
        ]

    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parents = {}
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.pid] = entry.parent
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(snapshot)

    candidates = {parent_pid}
    while (
        descendants := {pid for pid, parent in parents.items() if parent in candidates} - candidates
    ):
        candidates.update(descendants)
    handles = []
    created = {}
    try:
        for pid in sorted(candidates):
            # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, no termination rights.
            handle = kernel.OpenProcess(0x00101000, False, pid)
            if handle:
                handles.append((pid, handle))
                times = [wintypes.FILETIME() for _ in range(4)]
                if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                    raise ctypes.WinError(ctypes.get_last_error())
                created[pid] = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER: already exited
                raise ctypes.WinError(ctypes.get_last_error())
        if parent_pid not in created:
            raise RuntimeError(f"Cannot establish creation time of owned backend PID {parent_pid}")
        owned = descendant_pids(parent_pid, parents, created)
        yield kernel, [(pid, handle) for pid, handle in handles if pid in owned]
    finally:
        for _, handle in handles:
            kernel.CloseHandle(handle)


@dataclass
class Backend:
    url: str
    root: Path
    process: subprocess.Popen

    def stop(self):
        if self.process.poll() is None:
            if os.name == "nt":
                # The venv launcher has a base-Python child holding stdout and the port.
                # Kill the owned tree while its parent still exists, never by image name.
                with windows_child_handles(self.process.pid) as (kernel, children):
                    result = subprocess.run(
                        ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if result.returncode and self.process.poll() is None:
                        raise RuntimeError(f"Owned backend tree stop failed: {result.stderr}")
                    self.process.wait(timeout=5)
                    deadline = time.monotonic() + 5
                    for pid, handle in children:
                        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                        status = kernel.WaitForSingleObject(handle, remaining_ms)
                        # WAIT_OBJECT_0 means process exit, not just termination sent.
                        if status != 0:
                            raise RuntimeError(
                                f"Owned backend child {pid} did not exit within 5s (wait={status})"
                            )
                return
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)

    def role_call(self, role, method, path, payload=None):
        """Manager/admin act over HTTP, never via imported backend services."""
        assert role in {"manager", "knowledge_admin"}
        with httpx.Client(base_url=self.url + "/api/v1/", timeout=5, trust_env=False) as http:
            login = http.post("auth/login", json={"username": role, "password": PASSWORD})
            assert login.status_code == 200, login.text
            token = login.json()["access_token"]
            response = http.request(
                method, path, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
            assert response.is_success, f"{method} {path}: {response.status_code} {response.text}"
            return response.json()


@pytest.fixture
def backend(tmp_path, monkeypatch):
    interpreter = backend_python(ROOT)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    state = tmp_path / "backend"
    state.mkdir()
    shutil.copytree(ROOT / "documents", state / "documents")
    # Prevent the service's read-only legacy prompt fallback from affecting the test.
    (state / "ai_settings.json").write_text(
        json.dumps(
            {
                "settings": {"show_sources": True, "strict_grounding": True},
                "system_prompt": "Answer employee questions in English using approved company documents.",
            }
        ),
        encoding="utf-8",
    )
    state_paths = {
        "DOCUMENTS_DIR": state / "documents",
        "INDEX_PATH": state / "index.json",
        "INDEX_STATUS_PATH": state / "index_status.json",
        "LOG_PATH": state / "chat_logs.jsonl",
        "WORKFLOW_DB": state / "workflow.db",
        "CONVERSATION_DB": state / "conversations.db",
        "AI_SETTINGS_PATH": state / "ai_settings.json",
    }
    assert all(path.resolve().is_relative_to(tmp_path) for path in state_paths.values())
    env = os.environ.copy()
    env.update({key: str(path) for key, path in state_paths.items()})
    env.update(
        {
            "OPENAI_API_KEY": "",
            "OPENAI_MODEL": "isolated-e2e-no-provider",
            "OPENAI_MAX_RETRIES": "0",
            "OPENAI_TIMEOUT_SECONDS": "1",
            "EMBEDDING_MODEL": "isolated-e2e-no-embeddings",
            "DEMO_AUTH_SECRET": "isolated-e2e-signing-secret",
            "DEMO_LOGIN_PASSWORD": PASSWORD,
            "DEMO_TOKEN_TTL_SECONDS": "300",
            "LOG_USER_TEXT_MODE": "off",
            "CORS_ORIGINS": "http://127.0.0.1",
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT),
            "TMP": str(state),
            "TEMP": str(state),
            "TMPDIR": str(state),
        }
    )
    log_path = state / "uvicorn.log"
    active = None
    deadline = time.monotonic() + 20
    try:
        with log_path.open("ab", buffering=0) as output:
            # Retry port allocation if another process wins the bind-after-release race.
            while time.monotonic() < deadline:
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    port = reservation.getsockname()[1]
                process = subprocess.Popen(
                    [
                        str(interpreter),
                        "-B",
                        "-m",
                        "uvicorn",
                        "app:app",
                        "--app-dir",
                        str(ROOT),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--log-level",
                        "warning",
                        "--no-access-log",
                    ],
                    cwd=ROOT,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                active = Backend(f"http://127.0.0.1:{port}", state, process)
                probe = PeopleFlowClient(active.url, PASSWORD, timeout=0.2)
                ready = False
                try:
                    while time.monotonic() < deadline and process.poll() is None:
                        try:
                            ready = probe.health()["status"] == "ok"
                        except APIError:
                            pass
                        if ready:
                            break
                        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                finally:
                    probe.close()
                if ready:
                    break
                active.stop()
                diagnostic = log_path.read_text(encoding="utf-8", errors="replace")
                if "address already in use" not in diagnostic.lower() and "10048" not in diagnostic:
                    pytest.fail(
                        f"Isolated backend did not become ready within 20s:\n{diagnostic[-4000:]}"
                    )
            else:
                pytest.fail("Could not start the isolated backend on an ephemeral port within 20s.")
        # The test process must also release its copy of the inherited log handle.
        yield active
    finally:
        if active is not None:
            active.stop()
            assert active.process.poll() is not None, "The test must not leave uvicorn running"


def test_backend_stop_releases_log_and_closes_port(backend):
    """Exercise the real venv launcher/child teardown, including Windows file locking."""
    log = backend.root / "uvicorn.log"
    moved = backend.root / "released.log"
    if os.name == "nt":
        # The fixture has closed its own stream; the running server still holds this file.
        with pytest.raises(PermissionError):
            log.rename(moved)
    backend.stop()
    backend.stop()  # Teardown also runs after an explicit stop, including API-down tests.
    assert backend.process.poll() is not None
    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", httpx.URL(backend.url).port)) != 0
    # No cleanup-error suppression or retry: stop must finish releasing the child handles.
    log.rename(moved)
    moved.unlink()
    assert not log.exists() and not moved.exists()


class FakeSlack(WebClient):
    """Record immutable delivery snapshots and prohibit any real Slack request."""

    def __init__(self):
        super().__init__(token="xoxb-e2e-never-sent", base_url="http://127.0.0.1:1/")
        self.calls = []
        self.messages = {}
        self.sequence = 0

    def api_call(self, *args, **kwargs):
        raise AssertionError("Unexpected Slack API method: real Slack access is forbidden")

    def record(self, method, payload):
        self.calls.append((method, copy.deepcopy(payload)))

    def recorded(self, method):
        return [payload for name, payload in self.calls if name == method]

    def auth_test(self, **kwargs):
        self.record("auth_test", kwargs)
        return {"ok": True, "team_id": TEAM, "user_id": "UE2EBOT", "bot_id": "BE2EBOT"}

    def conversations_open(self, **kwargs):
        assert kwargs["users"] == MEMBER
        self.record("conversations_open", kwargs)
        return {"ok": True, "channel": {"id": DM}}

    def chat_postMessage(self, **kwargs):
        assert kwargs["channel"] == DM, "Employee data must stay in the configured DM"
        self.sequence += 1
        ts = f"1800000001.{self.sequence:06d}"
        message = {**copy.deepcopy(kwargs), "ts": ts}
        self.messages[(DM, ts)] = message
        self.record("chat_postMessage", message)
        return {"ok": True, "channel": DM, "ts": ts, "message": copy.deepcopy(message)}

    def chat_update(self, **kwargs):
        key = (kwargs["channel"], kwargs["ts"])
        assert key in self.messages, "An update must target an existing bot message"
        self.messages[key].update(copy.deepcopy(kwargs))
        self.record("chat_update", kwargs)
        return {"ok": True, **copy.deepcopy(self.messages[key])}

    def chat_getPermalink(self, **kwargs):
        assert (kwargs["channel"], kwargs["message_ts"]) in self.messages
        self.record("chat_getPermalink", kwargs)
        return {
            "ok": True,
            "permalink": (
                f"https://e2e.invalid/archives/{kwargs['channel']}/"
                f"p{kwargs['message_ts'].replace('.', '')}"
            ),
        }

    def views_publish(self, **kwargs):
        assert kwargs["user_id"] == MEMBER
        self.record("views_publish", kwargs)
        return {"ok": True, "view": {"id": "VE2EHOME", **copy.deepcopy(kwargs["view"])}}

    def views_update(self, **kwargs):
        self.record("views_update", kwargs)
        return {"ok": True, "view": {"id": kwargs["view_id"], **copy.deepcopy(kwargs["view"])}}

    def views_open(self, **kwargs):
        self.record("views_open", kwargs)
        return {"ok": True, "view": {"id": "VE2EMODAL", **copy.deepcopy(kwargs["view"])}}


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from nodes(child)


def visible_text(value):
    return html.unescape(
        "\n".join(node["text"] for node in nodes(value) if isinstance(node.get("text"), str))
    )


def action_value(message, action):
    return next(node["value"] for node in nodes(message) if node.get("action_id") == action)


def selected_values(message, action):
    return [
        option["value"]
        for node in nodes(message)
        if node.get("action_id") == action
        for option in node["options"]
    ]


def assert_no_chat_controls(message):
    assert message.get("blocks"), "Check a rendered message, not an empty fixture"
    assert not any("action_id" in node for node in nodes(message["blocks"]))


def assert_employee_actions(value):
    actions = {node["action_id"] for node in nodes(value) if "action_id" in node}
    assert list(nodes(value)), "Inspect rendered content, not an empty traversal"
    assert not actions.intersection(
        {
            "approve_request",
            "decline_request",
            "acknowledge_request",
            "approve",
            "decline",
            "acknowledge",
            "add_manager_comment",
            "upload_document",
            "ai_settings",
        }
    )


@dataclass
class Session:
    backend: Backend
    settings: Settings
    slack: FakeSlack
    app: EmployeeApp
    api: PeopleFlowClient

    def restart(self):
        self.app.close()
        self.api = PeopleFlowClient(self.backend.url, PASSWORD, timeout=5)
        self.app = EmployeeApp(self.settings, self.api, Store(self.settings.state_path), self.slack)

    def ask(self, text=QUESTION, event_id="EvE2EQUESTION", root=ROOT_TS, *, new_message=False):
        if new_message:
            self.app.ask(text, DM, root, event_id, new_message=True)
        else:
            self.app.ask(text, DM, root, event_id)

    def last_message(self):
        return next(reversed(self.slack.messages.values()))


@pytest.fixture
def session_factory(backend, tmp_path):
    sessions = []

    def create(transport=None):
        settings = Settings(
            bot_token="xoxb-e2e-never-sent",
            app_token="xapp-e2e-never-sent",
            employee_user_id=MEMBER,
            team_id=TEAM,
            api_url=backend.url,
            password=PASSWORD,
            api_timeout=5,
            state_path=tmp_path / f"adapter-{len(sessions)}.db",
        )
        api = PeopleFlowClient(backend.url, PASSWORD, timeout=5, transport=transport)
        slack = FakeSlack()
        app = EmployeeApp(settings, api, Store(settings.state_path), slack)
        session = Session(backend, settings, slack, app, api)
        sessions.append(session)
        return session

    try:
        yield create
    finally:
        for session in reversed(sessions):
            session.app.close()


@pytest.fixture
def employee(session_factory):
    return session_factory()


def test_baseline_is_silent_and_home_reads_existing_backend_state(employee):
    assert employee.api.me()["user"]["id"] == "employee.demo"
    assert employee.api.conversations() == []
    assert employee.api.requests() == []
    draft = employee.api.create_request(PTO)
    employee.api.submit_request(draft["id"], PTO)
    conversation = employee.api.chat(QUESTION)

    employee.app.poll_once()
    employee.app.poll_once()
    employee.app.home("requests")

    assert employee.slack.recorded("chat_postMessage") == []
    assert employee.slack.recorded("chat_update") == []
    home = employee.slack.recorded("views_publish")[-1]["view"]
    assert "In review" in visible_text(home)
    assert selected_values(home, "select_request") == [draft["id"]]
    assert_employee_actions(home)
    employee.app.home("conversations")
    home = employee.slack.recorded("views_publish")[-1]["view"]
    assert action_value(home, "open_conversation") == conversation["conversation_id"]
    assert_employee_actions(home)
    assert (employee.backend.root / "workflow.db").is_file()
    assert (employee.backend.root / "conversations.db").is_file()
    assert (employee.backend.root / "index.json").is_file()


def test_english_answer_sources_and_follow_up_share_one_dm_thread(employee):
    employee.app.poll_once()
    employee.ask()
    conversations = employee.api.conversations()
    assert len(conversations) == 1
    conversation_id = conversations[0]["id"]
    first = employee.api.conversation(conversation_id)["messages"]
    assert [item["role"] for item in first] == ["user", "assistant"]
    assert first[0]["content"] == QUESTION
    assert first[1]["sources"], "The deterministic answer must use real worktree documents"
    assert any("payroll" in source["source"].lower() for source in first[1]["sources"])
    assert "payroll" in first[1]["content"].lower()
    assert not any("\u0400" <= char <= "\u04ff" for char in first[1]["content"])
    assert first[1]["content"] in visible_text(employee.last_message())
    assert "Sources:" in visible_text(employee.last_message())
    assert_no_chat_controls(employee.last_message())
    assert employee.slack.recorded("chat_update")

    follow_up = "What if payday falls on a weekend?"
    employee.ask(follow_up, "EvE2EFOLLOWUP")
    detail = employee.api.conversation(conversation_id)
    assert len(employee.api.conversations()) == 1
    assert [item["role"] for item in detail["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert detail["messages"][-2]["content"] == follow_up
    assert detail["messages"][-1]["content"] in visible_text(employee.last_message())
    posts = employee.slack.recorded("chat_postMessage")
    assert len(posts) == 2
    assert {(item["channel"], item["thread_ts"]) for item in posts} == {(DM, ROOT_TS)}
    assert_employee_actions(employee.slack.calls)


def test_top_level_answer_and_both_followup_roots_retain_backend_context_after_restart(employee):
    employee.app.poll_once()
    employee.ask(event_id="EvE2ETOPLEVEL", new_message=True)
    conversations = employee.api.conversations()
    assert len(conversations) == 1
    conversation_id = conversations[0]["id"]
    history = employee.api.conversation(conversation_id)["messages"]
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[0]["content"] == QUESTION
    assert history[1]["sources"]
    answer_root = employee.last_message()["ts"]
    posts = employee.slack.recorded("chat_postMessage")
    assert len(posts) == 1, "A new question produces one answer, with no bot question echo"
    assert "thread_ts" not in posts[0]
    assert "thread_ts" not in employee.last_message()
    assert history[-1]["content"] in visible_text(employee.last_message())
    assert "Sources:" in visible_text(employee.last_message())
    assert_no_chat_controls(employee.last_message())
    assert answer_root != ROOT_TS

    employee.restart()
    for root in (ROOT_TS, answer_root):
        assert employee.app.store.thread(DM, root)["conversation_id"] == conversation_id
    delivered = copy.deepcopy(employee.slack.calls)
    employee.ask(event_id="EvE2ETOPLEVEL", new_message=True)
    assert employee.slack.calls == delivered
    assert employee.api.conversation(conversation_id)["messages"] == history

    for index, (root, question) in enumerate(
        [
            (ROOT_TS, "What if payday falls on a weekend?"),
            (answer_root, "What happens when payday is a public holiday?"),
        ],
        start=1,
    ):
        employee.ask(question, f"EvE2ETOPFOLLOW{index}", root)
        updated = employee.api.conversation(conversation_id)["messages"]
        assert updated[:-2] == history, "Both Slack roots must append to the same saved history"
        assert [item["role"] for item in updated[-2:]] == ["user", "assistant"]
        assert updated[-2]["content"] == question
        assert updated[-1]["content"] in visible_text(employee.last_message())
        assert employee.last_message()["thread_ts"] == root
        assert len(employee.api.conversations()) == 1
        assert len(employee.slack.recorded("chat_postMessage")) == index + 1
        history = updated
    assert len(history) == 6
    assert_employee_actions(employee.slack.calls)


def test_ask_new_has_one_answer_root_and_can_resume_an_explicit_backend_conversation(employee):
    employee.app.ask_new(QUESTION, "question:VE2ENEW")
    conversation_id = employee.api.conversations()[0]["id"]
    history = employee.api.conversation(conversation_id)["messages"]
    first_root = employee.last_message()["ts"]
    assert len(employee.slack.recorded("chat_postMessage")) == 1
    assert len(employee.slack.messages) == 1, "ask_new must not create a separate question echo"
    assert "thread_ts" not in employee.last_message()
    assert history[0]["content"] == QUESTION
    assert history[-1]["content"] in visible_text(employee.last_message())
    assert employee.app.store.thread(DM, first_root)["conversation_id"] == conversation_id
    delivered = copy.deepcopy(employee.slack.calls)
    employee.app.ask_new(QUESTION, "question:VE2ENEW")
    assert employee.slack.calls == delivered
    assert employee.api.conversation(conversation_id)["messages"] == history

    followup = "What if payday falls on a weekend?"
    employee.app.ask_new(followup, "question:VE2ERESUME", conversation_id=conversation_id)
    assert len(employee.api.conversations()) == 1
    updated = employee.api.conversation(conversation_id)["messages"]
    assert len(updated) == 4 and updated[:2] == history
    assert updated[-2]["content"] == followup
    assert updated[-1]["content"] in visible_text(employee.last_message())
    assert len(employee.slack.messages) == 2
    assert len(employee.slack.recorded("chat_postMessage")) == 2
    assert all("thread_ts" not in post for post in employee.slack.recorded("chat_postMessage"))
    second_root = employee.last_message()["ts"]
    assert second_root != first_root
    assert employee.app.store.thread(DM, second_root)["conversation_id"] == conversation_id


def test_pto_receipt_refreshes_but_manager_notifications_remain_historical(employee):
    employee.app.poll_once()
    employee.app.submit_request("VE2EPTO", PTO, None, "submit:VE2EPTO")
    requests = employee.api.requests()
    assert len(requests) == 1
    request_id = requests[0]["id"]
    assert requests[0]["status"] == "in_review"
    assert "submitted" in visible_text(employee.slack.recorded("views_update")[-1]).lower()
    submitted_card = employee.slack.recorded("chat_postMessage")[-1]
    card_key = (submitted_card["channel"], submitted_card["ts"])
    assert "In review" in visible_text(submitted_card)

    # Repeated delivery of the same submission must not create another draft.
    employee.app.submit_request("VE2EPTO", PTO, None, "submit:VE2EPTO")
    assert len(employee.api.requests()) == 1
    assert len(employee.slack.recorded("chat_postMessage")) == 1

    employee.backend.role_call("manager", "POST", f"requests/{request_id}/approve", {})
    employee.app.poll_once()
    approved = employee.api.request(request_id)
    assert approved["request"]["status"] == "approved"
    assert "Approved" in visible_text(employee.slack.messages[card_key])
    assert "approved" in employee.slack.recorded("chat_postMessage")[-1]["text"]
    assert any(
        (item["channel"], item["ts"]) == card_key for item in employee.slack.recorded("chat_update")
    )
    approval_notice = copy.deepcopy(employee.last_message())
    approval_key = (approval_notice["channel"], approval_notice["ts"])
    assert approval_key != card_key
    assert PTO["comment"] not in visible_text(approval_notice), (
        "A status notice is not a full receipt"
    )
    assert_no_chat_controls(approval_notice)

    note = "Your handoff is confirmed. Enjoy your time off."
    employee.backend.role_call("manager", "POST", f"requests/{request_id}/comments", {"body": note})
    count = len(employee.slack.recorded("chat_postMessage"))
    employee.app.poll_once()
    assert len(employee.slack.recorded("chat_postMessage")) == count + 1
    note_notice = copy.deepcopy(employee.last_message())
    note_key = (note_notice["channel"], note_notice["ts"])
    assert note in visible_text(note_notice)
    assert PTO["comment"] not in visible_text(note_notice)
    assert_no_chat_controls(note_notice)
    assert employee.slack.messages[approval_key] == approval_notice
    assert employee.api.request(request_id)["request"]["status"] == "approved"

    # A restart and another manager change must not turn historical notices into live cards.
    employee.restart()
    second_note = "The coverage calendar is now updated."
    employee.backend.role_call(
        "manager", "POST", f"requests/{request_id}/comments", {"body": second_note}
    )
    employee.app.poll_once()
    assert len(employee.slack.recorded("chat_postMessage")) == count + 2
    assert second_note in visible_text(employee.last_message())
    assert note not in visible_text(employee.last_message()), (
        "A new note notice must not repeat old notes"
    )
    assert employee.slack.messages[approval_key] == approval_notice
    assert employee.slack.messages[note_key] == note_notice
    assert "Approved" in visible_text(employee.slack.messages[card_key])
    updates = employee.slack.recorded("chat_update")
    assert {(item["channel"], item["ts"]) for item in updates} == {card_key}
    assert {(item["channel"], item["ts"]) for item in employee.app.store.cards(request_id)} == {
        card_key
    }
    detail = employee.api.request(request_id)
    assert detail["request"]["status"] == "approved"
    assert [comment["body"] for comment in detail["comments"]] == [note, second_note]
    employee.app.show_detail("VE2EDETAIL", "open_request", request_id)
    assert note in visible_text(employee.slack.recorded("views_update")[-1])
    assert second_note in visible_text(employee.slack.recorded("views_update")[-1])
    assert_employee_actions(employee.slack.calls)
    unchanged = copy.deepcopy(employee.slack.calls)
    employee.app.poll_once()
    assert employee.slack.calls == unchanged


@pytest.mark.parametrize("unknown", [False, True], ids=["partial-day", "return-unknown"])
def test_sick_leave_report_is_acknowledged_without_approval_ui(employee, unknown):
    details = {
        "expected_return_date": None if unknown else "2030-04-01",
        "expected_return_unknown": unknown,
        "time_away": "full_day" if unknown else "partial_day",
        "partial_hours": None if unknown else 3.5,
        "extended_or_recurring": unknown,
    }
    payload = {
        "type": "sick_leave",
        "start_date": "2030-04-01",
        "end_date": None,
        "comment": "Coverage note only; no medical information.",
        "details": details,
    }
    employee.app.poll_once()
    employee.app.submit_request("VE2ESICK", payload, None, "submit:VE2ESICK")
    request = employee.api.requests()[0]
    assert request["status"] == "reported"
    assert request["details"] == details
    card = employee.slack.recorded("chat_postMessage")[-1]
    card_key = (card["channel"], card["ts"])
    assert "Reported" in visible_text(card)
    assert ("Return date unknown" if unknown else "3.5 hours") in visible_text(card)
    assert "Absence reported" in visible_text(employee.slack.recorded("views_update")[-1])

    employee.backend.role_call("manager", "POST", f"requests/{request['id']}/acknowledge", {})
    employee.app.poll_once()
    assert employee.api.request(request["id"])["request"]["status"] == "acknowledged"
    assert "Acknowledged" in visible_text(employee.slack.messages[card_key])
    assert "acknowledged" in employee.slack.recorded("chat_postMessage")[-1]["text"]
    assert_employee_actions(employee.slack.calls)


def test_local_cancellation_refreshes_receipt_and_modal_without_an_extra_dm(employee):
    employee.app.poll_once()
    draft = employee.api.create_request(PTO)
    employee.api.submit_request(draft["id"], PTO)
    employee.app.poll_once()
    card = employee.slack.recorded("chat_postMessage")[-1]
    posts_before = copy.deepcopy(employee.slack.recorded("chat_postMessage"))
    employee.app.cancel(draft["id"], "cancel:VE2ECANCEL", view_id="VE2ECANCEL")
    cancelled = employee.api.request(draft["id"])
    assert cancelled["request"]["status"] == "cancelled"
    updated = employee.slack.messages[(card["channel"], card["ts"])]
    assert "Cancelled" in visible_text(updated)
    assert "cancel_request" not in json.dumps(updated)
    modal = employee.slack.recorded("views_update")[-1]
    assert modal["view_id"] == "VE2ECANCEL"
    assert "Cancelled" in visible_text(modal)
    assert "cancel_request" not in json.dumps(modal)
    assert employee.slack.recorded("chat_postMessage") == posts_before
    before = copy.deepcopy(employee.slack.calls)
    employee.app.cancel(draft["id"], "cancel:VE2ECANCEL", view_id="VE2ECANCEL")
    employee.app.poll_once()
    assert employee.slack.calls == before
    assert employee.api.request(draft["id"]) == cancelled


def test_external_cancellation_still_sends_one_short_notification(employee):
    employee.app.poll_once()
    draft = employee.api.create_request(PTO)
    employee.api.submit_request(draft["id"], PTO)
    employee.app.poll_once()
    receipt = employee.last_message()
    receipt_key = (receipt["channel"], receipt["ts"])
    posts_before = len(employee.slack.recorded("chat_postMessage"))

    employee.api.cancel_request(draft["id"])
    employee.app.poll_once()
    assert employee.api.request(draft["id"])["request"]["status"] == "cancelled"
    assert len(employee.slack.recorded("chat_postMessage")) == posts_before + 1
    assert "Cancelled" in visible_text(employee.slack.messages[receipt_key])
    notice = employee.last_message()
    assert notice["ts"] != receipt["ts"]
    assert "cancelled" in visible_text(notice).lower()
    assert PTO["comment"] not in visible_text(notice)
    assert_no_chat_controls(notice)
    assert {(item["channel"], item["ts"]) for item in employee.app.store.cards(draft["id"])} == {
        receipt_key
    }
    employee.restart()
    delivered = copy.deepcopy(employee.slack.calls)
    employee.app.poll_once()
    assert employee.slack.calls == delivered


def test_delete_conversation_keeps_linked_request_and_prevents_thread_resurrection(employee):
    employee.app.poll_once()
    employee.ask("I need vacation from 2030-04-01 to 2030-04-03", "EvE2EVACATION")
    conversation_id = employee.api.conversations()[0]["id"]
    detail = employee.api.conversation(conversation_id)
    request_id = detail["messages"][-1]["workflow"]["id"]
    employee.api.submit_request(request_id, {"comment": "Family vacation; coverage arranged."})
    employee.app.poll_once()
    before = employee.api.request(request_id)
    slack_message_keys = set(employee.slack.messages)

    employee.app.delete(conversation_id, "delete:VE2EDELETE")
    assert employee.api.conversations() == []
    with pytest.raises(APIError) as missing:
        employee.api.conversation(conversation_id)
    assert missing.value.status == 404
    assert employee.api.request(request_id) == before
    assert [item["id"] for item in employee.api.requests()] == [request_id]
    assert slack_message_keys.issubset(employee.slack.messages)
    assert "requests remain" in visible_text(employee.last_message())

    employee.ask("Is my vacation still being reviewed?", "EvE2EDELETEDFOLLOWUP")
    assert employee.api.conversations() == []
    assert employee.api.request(request_id) == before
    assert "deleted" in visible_text(employee.last_message()).lower()


def test_duplicate_event_after_restart_does_not_repeat_backend_exchange(employee):
    employee.app.poll_once()
    employee.ask(event_id="EvE2EREDELIVERY")
    conversation_id = employee.api.conversations()[0]["id"]
    saved = employee.api.conversation(conversation_id)
    delivered = copy.deepcopy(employee.slack.calls)
    employee.ask(event_id="EvE2EREDELIVERY")
    assert employee.slack.calls == delivered
    assert employee.api.conversation(conversation_id) == saved

    employee.restart()
    employee.app.poll_once()
    employee.ask(event_id="EvE2EREDELIVERY")
    assert employee.slack.calls == delivered
    assert employee.api.conversation(conversation_id) == saved
    assert len(saved["messages"]) == 2
    assert len(employee.api.conversations()) == 1

    employee.ask("What happens when payday is a holiday?", "EvE2EAFTERRESTART")
    assert len(employee.api.conversations()) == 1
    assert len(employee.api.conversation(conversation_id)["messages"]) == 4
    assert employee.last_message()["thread_ts"] == ROOT_TS


@pytest.mark.parametrize("rating", [1, 5], ids=["unhelpful", "helpful"])
def test_legacy_answer_feedback_reaches_admin_once_without_employee_identity(employee, rating):
    employee.ask(new_message=True)
    # Old posted Slack buttons remain actionable; new answers expose no feedback controls.
    answer_id = employee.app.store.get("latest_answer:" + DM)
    assert answer_id
    assert_no_chat_controls(employee.last_message())
    answer_key = (employee.last_message()["channel"], employee.last_message()["ts"])
    conversation_id = employee.api.conversations()[0]["id"]
    answer = employee.api.conversation(conversation_id)["messages"][-1]["content"]
    note = "Please include the cutoff time." if rating == 1 else "The source answered my question."
    posts_before = copy.deepcopy(employee.slack.recorded("chat_postMessage"))
    updates_before = len(employee.slack.recorded("chat_update"))
    employee.app.rate(answer_id, rating, note)
    rated_calls = copy.deepcopy(employee.slack.calls)
    employee.app.rate(answer_id, rating, note)
    assert employee.slack.calls == rated_calls
    feedback = employee.backend.role_call("knowledge_admin", "GET", "admin/feedback")["feedback"]
    assert len(feedback) == 1
    assert feedback[0]["question"] == QUESTION
    assert feedback[0]["answer"] == answer
    assert feedback[0]["rating"] == rating
    assert feedback[0]["comment"] == note
    assert feedback[0]["sentiment"] == ("negative" if rating == 1 else "positive")
    assert not {"user_id", "employee_id", "applicant", "username"}.intersection(feedback[0])
    assert "employee.demo" not in json.dumps(feedback)
    assert employee.slack.recorded("chat_postMessage") == posts_before
    assert len(employee.slack.messages) == 1, "Successful feedback updates the answer in place"
    updates = employee.slack.recorded("chat_update")[updates_before:]
    assert len(updates) == 1
    assert (updates[0]["channel"], updates[0]["ts"]) == answer_key
    assert "thread_ts" not in employee.last_message()
    rated_message = employee.slack.messages[answer_key]
    assert "Feedback saved" in visible_text(rated_message)
    assert answer in visible_text(rated_message)
    assert "Sources:" in visible_text(rated_message)
    assert_no_chat_controls(rated_message)
    assert not any(
        node.get("action_id") in {"feedback_helpful", "feedback_unhelpful"}
        for node in nodes(rated_message)
    )


def test_api_down_replaces_placeholder_and_home_with_safe_failure_output(employee):
    employee.app.poll_once()
    employee.ask()
    saved = employee.api.conversations()
    assert len(saved) == 1
    employee.backend.stop()
    count = len(employee.slack.recorded("chat_postMessage"))
    employee.ask("Can I change my direct deposit?", "EvE2EAPIDOWN")
    employee.app.home()
    assert len(employee.slack.recorded("chat_postMessage")) == count + 1
    assert "temporarily unavailable" in visible_text(employee.last_message()).lower()
    assert "Looking through" not in visible_text(employee.last_message())
    assert (
        "temporarily unavailable"
        in visible_text(employee.slack.recorded("views_publish")[-1]).lower()
    )
    output = json.dumps(employee.slack.calls)
    assert PASSWORD not in output
    assert employee.backend.url not in output
    assert "Traceback" not in output


def test_backend_api_smoke_auth_history_stream_workflows_documents_and_metrics(employee):
    """API portion of smoke_check.ps1, using the isolated server and copied corpus."""
    health = employee.api.health()
    assert health["status"] == "ok"
    assert health["api_version"] == "v1"
    # No employee client method exists for deliberately unauthenticated /me.
    with httpx.Client(base_url=employee.backend.url, timeout=5, trust_env=False) as http:
        assert http.get("/api/v1/me").status_code == 401

    response = employee.api.chat("What can you help with?")
    assert response["intent"] == "view_capabilities"
    conversation_id = response["conversation_id"]
    assert len(employee.api.conversation(conversation_id)["messages"]) == 2
    events = list(employee.api.stream_chat("What can you help with?", conversation_id))
    assert events[0]["type"] == "start"
    assert any(event["type"] == "token" for event in events)
    assert events[-1]["type"] == "complete"
    assert events[-1]["outcome_code"]
    assert events[-1]["conversation_id"] == conversation_id
    assert len(employee.api.conversation(conversation_id)["messages"]) == 4

    pto = employee.api.create_request(PTO)
    assert employee.api.submit_request(pto["id"], PTO)["request"]["status"] == "in_review"
    employee.backend.role_call("manager", "POST", f"requests/{pto['id']}/approve", {})
    sick_payload = {
        "type": "sick_leave",
        "start_date": "2030-04-05",
        "comment": "Coverage note",
        "details": {
            "expected_return_date": "2030-04-06",
            "expected_return_unknown": False,
            "time_away": "full_day",
            "partial_hours": None,
            "extended_or_recurring": False,
        },
    }
    sick = employee.api.create_request(sick_payload)
    assert employee.api.submit_request(sick["id"], sick_payload)["request"]["status"] == "reported"
    employee.backend.role_call("manager", "POST", f"requests/{sick['id']}/acknowledge", {})

    documents = employee.backend.role_call("knowledge_admin", "GET", "documents")["documents"]
    assert documents and all(document["id"] for document in documents)
    index = employee.backend.role_call("knowledge_admin", "POST", "documents/index")
    assert index["scope"] == "all_documents"
    assert index["index"]["mode"] == "lexical"
    assert (employee.backend.root / "index.json").is_file()
    assert (employee.backend.root / "index_status.json").is_file()
    metrics = employee.backend.role_call("knowledge_admin", "GET", "admin/metrics")["metrics"]
    assert metrics["total_requests"] == 2
    assert metrics["requests_by_status"]["approved"] == 1
    assert metrics["requests_by_status"]["acknowledged"] == 1
    assert metrics["questions"] == 2
    assert {item["id"]: item["status"] for item in employee.api.requests()} == {
        pto["id"]: "approved",
        sick["id"]: "acknowledged",
    }


class ReplacementStream(httpx.SyncByteStream):
    def __init__(self, answer, complete):
        self.answer, self.complete = answer, complete

    def __iter__(self):
        yield b'{"type":"start"}\n'
        # Allow the application's preview coalescing window to elapse once.
        time.sleep(2.05)
        yield b'{"type":"token","content":"DISCARDED PARTIAL PAYROLL ANSWER"}\n'
        yield (json.dumps({"type": "replace", "content": self.answer}) + "\n").encode()
        yield (json.dumps(self.complete) + "\n").encode()


class ReplaceResponseTransport(httpx.BaseTransport):
    """Forward every HTTP operation; alter one response's delivery, not backend state."""

    def __init__(self):
        self.inner = httpx.HTTPTransport(retries=0)
        self.injected = 0

    def handle_request(self, request):
        response = self.inner.handle_request(request)
        if request.url.path.endswith("/chat/stream") and response.status_code == 200:
            try:
                events = [json.loads(line) for line in response.read().splitlines() if line]
            finally:
                response.close()
            assert events[-1]["type"] == "complete", "Fault injection requires a real saved answer"
            answer = ""
            for event in events:
                if event["type"] == "token":
                    answer += event["content"]
                elif event["type"] == "replace":
                    answer = event["content"]
            self.injected += 1
            return httpx.Response(
                200,
                headers={"Content-Type": "application/x-ndjson"},
                stream=ReplacementStream(answer, events[-1]),
            )
        return response

    def close(self):
        self.inner.close()


def test_replace_event_removes_visible_partial_answer_and_matches_saved_history(session_factory):
    transport = ReplaceResponseTransport()
    employee = session_factory(transport)
    employee.ask()
    assert transport.injected == 1
    conversation_id = employee.api.conversations()[0]["id"]
    messages = employee.api.conversation(conversation_id)["messages"]
    assert len(messages) == 2
    answer = messages[-1]["content"]
    updates = employee.slack.recorded("chat_update")
    assert any("DISCARDED PARTIAL" in visible_text(update) for update in updates[:-1])
    assert answer in visible_text(employee.last_message())
    assert "DISCARDED PARTIAL" not in visible_text(employee.last_message())
    assert len(employee.slack.recorded("chat_postMessage")) == 1
    assert {(item["channel"], item["ts"]) for item in updates} == {
        (DM, employee.last_message()["ts"])
    }
    assert "Sources:" in visible_text(employee.last_message())
    assert_no_chat_controls(employee.last_message())
