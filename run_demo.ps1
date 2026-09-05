param(
    [ValidateRange(1, 65535)][int]$ApiPort = 8000,
    [ValidateRange(1, 65535)][int]$UserUiPort = 5173,
    [switch]$InstallDeps,
    [switch]$RuntimeDepsOnly,
    [switch]$SkipIndexRebuild,
    [switch]$ForceRestart
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$projectRoot = Split-Path -Parent $PSCommandPath
if (-not $projectRoot) {
    throw "Unable to resolve the project root."
}
$projectRoot = [IO.Path]::GetFullPath($projectRoot)
. (Join-Path $projectRoot "scripts\demo_processes.ps1")

function Get-PythonRuntime {
    param([string]$FilePath, [string[]]$PrefixArgs = @())

    # Execute Python code instead of accepting a PATH entry or a Windows Store alias.
    $probeCode = "import json, sys; print(json.dumps({'version': list(sys.version_info[:3]), 'prefix': sys.prefix, 'base_prefix': sys.base_prefix}))"
    $probe = [Diagnostics.Process]::new()
    try {
        $probe.StartInfo.FileName = $FilePath
        $probe.StartInfo.Arguments = (@($PrefixArgs) + @("-I", "-c", ('"' + $probeCode + '"'))) -join " "
        $probe.StartInfo.UseShellExecute = $false
        $probe.StartInfo.CreateNoWindow = $true
        $probe.StartInfo.RedirectStandardOutput = $true
        $probe.StartInfo.RedirectStandardError = $true
        if (-not $probe.Start()) {
            return $null
        }
        $outputTask = $probe.StandardOutput.ReadToEndAsync()
        $errorTask = $probe.StandardError.ReadToEndAsync()
        if (-not $probe.WaitForExit(10000)) {
            $probe.Kill()
            return $null
        }
        if ($probe.ExitCode -ne 0) {
            return $null
        }
        $runtime = $outputTask.GetAwaiter().GetResult() | ConvertFrom-Json
        $null = $errorTask.GetAwaiter().GetResult()
        $version = [version]($runtime.version -join ".")
        if ($version -lt [version]"3.10") {
            return $null
        }
        return [pscustomobject]@{
            Version = $version
            Prefix = [string]$runtime.prefix
            IsVirtualEnvironment = $runtime.prefix -ne $runtime.base_prefix
        }
    } catch {
        return $null
    } finally {
        $probe.Dispose()
    }
}

function Resolve-BootstrapPython {
    foreach ($candidate in @(
        @{ Name = "python.exe"; PrefixArgs = @() },
        @{ Name = "py.exe"; PrefixArgs = @("-3") }
    )) {
        foreach ($command in @(Get-Command $candidate.Name -CommandType Application -ErrorAction SilentlyContinue)) {
            if (Get-PythonRuntime -FilePath $command.Source -PrefixArgs $candidate.PrefixArgs) {
                return @{ FilePath = $command.Source; PrefixArgs = $candidate.PrefixArgs }
            }
        }
    }
    throw "A working Python 3.10+ was not found. Install Python, then reopen the launcher. Windows Store placeholder aliases are not sufficient."
}

function Resolve-ProjectPython {
    param([string]$Root, [bool]$MayCreate)

    $virtualEnvironment = Join-Path $Root ".venv"
    $virtualPython = Join-Path $virtualEnvironment "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $virtualPython)) {
        if (Test-Path -LiteralPath $virtualEnvironment) {
            throw "The existing .venv is incomplete. Rename or repair $virtualEnvironment, then run .\run_demo.ps1 -InstallDeps."
        }
        if (-not $MayCreate) {
            throw "Missing .venv. Run .\run_demo.ps1 -InstallDeps once to create it."
        }
        $bootstrap = Resolve-BootstrapPython
        & $bootstrap.FilePath @($bootstrap.PrefixArgs + @("-m", "venv", $virtualEnvironment))
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $virtualPython)) {
            throw "Python virtual environment creation failed."
        }
    }
    $runtime = Get-PythonRuntime -FilePath $virtualPython
    if (-not $runtime -or -not $runtime.IsVirtualEnvironment -or -not [string]::Equals(
        [IO.Path]::GetFullPath($runtime.Prefix),
        [IO.Path]::GetFullPath($virtualEnvironment),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "The existing .venv cannot run Python 3.10+ correctly. Rename or repair $virtualEnvironment, then run .\run_demo.ps1 -InstallDeps."
    }
    return $virtualPython
}

function Resolve-ProjectNode {
    $command = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) {
        throw "Node.js 22.12+ was not found. Install Node.js, then reopen the launcher."
    }
    try {
        $reportedVersion = (& $command.Source -p "process.versions.node" 2>$null) -join ""
        if ($LASTEXITCODE -ne 0 -or $reportedVersion -notmatch '^\d+\.\d+\.\d+$' -or
            [version]$reportedVersion -lt [version]"22.12") {
            throw "Unsupported Node.js runtime."
        }
    } catch {
        throw "This demo requires Node.js 22.12 or newer. Update Node.js, then reopen the launcher."
    }
    return $command.Source
}

function Assert-DemoPortAvailable {
    param([int]$Port, [string]$Name, [string]$Option)

    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try {
        $listener.ExclusiveAddressUse = $true
        $listener.Start()
    } catch {
        throw "$Name port $Port is unavailable. Close the application using it or choose a different -$Option value."
    } finally {
        $listener.Stop()
    }
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

function Set-DemoCorsOrigins {
    param([int]$FrontendPort)

    $configured = [Environment]::GetEnvironmentVariable("CORS_ORIGINS", "Process")
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:5173,http://localhost:5173"
    }
    $origins = @($configured.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $origins += @("http://127.0.0.1:$FrontendPort", "http://localhost:$FrontendPort")
    $env:CORS_ORIGINS = ($origins | Select-Object -Unique) -join ","
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
if ($ApiPort -eq $UserUiPort) {
    throw "API and frontend need different ports. Set distinct -ApiPort and -UserUiPort values."
}
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

Assert-DemoPortAvailable -Port $ApiPort -Name "API" -Option "ApiPort"
Assert-DemoPortAvailable -Port $UserUiPort -Name "Frontend" -Option "UserUiPort"
$python = Resolve-ProjectPython -Root $projectRoot -MayCreate $InstallDeps
$node = Resolve-ProjectNode
$frontendDirectory = Join-Path $projectRoot "frontend"
if ($InstallDeps) {
    $npm = Get-Command npm.cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $npm) {
        throw "npm.cmd was not found. Repair your Node.js installation, then reopen the launcher."
    }
    $requirementsFile = if ($RuntimeDepsOnly) { "requirements.txt" } else { "requirements-dev.txt" }
    & $python -m pip install -r (Join-Path $projectRoot $requirementsFile)
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency installation failed."
    }
    & $npm.Source --prefix $frontendDirectory ci
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend dependency installation failed."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendDirectory "node_modules\vite\bin\vite.js"))) {
    throw "Missing frontend dependencies. Run .\run_demo.ps1 -InstallDeps once."
}

Import-DotEnv -Path (Join-Path $projectRoot ".env")
$apiBaseUrl = "http://127.0.0.1:$ApiPort"
$frontendUrl = "http://127.0.0.1:$UserUiPort"
Set-DemoCorsOrigins -FrontendPort $UserUiPort
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
Assert-DemoPortAvailable -Port $ApiPort -Name "API" -Option "ApiPort"
Assert-DemoPortAvailable -Port $UserUiPort -Name "Frontend" -Option "UserUiPort"
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
        -ArgumentList @("node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "$UserUiPort", "--strictPort") `
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
