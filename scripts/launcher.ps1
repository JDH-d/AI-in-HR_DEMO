param(
    [ValidateSet("Menu", "Start", "Restart", "Stop", "Status", "CheckSlack")][string]$Action = "Menu",
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
. (Join-Path $PSScriptRoot "slack_service.ps1")

function Get-RunningDemo {
    $state = Read-DemoProcessState -Path $script:stateFile
    if (-not $state) { return $null }
    if ([string]$state.project_root -ne $script:projectDirectory) { return $null }
    $entries = @(Get-DemoProcessEntries -State $state)
    $coreEntries = @($entries | Where-Object { $_.name -in @('api', 'frontend') })
    if ($coreEntries.Count -ne 2 -or @($coreEntries.name | Select-Object -Unique).Count -ne 2) { return $null }
    foreach ($entry in $coreEntries) {
        if (-not (Get-OwnedDemoProcess -Entry $entry)) { return $null }
    }
    $slackConfiguration = Get-SlackConfiguration -Root $script:projectDirectory
    $slackStatus = Get-SlackServiceStatus -State $state -Root $script:projectDirectory
    if ($slackConfiguration.configured -and $slackStatus -notin @('connected', 'disabled')) { return $null }
    if (-not $slackConfiguration.configured -and @($entries | Where-Object { $_.name -eq 'slack' }).Count -gt 0) { return $null }
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
    $hashes = foreach ($relative in @("requirements.txt", "slack/pyproject.toml", "frontend/package.json", "frontend/package-lock.json")) {
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
        $probe = 'import fastapi, uvicorn, openai, dotenv, pypdf, docx, multipart, slack_bolt, slack_sdk, httpx, peopleflow_slack, sys; from pathlib import Path; assert Path(peopleflow_slack.__file__).resolve().parent == Path(sys.argv[1]).resolve()'
        & $pythonPath -I -c $probe (Join-Path $script:projectDirectory 'slack/peopleflow_slack') 2>$null | Out-Null
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
        Show-SlackStatus -State $running -Root $script:projectDirectory
        return $running
    }
    Initialize-LocalConfiguration
    $fingerprint = Get-SetupFingerprint
    $install = $Repair -or -not (Test-DependenciesReady -Fingerprint $fingerprint)
    if ($install) {
        Write-Host "Setting up or updating dependencies. An internet connection is required." -ForegroundColor Cyan
        Write-Host "This usually takes a few minutes. Future launches will be faster."
    } else {
        Write-Host "Dependencies are ready. Starting services..." -ForegroundColor Cyan
    }
    $arguments = @('-AutoPorts', '-SkipIndexRebuild')
    if ($Restart -or $Repair -or (Test-Path -LiteralPath $script:stateFile)) { $arguments += '-ForceRestart' }
    if ($install) { $arguments += @("-InstallDeps", "-RuntimeDepsOnly") }
    Invoke-DemoScript -Name "run_demo.ps1" -ScriptArguments $arguments
    $running = Get-RunningDemo
    if (-not $running) { throw "Services started, but the readiness check failed. Choose 5 to open the logs." }
    if ($install) {
        @{ fingerprint = $fingerprint; project_root = $script:projectDirectory } |
            ConvertTo-Json | Set-Content -LiteralPath $script:setupFile -Encoding UTF8
    }
    Write-Host "Ready! $($running.frontend_url)" -ForegroundColor Green
    Show-SlackStatus -State $running -Root $script:projectDirectory
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

function Invoke-SlackCheck {
    $python = Join-Path $script:projectDirectory '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Start PeopleFlow once to prepare dependencies, then check Slack again.'
    }
    & $python -I -m peopleflow_slack --check
    if ($LASTEXITCODE -ne 0) { throw 'Slack connection check failed. Review the settings in the root .env.' }
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
    Write-Host "  7  Install Python / Node.js  8  Connect / configure Slack"
    Write-Host " 10  Check Slack connection"
    Write-Host "  0  Close this window (keep PeopleFlow running)"
    Write-Host "  9  Stop PeopleFlow and exit"
    Write-Host ""
}

function Show-PeopleFlowStatus {
    $running = Get-RunningDemo
    $state = Read-DemoProcessState -Path $script:stateFile
    if ($running) {
        Write-Host "RUNNING $($running.frontend_url)"
        Show-SlackStatus -State $running -Root $script:projectDirectory
        return $true
    }
    Write-Host 'NOT READY'
    if ($state -and $state.project_root -eq $script:projectDirectory) {
        foreach ($entry in Get-DemoProcessEntries -State $state | Where-Object { $_.name -in @('api', 'frontend') }) {
            $label = if (Get-OwnedDemoProcess -Entry $entry) { 'process running' } else { 'stopped' }
            Write-Host "$($entry.name): $label"
        }
        Show-SlackStatus -State $state -Root $script:projectDirectory
    } else {
        Write-Host 'Web and Slack: stopped.'
    }
    return $false
}

# Dot-sourcing exposes helpers for isolated tests without starting any services.
if ($MyInvocation.InvocationName -eq ".") { return }

try {
    $Host.UI.RawUI.WindowTitle = "PeopleFlow AI - Launcher"
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    Set-Location -LiteralPath $script:projectDirectory
    if ($Action -eq 'CheckSlack') { Invoke-SlackCheck; exit 0 }
    if ($Action -eq "Status") {
        if (Show-PeopleFlowStatus) { exit 0 }
        exit 1
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
                "8" {
                    Initialize-LocalConfiguration
                    $slackEnv = Join-Path $script:projectDirectory '.env'
                    Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $slackEnv + '"')
                    Write-Host 'Add the Slack tokens and workspace/member IDs from slack/README.md. Save, then choose 2.'
                    Write-Host 'Slack will start and stop with the web app. No separate terminal is needed.'
                }
                "9" { Stop-PeopleFlow; exit 0 }
                "10" { Invoke-SlackCheck }
                "0" { exit 0 }
                default { Write-Host "Enter one of the menu numbers." }
            }
        } catch { Show-LauncherError -Message $_.Exception.Message }
    }
} catch {
    Show-LauncherError -Message $_.Exception.Message
    exit 1
}
