param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSCommandPath
if (-not $projectRoot) {
    throw "Unable to resolve the project root."
}
$projectRoot = [IO.Path]::GetFullPath($projectRoot)
. (Join-Path $projectRoot "scripts\demo_processes.ps1")

$lifecycleLock = Enter-DemoLifecycleLock -Root $projectRoot
try {
    $pidFile = Join-Path $projectRoot ".demo_state\demo_processes.json"
    $state = Read-DemoProcessState -Path $pidFile
    if (-not $state) {
        Write-Host "No demo process state found. Nothing to stop."
        exit 0
    }
    if ($state.project_root -and $state.project_root -ne $projectRoot) {
        throw 'The saved process state belongs to a different project. It was preserved; no processes were stopped.'
    }

    $result = Stop-DemoProcesses -State $state
    if ($result.unverified.Count -gt 0) {
        throw (
            "Refused to stop PID(s) $($result.unverified -join ', ') because their process identity " +
            "does not match the saved demo state. The state file was kept for inspection: $pidFile"
        )
    }

    Remove-Item -LiteralPath $pidFile -Force
    if ($result.stopped.Count -gt 0) {
        Write-Host "Stopped demo processes: $($result.stopped -join ', ')"
    } else {
        Write-Host "The recorded demo processes were already stopped."
    }
} finally {
    Exit-DemoLifecycleLock -Mutex $lifecycleLock
}
