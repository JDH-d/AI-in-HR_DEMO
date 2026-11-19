$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSCommandPath
. (Join-Path $projectRoot "scripts/demo_processes.ps1")
$pidFile = Join-Path $projectRoot ".demo_state/demo_processes.json"
$operationLock = Enter-DemoOperationLock -ProjectRoot $projectRoot
try {
    $processes = @(Get-DemoProcesses -PidFile $pidFile)
    foreach ($process in $processes) {
        Stop-DemoProcess -Process $process
        Write-Host "Stopped demo process: $($process.Id)"
    }
    if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile -Force }
    if ($processes.Count -eq 0) { Write-Host "No running demo processes found." }
} finally {
    Exit-DemoOperationLock -Lock $operationLock
}
