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
        for name in ("launcher.ps1", "demo_processes.ps1"):
            shutil.copyfile(PROJECT_ROOT / "scripts" / name, scripts / name)
        (self.workspace / "frontend").mkdir()
        for relative, content in {
            ".env.example": "OPENAI_API_KEY=your_openai_api_key\nDEMO_MODE=1\n",
            "requirements.txt": "fastapi==0.1\n",
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
$result = & {{
{body}
}}
[Console]::WriteLine('{RESULT_PREFIX}' + (ConvertTo-Json -InputObject $result -Depth 8 -Compress))
"""
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        # A parent pwsh 7 session can export its incompatible module path to powershell.exe.
        environment = {
            key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"
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
        self.assertEqual(len(original.split(":")), 3)
        previous = original
        for relative in (
            "requirements.txt",
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
