"""Windows PowerShell 5.1 launcher regressions, isolated from the running demo."""

import base64
import json
import os
import shutil
import socket
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = (
    Path(os.environ.get("SystemRoot", "C:/Windows"))
    / "System32/WindowsPowerShell/v1.0/powershell.exe"
)
RESULT_PREFIX = "LAUNCHER_TEST_JSON:"


def ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == "nt" and POWERSHELL.is_file(), "Requires Windows PowerShell 5.1")
class WindowsLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="peopleflow launcher tests ")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "workspace тест"
        scripts = self.workspace / "scripts"
        scripts.mkdir(parents=True)
        # Copy the actual scripts so even a broken dot-source guard cannot touch the real project.
        for name in ("launcher.ps1", "demo_processes.ps1", "slack_service.ps1"):
            shutil.copyfile(PROJECT_ROOT / "scripts" / name, scripts / name)
        shutil.copyfile(PROJECT_ROOT / "run_demo.ps1", self.workspace / "run_demo.ps1")
        (self.workspace / "frontend").mkdir()
        (self.workspace / "slack").mkdir()
        shutil.copyfile(PROJECT_ROOT / "run_demo.ps1", self.workspace / "run_demo.ps1")
        shutil.copyfile(PROJECT_ROOT / "stop_demo.ps1", self.workspace / "stop_demo.ps1")
        for relative, content in {
            ".env.example": "OPENAI_API_KEY=your_openai_api_key\nDEMO_MODE=1\n",
            "requirements.txt": "fastapi==0.1\n",
            "slack/pyproject.toml": '[project]\nname="launcher-slack-fixture"\n',
            "frontend/package.json": '{"name":"launcher-test"}\n',
            "frontend/package-lock.json": '{"lockfileVersion":3}\n',
        }.items():
            (self.workspace / relative).write_text(content, encoding="utf-8")

    def run_powershell(self, body: str):
        script = f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
. {ps_quote(self.workspace / "scripts/launcher.ps1")} -Action Status -NoBrowser
$script:fixturePython = {ps_quote(PROJECT_ROOT / ".venv/Scripts/python.exe")}
$result = & {{
{body}
}}
[Console]::WriteLine('{RESULT_PREFIX}' + (ConvertTo-Json -InputObject $result -Depth 8 -Compress))
"""
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        # A parent pwsh 7 session can export its incompatible module path to powershell.exe.
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() not in {"PSMODULEPATH", "OPENAI_MODEL", "POLL_INTERVAL_SECONDS"}
            and not key.upper().startswith("SLACK_")
        }
        completed = subprocess.run(
            [
                str(POWERSHELL),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            cwd=self.workspace,
            env=environment,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=35,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        results = [line for line in completed.stdout.splitlines() if line.startswith(RESULT_PREFIX)]
        self.assertEqual(len(results), 1, completed.stdout + completed.stderr)
        return json.loads(results[0][len(RESULT_PREFIX) :])

    def test_parser_and_dot_source_are_compatible_with_powershell_51(self) -> None:
        result = self.run_powershell("""
$tokens = $null
$parseErrors = $null
$null = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $script:projectDirectory 'scripts/launcher.ps1'), [ref]$tokens, [ref]$parseErrors)
@{ version = $PSVersionTable.PSVersion.ToString(); errors = @($parseErrors).Count;
   initialized = (Test-Path -LiteralPath $script:stateDirectory) }
""")
        self.assertTrue(result["version"].startswith("5.1."), result)
        self.assertEqual(result["errors"], 0)
        self.assertFalse(result["initialized"])

    def test_configuration_creates_blank_key_without_overwriting_existing_env(self) -> None:
        first = self.run_powershell("""
Initialize-LocalConfiguration
@{ text = [IO.File]::ReadAllText((Join-Path $script:projectDirectory '.env'));
   state = (Test-Path -LiteralPath $script:stateDirectory);
   logs = (Test-Path -LiteralPath $script:logDirectory) }
""")
        self.assertEqual(first["text"].splitlines(), ["OPENAI_API_KEY=", "DEMO_MODE=1"])
        self.assertTrue(first["state"])
        self.assertTrue(first["logs"])
        custom = b"OPENAI_API_KEY=fixture-only-value\r\nCUSTOM_SETTING=keep-me\r\n"
        env_path = self.workspace / ".env"
        env_path.write_bytes(custom)
        self.run_powershell("Initialize-LocalConfiguration; $true")
        self.assertEqual(env_path.read_bytes(), custom)

    def test_fingerprint_changes_for_each_dependency_manifest(self) -> None:
        original = self.run_powershell("Get-SetupFingerprint")
        self.assertEqual(len(original.split(":")), 4)
        previous = original
        for relative in (
            "requirements.txt",
            "slack/pyproject.toml",
            "frontend/package.json",
            "frontend/package-lock.json",
        ):
            with self.subTest(manifest=relative):
                path = self.workspace / relative
                path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
                current = self.run_powershell("Get-SetupFingerprint")
                self.assertNotEqual(current, previous)
                previous = current

    def test_dependency_cache_requires_matching_stamp_binaries_and_import_probe(self) -> None:
        result = self.run_powershell("""
Initialize-LocalConfiguration
$pythonPath = Join-Path $script:projectDirectory '.venv/Scripts/python.exe'
$vitePath = Join-Path $script:projectDirectory 'frontend/node_modules/vite/bin/vite.js'
New-Item -ItemType Directory -Path (Split-Path $pythonPath) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path $vitePath) -Force | Out-Null
[IO.File]::WriteAllText($vitePath, '// fixture')
# A tiny local executable simulates import success/failure; no Python installation is touched.
Add-Type -OutputAssembly $pythonPath -OutputType ConsoleApplication -TypeDefinition @'
using System;
public class LauncherProbe {
    public static int Main(string[] args) {
        System.IO.File.WriteAllText(Environment.GetEnvironmentVariable("LAUNCHER_PROBE_LOG"),
            string.Join("|", args));
        return int.Parse(Environment.GetEnvironmentVariable("LAUNCHER_PROBE_EXIT"));
    }
}
'@
$env:LAUNCHER_PROBE_LOG = Join-Path $script:projectDirectory 'probe.txt'
$env:LAUNCHER_PROBE_EXIT = '0'
$fingerprint = Get-SetupFingerprint
$stamp = @{ fingerprint = $fingerprint; project_root = $script:projectDirectory }
$stamp | ConvertTo-Json | Set-Content -LiteralPath $script:setupFile -Encoding UTF8
$valid = Test-DependenciesReady -Fingerprint $fingerprint
$probeArguments = [IO.File]::ReadAllText($env:LAUNCHER_PROBE_LOG)
$env:LAUNCHER_PROBE_EXIT = '7'
$failedProbe = Test-DependenciesReady -Fingerprint $fingerprint
$env:LAUNCHER_PROBE_EXIT = '0'
$changedManifest = Test-DependenciesReady -Fingerprint ($fingerprint + '-changed')
$stamp.project_root = Join-Path $script:projectDirectory 'different-project'
$stamp | ConvertTo-Json | Set-Content -LiteralPath $script:setupFile -Encoding UTF8
$wrongRoot = Test-DependenciesReady -Fingerprint $fingerprint
[IO.File]::WriteAllText($script:setupFile, 'not-json')
$corruptStamp = Test-DependenciesReady -Fingerprint $fingerprint
$stamp.project_root = $script:projectDirectory
$stamp | ConvertTo-Json | Set-Content -LiteralPath $script:setupFile -Encoding UTF8
Remove-Item -LiteralPath $vitePath
$missingBinary = Test-DependenciesReady -Fingerprint $fingerprint
@{ valid = $valid; failedProbe = $failedProbe; changedManifest = $changedManifest;
   wrongRoot = $wrongRoot; corruptStamp = $corruptStamp; missingBinary = $missingBinary;
   probeArguments = $probeArguments }
""")
        self.assertTrue(result["valid"])
        self.assertTrue(result["probeArguments"].startswith("-I|-c|import fastapi, uvicorn"))
        for key in ("failedProbe", "changedManifest", "wrongRoot", "corruptStamp", "missingBinary"):
            self.assertFalse(result[key], key)

    def test_available_port_skips_an_occupied_port_without_stopping_its_owner(self) -> None:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            occupied = listener.getsockname()[1]
            selected = self.run_powershell(f"Get-AvailableDemoPort -Preferred {occupied}")
            self.assertGreater(selected, occupied)
            self.assertLess(selected, min(occupied + 50, 65536))
            with socket.create_connection(("127.0.0.1", occupied), timeout=2):
                connection, _ = listener.accept()
                connection.close()

    def test_running_demo_is_reused_without_setup_ports_or_child_processes(self) -> None:
        result = self.run_powershell("""
function Get-RunningDemo { return @{ frontend_url = 'http://127.0.0.1:5173'; marker = 'existing' } }
function Invoke-DemoScript { throw 'Must not start or stop any process' }
function Initialize-LocalConfiguration { throw 'Must not change configuration' }
function Test-DependenciesReady { throw 'Must not inspect or install dependencies' }
function Get-AvailableDemoPort { throw 'Must not allocate ports' }
$state = Start-PeopleFlow
@{ marker = $state.marker; count = @($state).Count;
   setupExists = (Test-Path -LiteralPath $script:setupFile) }
""")
        self.assertEqual(result["marker"], "existing")
        self.assertEqual(result["count"], 1)
        self.assertFalse(result["setupExists"])

    def test_cached_start_skips_install_and_first_setup_stamps_only_after_readiness(self) -> None:
        for ready in (True, False):
            with self.subTest(cached=ready):
                # Each invocation is an isolated PowerShell scope; child scripts are recorded only.
                body = """
$script:checks = 0
function Get-RunningDemo {
    $script:checks += 1
    if ($script:checks -gt 1) { return @{ frontend_url = 'http://127.0.0.1:5173' } }
    return $null
}
function Test-DependenciesReady { param($Fingerprint) return CACHED_VALUE }
function Get-AvailableDemoPort { param($Preferred) return $Preferred }
function Invoke-DemoScript {
    param($Name, $ScriptArguments)
    $script:invokedName = $Name
    $script:invokedArguments = $ScriptArguments
    $script:stampBeforeReady = Test-Path -LiteralPath $script:setupFile
}
$state = Start-PeopleFlow
@{ name = $script:invokedName; arguments = $script:invokedArguments;
   stampBeforeReady = $script:stampBeforeReady; stampAfterReady = (Test-Path $script:setupFile);
   returned = $state.frontend_url }
""".replace("CACHED_VALUE", "$true" if ready else "$false")
                result = self.run_powershell(body)
                self.assertEqual(result["name"], "run_demo.ps1")
                self.assertIn("-SkipIndexRebuild", result["arguments"])
                self.assertEqual("-InstallDeps" in result["arguments"], not ready)
                self.assertEqual("-RuntimeDepsOnly" in result["arguments"], not ready)
                self.assertFalse(result["stampBeforeReady"])
                self.assertEqual(result["stampAfterReady"], not ready)
                self.assertEqual(result["returned"], "http://127.0.0.1:5173")

    def test_failed_setup_or_readiness_does_not_write_a_success_stamp(self) -> None:
        for fail_child in (True, False):
            with self.subTest(child_fails=fail_child):
                body = """
function Get-RunningDemo { return $null }
function Test-DependenciesReady { param($Fingerprint) return $false }
function Get-AvailableDemoPort { param($Preferred) return $Preferred }
$script:childInvoked = $false
function Invoke-DemoScript { $script:childInvoked = $true; CHILD_BEHAVIOR }
$failed = $false
try { $null = Start-PeopleFlow } catch { $failed = $true }
@{ failed = $failed; stamp = (Test-Path -LiteralPath $script:setupFile);
   childInvoked = $script:childInvoked }
""".replace("CHILD_BEHAVIOR", "throw 'Setup failed'" if fail_child else "return")
                result = self.run_powershell(body)
                self.assertTrue(result["failed"])
                self.assertTrue(result["childInvoked"])
                self.assertFalse(result["stamp"])

    def test_real_child_helper_accepts_exit_zero_and_rejects_nonzero_without_output_pollution(
        self,
    ) -> None:
        (self.workspace / "success fixture.ps1").write_text(
            'param([string]$Value)\nWrite-Output "child-output-$Value"\nexit 0\n', encoding="utf-8"
        )
        (self.workspace / "failure fixture.ps1").write_text(
            '[Console]::Error.WriteLine("expected-child-failure")\nexit 7\n', encoding="utf-8"
        )
        result = self.run_powershell("""
$output = @(Invoke-DemoScript -Name 'success fixture.ps1' -ScriptArguments @('-Value', 'passed'))
$failed = $false
try { Invoke-DemoScript -Name 'failure fixture.ps1' } catch { $failed = $true }
@{ outputCount = $output.Count; failed = $failed;
   stdout = [IO.File]::ReadAllText((Join-Path $script:logDirectory 'launcher-success fixture.out.log'));
   stderr = [IO.File]::ReadAllText((Join-Path $script:logDirectory 'launcher-failure fixture.err.log')) }
""")
        self.assertEqual(result["outputCount"], 0)
        self.assertTrue(result["failed"])
        self.assertIn("child-output-passed", result["stdout"])
        self.assertIn("expected-child-failure", result["stderr"])

    def test_start_batch_handles_spaces_and_cyrillic_project_paths(self) -> None:
        shutil.copyfile(PROJECT_ROOT / "START.bat", self.workspace / "START.bat")
        (self.workspace / "scripts/launcher.ps1").write_text(
            "[IO.File]::WriteAllText((Join-Path (Split-Path -Parent $PSScriptRoot) "
            "'batch-marker.txt'), 'started')\nexit 0\n",
            encoding="utf-8-sig",
        )
        completed = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "START.bat"],
            cwd=self.workspace,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(
            (self.workspace / "batch-marker.txt").read_text(encoding="utf-8"), "started"
        )

    def test_slack_configuration_is_optional_and_never_returns_credentials(self) -> None:
        configuration_python = ps_quote(PROJECT_ROOT / ".venv/Scripts/python.exe")
        configuration_probe = (
            "Get-SlackConfiguration -Root $script:projectDirectory "
            f"-PythonPath {configuration_python}"
        )
        missing = self.run_powershell(configuration_probe)
        self.assertFalse(missing["configured"])
        self.assertFalse(missing["partial"])
        (self.workspace / ".env").write_text(
            "SLACK_BOT_TOKEN='xoxb-private-fixture'\nSLACK_APP_TOKEN=xapp-private-fixture\n"
            "SLACK_TEAM_ID=TDEMO # workspace\nSLACK_EMPLOYEE_USER_ID=UDEMO\n",
            encoding="utf-8",
        )
        configured = self.run_powershell(configuration_probe)
        self.assertEqual(configured, {"configured": True, "partial": False, "missing": []})
        partial = self.run_powershell("$env:SLACK_TEAM_ID = ' '\n" + configuration_probe)
        self.assertFalse(partial["configured"])
        self.assertTrue(partial["partial"])
        self.assertEqual(partial["missing"], ["SLACK_TEAM_ID"])

    def test_start_shares_dotenv_parsing_for_slack_and_backend_settings(self) -> None:
        (self.workspace / ".env").write_text(
            "OPENAI_MODEL=launcher-fixture\n"
            "SLACK_BOT_TOKEN='xoxb-private-fixture'\nSLACK_APP_TOKEN=xapp-private-fixture\n"
            "export SLACK_TEAM_ID=TDEMO # workspace\nSLACK_EMPLOYEE_USER_ID=UDEMO\n"
            "POLL_INTERVAL_SECONDS=12 # polling\n",
            encoding="utf-8-sig",
        )
        result = self.run_powershell("""
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $script:projectDirectory 'run_demo.ps1'), [ref]$null, [ref]$null)
$importer = $ast.Find({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Import-DotEnv'
}, $true)
Invoke-Expression $importer.Extent.Text
Import-DotEnv -Path (Join-Path $script:projectDirectory '.env') -PythonPath $script:fixturePython
@{ configured = (Get-SlackConfiguration -Root $script:projectDirectory).configured;
   imported_slack = @((Get-ChildItem Env:) | Where-Object { $_.Name -like 'SLACK_*' }).Count;
   model = $env:OPENAI_MODEL; interval = $env:POLL_INTERVAL_SECONDS }
""")
        self.assertEqual(
            result,
            {
                "configured": True,
                "imported_slack": 4,
                "model": "launcher-fixture",
                "interval": "12",
            },
        )

    def test_blank_template_does_not_erase_inherited_slack_configuration_on_start(self) -> None:
        (self.workspace / ".env").write_text(
            "SLACK_BOT_TOKEN=\nSLACK_APP_TOKEN=\nSLACK_TEAM_ID=\nSLACK_EMPLOYEE_USER_ID=\n",
            encoding="utf-8",
        )
        result = self.run_powershell("""
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $script:projectDirectory 'run_demo.ps1'), [ref]$null, [ref]$null)
$importer = $ast.Find({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Import-DotEnv'
}, $true)
Invoke-Expression $importer.Extent.Text
$env:SLACK_BOT_TOKEN = 'xoxb-process-fixture'
$env:SLACK_APP_TOKEN = 'xapp-process-fixture'
$env:SLACK_TEAM_ID = 'TDEMO'
$env:SLACK_EMPLOYEE_USER_ID = 'UDEMO'
Import-DotEnv -Path (Join-Path $script:projectDirectory '.env') -PythonPath $script:fixturePython
Get-SlackConfiguration -Root $script:projectDirectory
""")
        self.assertEqual(result, {"configured": True, "partial": False, "missing": []})

    def test_process_identity_preserves_native_datetime_timezone_in_powershell_7(self) -> None:
        result = self.run_powershell("""
$process = Get-Process -Id $PID
$entry = [pscustomobject]@{ name='fixture'; pid=$PID; executable=$process.Path; marker='';
    started_at=$process.StartTime.ToUniversalTime() }
$native = $null -ne (Get-OwnedDemoProcess -Entry $entry)
$entry.started_at = $entry.started_at.ToString('o')
$iso = $null -ne (Get-OwnedDemoProcess -Entry $entry)
@{ native=$native; iso=$iso }
""")
        self.assertTrue(result["native"])
        self.assertTrue(result["iso"])

    def test_slack_readiness_requires_live_owner_fresh_heartbeat_and_matching_api(self) -> None:
        result = self.run_powershell("""
Initialize-LocalConfiguration
function Get-OwnedDemoProcess { return $true }
$state = [ordered]@{ services = @([pscustomobject]@{ name='slack'; pid=123 }); api_url='http://127.0.0.1:8123' }
$healthPath = Join-Path $script:stateDirectory 'slack_health.json'
$health = @{ pid=123; api_url=$state.api_url; status='connected'; updated_at=[DateTimeOffset]::UtcNow.ToString('o') }
function Read-FixtureHealth {
    $health | ConvertTo-Json | Set-Content -LiteralPath $healthPath -Encoding UTF8
    Get-SlackServiceStatus -State $state -Root $script:projectDirectory
}
$connected = Read-FixtureHealth
$health.status = 'disconnected'
$disconnected = Read-FixtureHealth
$health.status = 'connected'
$health.pid = 999
$wrongPid = Read-FixtureHealth
$health.pid = 123
$health.api_url = 'http://127.0.0.1:8000'
$wrongApi = Read-FixtureHealth
$health.api_url = $state.api_url
$health.updated_at = [DateTimeOffset]::UtcNow.AddMinutes(-2).ToString('o')
$stale = Read-FixtureHealth
$health.updated_at = [DateTimeOffset]::UtcNow.ToString('o')
function Get-OwnedDemoProcess { return $null }
$dead = Read-FixtureHealth
@{ connected=$connected; disconnected=$disconnected; wrongPid=$wrongPid; wrongApi=$wrongApi; stale=$stale; dead=$dead }
""")
        self.assertEqual(result["connected"], "connected")
        self.assertEqual(result["disconnected"], "disconnected")
        self.assertEqual(result["dead"], "stopped")
        for key in ("wrongPid", "wrongApi", "stale"):
            self.assertEqual(result[key], "unresponsive")

    def test_running_demo_requires_connected_slack_when_configured(self) -> None:
        result = self.run_powershell("""
Initialize-LocalConfiguration
function Get-OwnedDemoProcess { return $true }
function Get-SlackConfiguration { return @{ configured=$true } }
function Invoke-RestMethod { return @{ status='ok'; api_version='v1' } }
function Invoke-WebRequest { return @{ StatusCode=200 } }
$state = @{ project_root=$script:projectDirectory; api_url='http://127.0.0.1:8123'; frontend_url='http://127.0.0.1:5273'; services=@(
    @{name='api';pid=1}, @{name='frontend';pid=2}, @{name='slack';pid=3}) }
Write-DemoProcessState -Path $script:stateFile -State $state
$health = @{pid=3;api_url=$state.api_url;status='connected';updated_at=[DateTimeOffset]::UtcNow.ToString('o')}
$healthPath = Join-Path $script:stateDirectory 'slack_health.json'
$health | ConvertTo-Json | Set-Content -LiteralPath $healthPath -Encoding UTF8
$connected = $null -ne (Get-RunningDemo)
$health.status = 'disconnected'
$health | ConvertTo-Json | Set-Content -LiteralPath $healthPath -Encoding UTF8
$disconnected = $null -ne (Get-RunningDemo)
$state.services = @($state.services | Where-Object { $_.name -ne 'slack' })
Write-DemoProcessState -Path $script:stateFile -State $state
$missing = $null -ne (Get-RunningDemo)
@{ connected=$connected; disconnected=$disconnected; missing=$missing }
""")
        self.assertTrue(result["connected"])
        self.assertFalse(result["disconnected"])
        self.assertFalse(result["missing"])

    def test_python_redirector_tracks_and_stops_real_worker_without_orphans(self) -> None:
        python = PROJECT_ROOT / ".venv/Scripts/python.exe"
        if not python.is_file():
            self.skipTest("Requires the project's Windows Python environment")
        (self.workspace / "launcher_worker_fixture.py").write_text(
            "import os, pathlib, time\n"
            "pathlib.Path('worker-pid.txt').write_text(str(os.getpid()))\n"
            "time.sleep(25)\n",
            encoding="utf-8",
        )
        result = self.run_powershell(f"""
$child = Start-Process -FilePath {ps_quote(python)} -ArgumentList @('-m', 'launcher_worker_fixture') `
    -WorkingDirectory $script:projectDirectory -WindowStyle Hidden -PassThru
$state = $null
try {{
    $entry = New-DemoProcessEntry -Name slack -Process $child -Marker launcher_worker_fixture
    $state = [pscustomobject]@{{ services=@($entry) }}
    $workerPid = [int][IO.File]::ReadAllText((Join-Path $script:projectDirectory 'worker-pid.txt'))
    $tracked = $entry.pid -eq $workerPid
    $result = Stop-DemoProcesses -State $state
    @{{ tracked=$tracked; workerPid=$workerPid; launcherPid=$child.Id;
       unverified=@($result.unverified).Count;
       workerAlive=$null -ne (Get-Process -Id $workerPid -ErrorAction SilentlyContinue);
       launcherAlive=$null -ne (Get-Process -Id $child.Id -ErrorAction SilentlyContinue) }}
}} finally {{
    if ($state) {{ $null = Stop-DemoProcesses -State $state }}
    elseif (-not $child.HasExited) {{ Stop-Process -Id $child.Id -Force }}
}}
""")
        self.assertTrue(result["tracked"], result)
        self.assertEqual(result["unverified"], 0, result)
        self.assertFalse(result["workerAlive"], result)
        self.assertFalse(result["launcherAlive"], result)

    def test_start_keeps_cleanup_identity_when_state_write_or_next_service_fails(self) -> None:
        (self.workspace / "tracked_worker_fixture.py").write_text(
            "import time\ntime.sleep(25)\n", encoding="utf-8"
        )
        for failure in ("state_write", "next_service"):
            with self.subTest(failure=failure):
                body = """
. (Join-Path $script:projectDirectory 'run_demo.ps1')
Initialize-LocalConfiguration
$state = [ordered]@{ services=@() }
$entry = $null
$failed = $false
FAILURE_SETUP
try {
    $null = Start-TrackedDemoProcess -State $state -StatePath $script:stateFile -Name api `
        -FilePath $script:fixturePython -ArgumentList @('-m', 'tracked_worker_fixture') `
        -WorkingDirectory $script:projectDirectory -LogDirectory $script:logDirectory -Marker tracked_worker_fixture
    NEXT_SERVICE
} catch { $failed = $true }
try {
    $entry = $state.services[0]
    $result = Stop-DemoProcesses -State $state
    @{ failed=$failed; tracked=@($state.services).Count; unverified=@($result.unverified).Count;
       workerAlive=$null -ne (Get-Process -Id $entry.pid -ErrorAction SilentlyContinue);
       launcherAlive=$null -ne (Get-Process -Id $entry.launcher.pid -ErrorAction SilentlyContinue) }
} finally {
    $null = Stop-DemoProcesses -State $state
}
"""
                body = body.replace(
                    "FAILURE_SETUP",
                    "function Write-DemoProcessState { throw 'fixture state write failure' }"
                    if failure == "state_write"
                    else "",
                ).replace(
                    "NEXT_SERVICE",
                    ""
                    if failure == "state_write"
                    else """
    $null = Start-TrackedDemoProcess -State $state -StatePath $script:stateFile -Name frontend `
        -FilePath 'nonexistent-peopleflow-fixture.exe' -ArgumentList @('fixture') `
        -WorkingDirectory $script:projectDirectory -LogDirectory $script:logDirectory -Marker fixture
""",
                )
                result = self.run_powershell(body)
                self.assertTrue(result["failed"], result)
                self.assertEqual(result["tracked"], 1, result)
                self.assertEqual(result["unverified"], 0, result)
                self.assertFalse(result["workerAlive"], result)
                self.assertFalse(result["launcherAlive"], result)

    def test_service_lock_rejects_concurrent_operations_and_releases_afterwards(self) -> None:
        (self.workspace / "lock fixture.ps1").write_text(
            ". (Join-Path $PSScriptRoot 'scripts/demo_processes.ps1')\n"
            "$lock = Enter-DemoLifecycleLock -Root $PSScriptRoot\n"
            "Exit-DemoLifecycleLock -Mutex $lock\n",
            encoding="utf-8",
        )
        result = self.run_powershell("""
$lock = Enter-DemoLifecycleLock -Root $script:projectDirectory
$blocked = $false
try {
    try { Invoke-DemoScript -Name 'lock fixture.ps1' } catch { $blocked = $true }
} finally { Exit-DemoLifecycleLock -Mutex $lock }
Invoke-DemoScript -Name 'lock fixture.ps1'
@{ blocked=$blocked; released=$true; stateExists=(Test-Path -LiteralPath $script:stateFile) }
""")
        self.assertTrue(result["blocked"])
        self.assertTrue(result["released"])
        self.assertFalse(result["stateExists"])

    def test_restart_is_one_atomic_child_operation_with_automatic_ports(self) -> None:
        result = self.run_powershell("""
Initialize-LocalConfiguration
[IO.File]::WriteAllText($script:stateFile, '{}')
$script:checks = 0
function Get-RunningDemo {
    $script:checks += 1
    if ($script:checks -gt 1) { return @{ frontend_url='http://127.0.0.1:5173';slack_status='not_configured' } }
}
function Test-DependenciesReady { return $true }
function Get-AvailableDemoPort { throw 'Ports must be selected inside the service operation lock' }
$script:calls = @()
function Invoke-DemoScript { param($Name, $ScriptArguments) $script:calls += @{name=$Name;arguments=$ScriptArguments} }
$null = Start-PeopleFlow -Restart
@{ count=@($script:calls).Count; name=$script:calls[0].name; arguments=$script:calls[0].arguments }
""")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["name"], "run_demo.ps1")
        self.assertIn("-ForceRestart", result["arguments"])
        self.assertIn("-AutoPorts", result["arguments"])

    def test_shared_slack_check_action_does_not_start_or_configure_services(self) -> None:
        result = self.run_powershell("""
$pythonPath = Join-Path $script:projectDirectory '.venv/Scripts/python.exe'
New-Item -ItemType Directory -Path (Split-Path $pythonPath) -Force | Out-Null
Add-Type -OutputAssembly $pythonPath -OutputType ConsoleApplication -TypeDefinition @'
using System;
public class SlackCheckProbe {
    public static int Main(string[] args) {
        System.IO.File.WriteAllText(Environment.GetEnvironmentVariable("SLACK_CHECK_PROBE"), string.Join("|", args));
        return 0;
    }
}
'@
$env:SLACK_CHECK_PROBE = Join-Path $script:projectDirectory 'check-arguments.txt'
Invoke-DemoScript -Name 'scripts/launcher.ps1' -ScriptArguments @('-Action', 'CheckSlack', '-NoBrowser')
@{ arguments=[IO.File]::ReadAllText($env:SLACK_CHECK_PROBE);
   state=(Test-Path -LiteralPath $script:stateFile); env=(Test-Path -LiteralPath (Join-Path $script:projectDirectory '.env')) }
""")
        self.assertEqual(result["arguments"], "-I|-m|peopleflow_slack|--check")
        self.assertFalse(result["state"])
        self.assertFalse(result["env"])
