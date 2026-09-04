param(
    [ValidateRange(1, 65535)][int]$ApiPort = 8000,
    [ValidateRange(1, 65535)][int]$UserUiPort = 5173,
    [switch]$InstallDeps,
    [switch]$SkipIndexRebuild,
    [switch]$ForceRestart
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSCommandPath
if (-not $projectRoot) {
    throw "Unable to resolve the project root."
}
$projectRoot = [IO.Path]::GetFullPath($projectRoot)
. (Join-Path $projectRoot "scripts\demo_processes.ps1")

function Resolve-BootstrapPython {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ FilePath = "python"; PrefixArgs = @() }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ FilePath = "py"; PrefixArgs = @("-3") }
    }
    throw "Python 3 was not found in PATH."
}

function Resolve-ProjectPython {
    param([string]$Root, [bool]$MayCreate)

    $virtualEnvironment = Join-Path $Root ".venv"
    $virtualPython = Join-Path $virtualEnvironment "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $virtualPython)) {
        if (-not $MayCreate) {
            throw "Missing .venv. Run .\run_demo.ps1 -InstallDeps once to create it."
        }
        $bootstrap = Resolve-BootstrapPython
        & $bootstrap.FilePath @($bootstrap.PrefixArgs + @("-m", "venv", $virtualEnvironment))
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $virtualPython)) {
            throw "Python virtual environment creation failed."
        }
    }
    return $virtualPython
}

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warning "No .env file found. AI calls will use deterministic fallbacks."
        return
    }
    foreach ($rawLine in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        $separator = $line.IndexOf("=")
        if ($separator -le 0) {
            continue
        }
        $key = $line.Substring(0, $separator).Trim()
        if ($key -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            throw "Invalid environment variable name in .env: $key"
        }
        $value = $line.Substring($separator + 1).Trim()
        if ($value.Length -ge 2) {
            $quoted = ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))
            if ($quoted) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        Set-Item -Path "Env:$key" -Value $value
    }
}

function Set-DefaultEnvironmentValue {
    param([string]$Name, [string]$Value)

    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($Name, "Process"))) {
        Set-Item -Path "Env:$Name" -Value $Value
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
    foreach ($path in @($stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
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
    param([string]$BaseUrl, [Diagnostics.Process]$Process, [int]$TimeoutSeconds = 45)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            return $false
        }
        try {
            $health = Invoke-RestMethod -Uri "$BaseUrl/api/v1/health" -Method Get -TimeoutSec 3
            if ($health.status -eq "ok" -and $health.api_version -eq "v1") {
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    }
    return $false
}

function Wait-FrontendReady {
    param([string]$Url, [Diagnostics.Process]$Process, [int]$TimeoutSeconds = 30)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            return $false
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 3 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

$logDirectory = Join-Path $projectRoot ".demo_logs"
$stateDirectory = Join-Path $projectRoot ".demo_state"
$pidFile = Join-Path $stateDirectory "demo_processes.json"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null

$existingState = Read-DemoProcessState -Path $pidFile
if ($existingState) {
    $existingEntries = @(Get-DemoProcessEntries -State $existingState)
    $runningEntries = @(
        $existingEntries | Where-Object { Get-Process -Id ([int]$_.pid) -ErrorAction SilentlyContinue }
    )
    if ($runningEntries.Count -gt 0 -and -not $ForceRestart) {
        throw "Demo services are already recorded as running. Use -ForceRestart or .\stop_demo.ps1."
    }
    if ($runningEntries.Count -gt 0) {
        $stopResult = Stop-DemoProcesses -State $existingState
        if ($stopResult.unverified.Count -gt 0) {
            throw "Refused to stop unverified PIDs: $($stopResult.unverified -join ', ')."
        }
    }
    Remove-Item -LiteralPath $pidFile -Force
}

$python = Resolve-ProjectPython -Root $projectRoot -MayCreate $InstallDeps
$node = (Get-Command node -ErrorAction Stop).Source
$frontendDirectory = Join-Path $projectRoot "frontend"
if ($InstallDeps) {
    & $python -m pip install -r (Join-Path $projectRoot "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency installation failed."
    }
    & npm --prefix $frontendDirectory ci
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend dependency installation failed."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendDirectory "node_modules"))) {
    throw "Missing frontend dependencies. Run .\run_demo.ps1 -InstallDeps once."
}

Import-DotEnv -Path (Join-Path $projectRoot ".env")
$apiBaseUrl = "http://127.0.0.1:$ApiPort"
$frontendUrl = "http://127.0.0.1:$UserUiPort"
Set-DefaultEnvironmentValue "DEMO_LOGIN_PASSWORD" "demo-password"
Set-DefaultEnvironmentValue "DEMO_AUTH_SECRET" "local-demo-secret-change-before-sharing"
Set-DefaultEnvironmentValue "WORKFLOW_DB" (Join-Path $stateDirectory "workflow.db")
Set-DefaultEnvironmentValue "CONVERSATION_DB" (Join-Path $stateDirectory "conversations.db")
Set-DefaultEnvironmentValue "LOG_PATH" (Join-Path $stateDirectory "chat_logs.jsonl")
Set-DefaultEnvironmentValue "INDEX_PATH" (Join-Path $stateDirectory "index.json")
Set-DefaultEnvironmentValue "INDEX_STATUS_PATH" (Join-Path $stateDirectory "index_status.json")
Set-DefaultEnvironmentValue "AI_SETTINGS_PATH" (Join-Path $stateDirectory "ai_settings.json")
$env:VITE_API_URL = $apiBaseUrl
$env:PYTHONUNBUFFERED = "1"

$apiProcess = $null
$frontendProcess = $null
try {
    $apiProcess = Start-DemoProcess `
        -Name "api" `
        -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
        -WorkingDirectory $projectRoot `
        -LogDirectory $logDirectory
    $frontendProcess = Start-DemoProcess `
        -Name "frontend" `
        -FilePath $node `
        -ArgumentList @("node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "$UserUiPort") `
        -WorkingDirectory $frontendDirectory `
        -LogDirectory $logDirectory

    $state = [ordered]@{
        version = 2
        project_root = $projectRoot
        services = @(
            New-DemoProcessEntry -Name "api" -Process $apiProcess -Marker "app:app"
            New-DemoProcessEntry -Name "frontend" -Process $frontendProcess -Marker "vite"
        )
        api_url = $apiBaseUrl
        frontend_url = $frontendUrl
        logs_dir = $logDirectory
    }
    Write-DemoProcessState -Path $pidFile -State $state

    if (-not (Wait-ApiReady -BaseUrl $apiBaseUrl -Process $apiProcess)) {
        throw "API did not become healthy. Check .demo_logs\api.err.log."
    }
    if (-not (Wait-FrontendReady -Url $frontendUrl -Process $frontendProcess)) {
        throw "Frontend did not become ready. Check .demo_logs\frontend.err.log."
    }

    if (-not $SkipIndexRebuild) {
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
            $headers = @{ Authorization = "Bearer $($login.access_token)" }
            Invoke-RestMethod `
                -Uri "$apiBaseUrl/api/v1/documents/index" `
                -Method Post `
                -Headers $headers `
                -TimeoutSec 180 | Out-Null
            Write-Host "Knowledge index rebuilt."
        } catch {
            Write-Warning "Knowledge index rebuild failed: $($_.Exception.Message)"
        }
    }
} catch {
    if (Test-Path -LiteralPath $pidFile) {
        $failedState = Read-DemoProcessState -Path $pidFile
        if ($failedState) {
            $cleanupResult = Stop-DemoProcesses -State $failedState
            if ($cleanupResult.unverified.Count -gt 0) {
                Write-Warning (
                    "Startup cleanup could not verify PID(s) " +
                    "$($cleanupResult.unverified -join ', '). State was kept at $pidFile."
                )
            } else {
                Remove-Item -LiteralPath $pidFile -Force
            }
        }
    } else {
        foreach ($process in @($apiProcess, $frontendProcess)) {
            if ($process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    throw
}

Write-Host ""
Write-Host "Demo services started."
Write-Host "Employee:        $frontendUrl/employee"
Write-Host "Manager:         $frontendUrl/manager"
Write-Host "Knowledge Admin: $frontendUrl/knowledge"
Write-Host "API docs:        $apiBaseUrl/docs"
Write-Host "Logs:            $logDirectory"
Write-Host ""
Write-Host "Stop safely with: .\stop_demo.ps1"
