param(
    [int]$ApiPort = 8000,
    [int]$UserUiPort = 5173,
    [int]$AdminUiPort = 0,
    [switch]$InstallDeps,
    [switch]$SkipIndexRebuild,
    [switch]$ForceRestart
)

$ErrorActionPreference = "Stop"

function Resolve-Python {
    $workspacePython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $workspacePython) {
        return @{
            FilePath = $workspacePython
            PrefixArgs = @()
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{
            FilePath = "python"
            PrefixArgs = @()
        }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{
            FilePath = "py"
            PrefixArgs = @("-3")
        }
    }
    throw "Python executable was not found in PATH."
}

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    foreach ($rawLine in Get-Content -Path $Path -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        $eqIndex = $line.IndexOf("=")
        if ($eqIndex -le 0) {
            continue
        }
        $key = $line.Substring(0, $eqIndex).Trim()
        $value = $line.Substring($eqIndex + 1).Trim()

        if ($value.Length -ge 2) {
            $startsWithDouble = $value.StartsWith('"')
            $endsWithDouble = $value.EndsWith('"')
            $startsWithSingle = $value.StartsWith("'")
            $endsWithSingle = $value.EndsWith("'")
            if (($startsWithDouble -and $endsWithDouble) -or ($startsWithSingle -and $endsWithSingle)) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }

        Set-Item -Path "Env:$key" -Value $value
    }
}

function Start-DemoProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$LogDirectory
    )

    $stdoutPath = Join-Path $LogDirectory "$Name.out.log"
    $stderrPath = Join-Path $LogDirectory "$Name.err.log"

    if (Test-Path $stdoutPath) {
        Remove-Item -Path $stdoutPath -Force
    }
    if (Test-Path $stderrPath) {
        Remove-Item -Path $stderrPath -Force
    }

    return Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -WindowStyle Hidden `
        -PassThru
}

function Wait-ApiReady {
    param(
        [string]$ApiBaseUrl,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "$ApiBaseUrl/api/v1/health" -Method Get -TimeoutSec 3
            if ($health.status -eq "ok") {
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 1000
            continue
        }
        Start-Sleep -Milliseconds 1000
    }
    return $false
}

function Get-RunningDemoPids {
    param([string]$PidFilePath)

    if (-not (Test-Path $PidFilePath)) {
        return @()
    }

    try {
        $meta = Get-Content -Path $PidFilePath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return @()
    }

    $running = @()
    foreach ($name in @("api_pid", "frontend_pid", "user_ui_pid", "admin_ui_pid")) {
        if (-not ($meta.PSObject.Properties.Name -contains $name)) {
            continue
        }
        $pidValue = [int]$meta.$name
        if ($pidValue -le 0) {
            continue
        }
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($proc) {
            $running += $pidValue
        }
    }
    return $running
}

$projectRoot = Split-Path -Parent $PSCommandPath
if (-not $projectRoot) {
    $projectRoot = (Get-Location).Path
}
Set-Location $projectRoot

$python = Resolve-Python
$apiBaseUrl = "http://127.0.0.1:$ApiPort"
$userUiUrl = "http://127.0.0.1:$UserUiPort"
$managerUiUrl = "$userUiUrl/manager"
$adminUiUrl = "$userUiUrl/knowledge"

$logDirectory = Join-Path $projectRoot ".demo_logs"
$stateDirectory = Join-Path $projectRoot ".demo_state"
$pidFile = Join-Path $stateDirectory "demo_processes.json"
$envFile = Join-Path $projectRoot ".env"

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null

Import-DotEnv -Path $envFile
$env:API_BASE_URL = $apiBaseUrl
$env:VITE_API_URL = $apiBaseUrl
$env:PYTHONUNBUFFERED = "1"
if (-not $env:DEMO_LOGIN_PASSWORD) {
    $env:DEMO_LOGIN_PASSWORD = "demo-password"
}
if (-not $env:DEMO_AUTH_SECRET) {
    $env:DEMO_AUTH_SECRET = "local-demo-secret-change-before-sharing"
}
if (-not $env:WORKFLOW_DB) {
    $env:WORKFLOW_DB = (Join-Path $stateDirectory "workflow.db")
}
if (-not $env:LOG_PATH) {
    $env:LOG_PATH = (Join-Path $stateDirectory "chat_logs.jsonl")
}
if (-not $env:INDEX_PATH) {
    $env:INDEX_PATH = (Join-Path $stateDirectory "index.json")
}
if (-not $env:INDEX_STATUS_PATH) {
    $env:INDEX_STATUS_PATH = (Join-Path $stateDirectory "index_status.json")
}
if (-not $env:SYSTEM_PROMPT_PATH) {
    $env:SYSTEM_PROMPT_PATH = (Join-Path $stateDirectory "system_prompt.txt")
}

$runningPids = Get-RunningDemoPids -PidFilePath $pidFile
if ($runningPids.Count -gt 0) {
    if (-not $ForceRestart) {
        throw "Demo services are already running (PIDs: $($runningPids -join ', ')). Use -ForceRestart to restart."
    }
    foreach ($runningPid in $runningPids) {
        Stop-Process -Id $runningPid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 1000
}

if ($InstallDeps) {
    & $python.FilePath @($python.PrefixArgs + @("-m", "pip", "install", "-r", "requirements.txt"))
    Push-Location (Join-Path $projectRoot "frontend")
    npm install
    Pop-Location
}
if (-not (Test-Path (Join-Path $projectRoot "frontend\node_modules"))) {
    Push-Location (Join-Path $projectRoot "frontend")
    npm install
    Pop-Location
}

$apiArgs = $python.PrefixArgs + @(
    "-m", "uvicorn", "app:app",
    "--host", "127.0.0.1",
    "--port", "$ApiPort"
)
$frontendArgs = @(
    "node_modules/vite/bin/vite.js",
    "--host", "127.0.0.1",
    "--port", "$UserUiPort"
)

$apiProc = Start-DemoProcess `
    -Name "api" `
    -FilePath $python.FilePath `
    -ArgumentList $apiArgs `
    -WorkingDirectory $projectRoot `
    -LogDirectory $logDirectory

$nodeCommand = (Get-Command node -ErrorAction Stop).Source
$frontendProc = Start-DemoProcess `
    -Name "frontend" `
    -FilePath $nodeCommand `
    -ArgumentList $frontendArgs `
    -WorkingDirectory (Join-Path $projectRoot "frontend") `
    -LogDirectory $logDirectory

$apiReady = Wait-ApiReady -ApiBaseUrl $apiBaseUrl -TimeoutSeconds 45
if (-not $apiReady) {
    Write-Warning "API did not become healthy in time. Check .demo_logs\\api.err.log"
}

if (-not $SkipIndexRebuild -and $apiReady) {
    if ($env:DEMO_LOGIN_PASSWORD) {
        try {
            $loginBody = @{
                username = "knowledge_admin"
                password = $env:DEMO_LOGIN_PASSWORD
            } | ConvertTo-Json
            $login = Invoke-RestMethod `
                -Uri "$apiBaseUrl/api/v1/auth/login" `
                -Method Post `
                -ContentType "application/json" `
                -Body $loginBody `
                -TimeoutSec 30
            $headers = @{ "Authorization" = "Bearer $($login.access_token)" }
            $documents = Invoke-RestMethod `
                -Uri "$apiBaseUrl/api/v1/documents" `
                -Method Get `
                -Headers $headers `
                -TimeoutSec 30
            if ($documents.documents.Count -gt 0) {
                $documentId = $documents.documents[0].id
                Invoke-RestMethod `
                    -Uri "$apiBaseUrl/api/v1/documents/$documentId/index" `
                    -Method Post `
                    -Headers $headers `
                    -TimeoutSec 180 | Out-Null
                Write-Host "RAG index rebuilt successfully."
            }
        } catch {
            Write-Warning "Index rebuild failed: $($_.Exception.Message)"
        }
    } else {
        Write-Warning "DEMO_LOGIN_PASSWORD is empty; skipped automatic index rebuild."
    }
}

$meta = [ordered]@{
    started_at = (Get-Date).ToString("o")
    api_pid = $apiProc.Id
    frontend_pid = $frontendProc.Id
    user_ui_pid = $frontendProc.Id
    admin_ui_pid = 0
    api_url = $apiBaseUrl
    user_ui_url = $userUiUrl
    admin_ui_url = $adminUiUrl
    logs_dir = $logDirectory
}
$meta | ConvertTo-Json | Set-Content -Path $pidFile -Encoding UTF8

Write-Host ""
Write-Host "Demo services started."
Write-Host "API:      $apiBaseUrl"
Write-Host "Employee:        $userUiUrl/employee"
Write-Host "Manager:         $managerUiUrl"
Write-Host "Knowledge Admin: $adminUiUrl"
Write-Host "Logs:     $logDirectory"
Write-Host "PIDs file: $pidFile"
Write-Host ""
Write-Host "To stop all services run: .\\stop_demo.ps1"
