"""Windows launcher ownership and concurrent-start regressions."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell.exe")
PS_ARGS = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="Windows launcher test")
HELPER = Path(__file__).resolve().parents[1] / "scripts/demo_processes.ps1"
PRELUDE = "$ErrorActionPreference = 'Stop'; . $env:DEMO_TEST_HELPER; "


def run_script(script, environment):
    return subprocess.run(
        [*PS_ARGS, PRELUDE + script],
        env=environment,
        capture_output=True,
        timeout=20,
    )


def test_lock_blocks_concurrent_start_and_is_released(tmp_path):
    ready = tmp_path / "ready"
    environment = {
        **os.environ,
        "DEMO_TEST_HELPER": str(HELPER),
        "DEMO_TEST_ROOT": str(tmp_path),
        "DEMO_TEST_READY": str(ready),
    }
    holder_script = (
        "$lock = Enter-DemoOperationLock -ProjectRoot $env:DEMO_TEST_ROOT; "
        "try { [IO.File]::WriteAllText($env:DEMO_TEST_READY, 'ready'); "
        "[Console]::ReadLine() | Out-Null } finally { Exit-DemoOperationLock -Lock $lock }"
    )
    acquire_script = (
        "$lock = Enter-DemoOperationLock -ProjectRoot $env:DEMO_TEST_ROOT; "
        "Exit-DemoOperationLock -Lock $lock"
    )
    holder = subprocess.Popen(
        [*PS_ARGS, PRELUDE + holder_script],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and holder.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "Mutex holder did not become ready"
        competing = run_script(
            acquire_script, {**environment, "DEMO_TEST_ROOT": str(tmp_path).upper()}
        )
        assert competing.returncode != 0
        assert b"Another start/stop is in progress" in competing.stderr
        independent = run_script(
            acquire_script, {**environment, "DEMO_TEST_ROOT": str(tmp_path / "another-project")}
        )
        assert independent.returncode == 0, independent.stderr
    finally:
        try:
            holder.communicate(b"\n", timeout=10)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.communicate()
    assert holder.returncode == 0
    assert run_script(acquire_script, environment).returncode == 0


def test_old_launcher_cannot_remove_new_process_record(tmp_path):
    pid_file = tmp_path / "processes.json"
    expected_file = tmp_path / "expected.json"
    old = [{"id": 123, "started_at": "2026-01-01T00:00:00Z"}]
    # Same PID may be reused by Windows; the creation time must also match.
    new = [{"id": 123, "started_at": "2026-01-02T00:00:00Z"}]
    pid_file.write_text(json.dumps({"processes": new}), encoding="utf-8")
    expected_file.write_text(json.dumps(old), encoding="utf-8")
    environment = {
        **os.environ,
        "DEMO_TEST_HELPER": str(HELPER),
        "DEMO_TEST_PID_FILE": str(pid_file),
        "DEMO_TEST_EXPECTED": str(expected_file),
    }
    script = (
        "$records = @(Get-Content -LiteralPath $env:DEMO_TEST_EXPECTED -Raw | ConvertFrom-Json); "
        "Remove-DemoProcessRecord -PidFile $env:DEMO_TEST_PID_FILE -ExpectedRecords $records"
    )
    result = run_script(script, environment)
    assert result.returncode == 0, result.stderr
    assert json.loads(pid_file.read_text()) == {"processes": new}
    expected_file.write_text(json.dumps(new), encoding="utf-8")
    result = run_script(script, environment)
    assert result.returncode == 0, result.stderr
    assert not pid_file.exists()


def test_frontend_preflight_preserves_loaded_native_module(tmp_path):
    node = shutil.which("node.exe")
    native = HELPER.parents[1] / (
        "frontend/node_modules/lightningcss-win32-x64-msvc/lightningcss.win32-x64-msvc.node"
    )
    if not node or not native.exists():
        pytest.skip("Install Windows frontend dependencies for the native-module lock test")
    frontend = tmp_path / "Project with spaces Кириллица" / "frontend"
    module = frontend / "node_modules" / "native" / native.name
    module.parent.mkdir(parents=True)
    shutil.copyfile(native, module)
    sentinel = frontend / "node_modules" / "keep.txt"
    sentinel.write_text("Existing installation must remain intact", encoding="utf-8")
    original = module.read_bytes()
    ready = tmp_path / "native-ready"
    environment = {
        **os.environ,
        "DEMO_TEST_HELPER": str(HELPER),
        "DEMO_TEST_FRONTEND": str(frontend),
        "DEMO_TEST_NATIVE": str(module),
        "DEMO_TEST_READY": str(ready),
    }
    holder = subprocess.Popen(
        [
            node,
            "-e",
            "require(process.env.DEMO_TEST_NATIVE); "
            "require('node:fs').writeFileSync(process.env.DEMO_TEST_READY, 'ready'); "
            "process.stdin.resume();",
        ],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    check = "Assert-DemoFrontendDependenciesUnlocked -FrontendDirectory $env:DEMO_TEST_FRONTEND"
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and holder.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "Native module holder did not become ready"
        blocked = run_script(check, environment)
        assert blocked.returncode != 0
        assert b"Frontend dependency" in blocked.stderr
        assert b"retry start.bat" in blocked.stderr
        assert module.read_bytes() == original
        assert sentinel.read_text(encoding="utf-8") == "Existing installation must remain intact"
        assert holder.poll() is None, "Preflight must not terminate another server"
        independent = run_script(
            check, {**environment, "DEMO_TEST_FRONTEND": str(tmp_path / "another-project")}
        )
        assert independent.returncode == 0, independent.stderr
    finally:
        holder.communicate(timeout=10)
    assert holder.returncode == 0
    unlocked = run_script(check, environment)
    assert unlocked.returncode == 0, unlocked.stderr
    assert module.read_bytes() == original
