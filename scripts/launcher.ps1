param(
    [ValidateSet("Menu", "Start", "Restart", "Stop", "Status")][string]$Action = "Menu",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$script:projectDirectory = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$script:stateDirectory = Join-Path $script:projectDirectory ".demo_state"
$script:stateFile = Join-Path $script:stateDirectory "demo_processes.json"
$script:setupFile = Join-Path $script:stateDirectory "launcher_setup.json"
$script:logDirectory = Join-Path $script:projectDirectory ".demo_logs"
$script:powershell = Join-Path $PSHOME "powershell.exe"
if (-not (Test-Path -LiteralPath $script:powershell)) {
    $script:powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
}
. (Join-Path $PSScriptRoot "demo_processes.ps1")

function Get-AvailableDemoPort {
    param([int]$Preferred)
    for ($candidate = $Preferred; $candidate -lt [Math]::Min($Preferred + 50, 65536); $candidate++) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $candidate)
        try {
            $listener.Server.ExclusiveAddressUse = $true
            $listener.Start()
            return $candidate
        } catch [Net.Sockets.SocketException] {
            # Try the next port; never stop the process which owns this one.
        } finally {
            $listener.Stop()
        }
    }
    throw "No available port found near $Preferred. Close unused local servers and try again."
}

function Get-RunningDemo {
    $state = Read-DemoProcessState -Path $script:stateFile
    if (-not $state) { return $null }
    if ([string]$state.project_root -ne $script:projectDirectory) { return $null }
    $entries = @(Get-DemoProcessEntries -State $state)
    if ($entries.Count -ne 2) { return $null }
    foreach ($entry in $entries) {
        if (-not (Get-OwnedDemoProcess -Entry $entry)) { return $null }
    }
    if ([string]$state.api_url -notmatch '^http://127\.0\.0\.1:\d+$' -or
        [string]$state.frontend_url -notmatch '^http://127\.0\.0\.1:\d+$') { return $null }
    try {
        $health = Invoke-RestMethod -Uri "$($state.api_url)/api/v1/health" -TimeoutSec 3
        $ui = Invoke-WebRequest -Uri $state.frontend_url -UseBasicParsing -TimeoutSec 3
        if ($health.status -eq "ok" -and $health.api_version -eq "v1" -and $ui.StatusCode -eq 200) {
            return $state
        }
    } catch { }
    return $null
}

function Initialize-LocalConfiguration {
    New-Item -ItemType Directory -Path $script:stateDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $script:logDirectory -Force | Out-Null
    $envPath = Join-Path $script:projectDirectory ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        $template = [IO.File]::ReadAllText((Join-Path $script:projectDirectory ".env.example"))
        $template = $template.Replace("OPENAI_API_KEY=your_openai_api_key", "OPENAI_API_KEY=")
        [IO.File]::WriteAllText($envPath, $template, [Text.UTF8Encoding]::new($false))
        Write-Host "Created .env. You can use the demo without an API key; choose 4 to add one later." -ForegroundColor DarkCyan
    }
}

function Get-SetupFingerprint {
    $hashes = foreach ($relative in @("requirements.txt", "frontend/package.json", "frontend/package-lock.json")) {
        (Get-FileHash -LiteralPath (Join-Path $script:projectDirectory $relative) -Algorithm SHA256).Hash
    }
    return $hashes -join ":"
}

function Test-DependenciesReady {
    param([string]$Fingerprint)
    $pythonPath = Join-Path $script:projectDirectory ".venv\Scripts\python.exe"
    $vitePath = Join-Path $script:projectDirectory "frontend\node_modules\vite\bin\vite.js"
    if (-not (Test-Path -LiteralPath $script:setupFile) -or
        -not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath $vitePath)) {
        return $false
    }
    try {
        $stamp = Get-Content -LiteralPath $script:setupFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($stamp.fingerprint -ne $Fingerprint -or $stamp.project_root -ne $script:projectDirectory) {
            return $false
        }
        & $pythonPath -I -c "import fastapi, uvicorn, openai, dotenv, pypdf, docx, multipart" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Invoke-DemoScript {
    param([string]$Name, [string[]]$ScriptArguments = @())
    # Separate process + file redirection avoids native pipelines waiting on server handles.
    New-Item -ItemType Directory -Path $script:logDirectory -Force | Out-Null
    $label = [IO.Path]::GetFileNameWithoutExtension($Name)
    $stdoutPath = Join-Path $script:logDirectory "launcher-$label.out.log"
    $stderrPath = Join-Path $script:logDirectory "launcher-$label.err.log"
    $arguments = @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        ('"' + (Join-Path $script:projectDirectory $Name) + '"')) + $ScriptArguments
    $process = Start-Process -FilePath $script:powershell -ArgumentList $arguments `
        -WorkingDirectory $script:projectDirectory -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
    # Keep the process handle: Windows PowerShell 5.1 otherwise may return a null ExitCode.
    $null = $process.Handle
    $timer = [Diagnostics.Stopwatch]::StartNew()
    try {
        while (-not $process.WaitForExit(500)) {
            if ($Action -eq "Menu") {
                Write-Host ("`rWorking... {0}s elapsed. Details are being saved to the logs." -f [int]$timer.Elapsed.TotalSeconds) -NoNewline
            }
        }
        $process.WaitForExit()
        # Read the exit code before disposing the process object.
        $exitCode = $process.ExitCode
    } finally {
        if ($Action -eq "Menu") { Write-Host "" }
        $process.Dispose()
    }
    if ($exitCode -ne 0) {
        Get-Content -LiteralPath $stderrPath -Tail 12 -Encoding UTF8 | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
        throw "The operation failed. See $stdoutPath and $stderrPath for details."
    }
}

function Start-PeopleFlow {
    param([switch]$Restart, [switch]$Repair)
    $running = Get-RunningDemo
    if ($running -and -not $Restart -and -not $Repair) {
        Write-Host "PeopleFlow is already running. Using the existing instance." -ForegroundColor Green
        return $running
    }
    if (Test-Path -LiteralPath $script:stateFile) {
        Write-Host "Stopping the previous PeopleFlow instance..."
        Invoke-DemoScript -Name "stop_demo.ps1"
    }
    Initialize-LocalConfiguration
    $fingerprint = Get-SetupFingerprint
    $install = $Repair -or -not (Test-DependenciesReady -Fingerprint $fingerprint)
    $apiPort = Get-AvailableDemoPort -Preferred 8000
    $uiPort = Get-AvailableDemoPort -Preferred 5173
    if ($apiPort -ne 8000 -or $uiPort -ne 5173) {
        Write-Host "A default port is busy. Using available ports: API $apiPort, interface $uiPort." -ForegroundColor DarkCyan
    }
    if ($install) {
        Write-Host "Setting up or updating dependencies. An internet connection is required." -ForegroundColor Cyan
        Write-Host "This usually takes a few minutes. Future launches will be faster."
    } else {
        Write-Host "Dependencies are ready. Starting services..." -ForegroundColor Cyan
    }
    $arguments = @("-ApiPort", "$apiPort", "-UserUiPort", "$uiPort", "-SkipIndexRebuild")
    if ($install) { $arguments += @("-InstallDeps", "-RuntimeDepsOnly") }
    Invoke-DemoScript -Name "run_demo.ps1" -ScriptArguments $arguments
    $running = Get-RunningDemo
    if (-not $running) { throw "Services started, but the readiness check failed. Choose 5 to open the logs." }
    if ($install) {
        @{ fingerprint = $fingerprint; project_root = $script:projectDirectory } |
            ConvertTo-Json | Set-Content -LiteralPath $script:setupFile -Encoding UTF8
    }
    Write-Host "Ready! $($running.frontend_url)" -ForegroundColor Green
    return $running
}

function Open-PeopleFlow {
    param($State)
    if ($State -and -not $NoBrowser) {
        try { Start-Process "$($State.frontend_url)/employee" }
        catch { Write-Host "Open this address in your browser: $($State.frontend_url)/employee" -ForegroundColor Yellow }
    }
}

function Stop-PeopleFlow {
    Invoke-DemoScript -Name "stop_demo.ps1"
    Write-Host "PeopleFlow has stopped. Your data is preserved." -ForegroundColor Green
}

function Show-LauncherError {
    param([string]$Message)
    Write-Host ""
    Write-Host "Something went wrong: $Message" -ForegroundColor Yellow
    Write-Host "Missing Python or Node.js? Choose 7. Dependency issues? Choose 6."
    Write-Host "Your chats, requests, documents, and .env are preserved."
}

function Install-RequiredTools {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    Write-Host "Python 3.10+ and Node.js 22.12+ are required. You can keep existing compatible versions."
    if (-not $winget) {
        Write-Host "Windows Package Manager was not found. Opening the official download pages."
        Start-Process "https://www.python.org/downloads/windows/"
        Start-Process "https://nodejs.org/en/download"
        return
    }
    Write-Host "1  Install Python 3.12    2  Install Node.js LTS    0  Back"
    $toolChoice = Read-Host "Choose an option"
    $package = switch ($toolChoice) {
        "1" { "Python.Python.3.12" }
        "2" { "OpenJS.NodeJS.LTS" }
        default { return }
    }
    Write-Host "Starting the installer. Windows may ask for permission to install."
    & $winget.Source install --exact --id $package --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Installation did not complete. Choose 7 to try again." }
    # Pick up installer PATH changes without requiring a new terminal.
    $paths = @(
        [Environment]::GetEnvironmentVariable("Path", "Machine")
        [Environment]::GetEnvironmentVariable("Path", "User")
        $env:Path
    ) | Where-Object { $_ }
    $env:Path = ($paths -join ";")
    Write-Host "Installation complete. Choose 1 to start PeopleFlow." -ForegroundColor Green
}

function Show-LauncherMenu {
    Write-Host ""
    Write-Host "  PeopleFlow AI" -ForegroundColor Cyan
    Write-Host "  1  Open / Start             2  Restart"
    Write-Host "  3  Stop                     4  Configure API key (.env)"
    Write-Host "  5  Open logs                6  Reinstall dependencies"
    Write-Host "  7  Install Python / Node.js"
    Write-Host "  0  Close this window (keep PeopleFlow running)"
    Write-Host "  9  Stop PeopleFlow and exit"
    Write-Host ""
}

# Dot-sourcing exposes helpers for isolated tests without starting any services.
if ($MyInvocation.InvocationName -eq ".") { return }

$mutex = $null
$ownsLock = $false
try {
    $Host.UI.RawUI.WindowTitle = "PeopleFlow AI - Launcher"
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $pathBytes = [Text.Encoding]::UTF8.GetBytes($script:projectDirectory.ToLowerInvariant())
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $lockId = [BitConverter]::ToString($sha.ComputeHash($pathBytes)).Replace("-", "") }
    finally { $sha.Dispose() }
    $mutex = [Threading.Mutex]::new($false, "Local\PeopleFlow-$lockId")
    try { $ownsLock = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $ownsLock = $true }
    if (-not $ownsLock) {
        $running = Get-RunningDemo
        if ($Action -eq "Status") {
            if ($running) { Write-Host "RUNNING $($running.frontend_url)"; exit 0 }
            Write-Host "STOPPED"; exit 1
        }
        if ($Action -in @("Menu", "Start") -and $running) {
            Open-PeopleFlow -State $running
            Write-Host "PeopleFlow is already running. Use the existing launcher window to manage it."
            exit 0
        }
        Write-Host "The PeopleFlow launcher is already open. Wait for startup or use its menu."
        if ($Action -eq "Menu") { Read-Host "Press Enter to close this window" | Out-Null; exit 0 }
        exit 1
    }
    Set-Location -LiteralPath $script:projectDirectory
    if ($Action -eq "Status") {
        $running = Get-RunningDemo
        if ($running) { Write-Host "RUNNING $($running.frontend_url)"; exit 0 }
        Write-Host "STOPPED"; exit 1
    }
    if ($Action -eq "Stop") { Stop-PeopleFlow; exit 0 }
    Write-Host ""
    Write-Host "PeopleFlow AI - Starting your workspace" -ForegroundColor Cyan
    Write-Host ""
    try {
        $running = Start-PeopleFlow -Restart:($Action -eq "Restart")
        Open-PeopleFlow -State $running
    } catch {
        Show-LauncherError -Message $_.Exception.Message
        if ($Action -ne "Menu") { exit 1 }
    }
    if ($Action -ne "Menu") { exit 0 }
    while ($true) {
        Show-LauncherMenu
        $choice = Read-Host "Choose an option"
        try {
            switch ($choice.Trim()) {
                "1" { Open-PeopleFlow -State (Start-PeopleFlow) }
                "2" { Open-PeopleFlow -State (Start-PeopleFlow -Restart) }
                "3" { Stop-PeopleFlow }
                "4" {
                    Initialize-LocalConfiguration
                    Start-Process -FilePath "notepad.exe" -ArgumentList ('"' + (Join-Path $script:projectDirectory ".env") + '"')
                    Write-Host "Save .env, then choose 2 to restart. Your saved key will be reused on future launches."
                }
                "5" {
                    New-Item -ItemType Directory -Path $script:logDirectory -Force | Out-Null
                    Invoke-Item -LiteralPath $script:logDirectory
                }
                "6" { Open-PeopleFlow -State (Start-PeopleFlow -Repair) }
                "7" { Install-RequiredTools }
                "9" { Stop-PeopleFlow; exit 0 }
                "0" { exit 0 }
                default { Write-Host "Enter one of the menu numbers." }
            }
        } catch { Show-LauncherError -Message $_.Exception.Message }
    }
} catch {
    Show-LauncherError -Message $_.Exception.Message
    exit 1
} finally {
    if ($ownsLock -and $mutex) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
