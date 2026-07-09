param()

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSCommandPath
if (-not $projectRoot) {
    $projectRoot = (Get-Location).Path
}

$pidFile = Join-Path $projectRoot ".demo_state\demo_processes.json"

if (-not (Test-Path $pidFile)) {
    Write-Host "No demo PID file found. Nothing to stop."
    exit 0
}

try {
    $meta = Get-Content -Path $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Warning "Cannot parse PID file. Remove it manually: $pidFile"
    exit 1
}

$stopped = @()
foreach ($name in @("api_pid", "user_ui_pid", "admin_ui_pid")) {
    if (-not ($meta.PSObject.Properties.Name -contains $name)) {
        continue
    }
    $pidValue = [int]$meta.$name
    if ($pidValue -le 0) {
        continue
    }
    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        $stopped += $pidValue
    }
}

Remove-Item -Path $pidFile -Force

if ($stopped.Count -gt 0) {
    Write-Host "Stopped demo processes: $($stopped -join ', ')"
} else {
    Write-Host "No running demo processes were found."
}
