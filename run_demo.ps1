param(
    [ValidateRange(1, 65535)][int]$ApiPort = 8000,
    [ValidateRange(1, 65535)][int]$UserUiPort = 5173,
    [switch]$InstallDeps,
    [switch]$SkipIndexRebuild,
    [switch]$ForceRestart,
    [switch]$OneClick,
    [switch]$NoBrowser,
    [switch]$NoWait
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$projectRoot = Split-Path -Parent $PSCommandPath
Set-Location -LiteralPath $projectRoot
. (Join-Path $projectRoot 'scripts/demo_processes.ps1')

function Start-DemoProcess {
    param([string]$Name, [string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory)
    $stdoutPath = Join-Path $logDirectory "$Name.out.log"
    $stderrPath = Join-Path $logDirectory "$Name.err.log"
    foreach ($path in @($stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
    Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru
}

$apiProc = $null
$frontendProc = $null
$operationLock = $null
$startupComplete = $false
try {
    $operationLock = Enter-DemoOperationLock -ProjectRoot $projectRoot
    $apiBaseUrl = "http://127.0.0.1:$ApiPort"
    $userUiUrl = "http://127.0.0.1:$UserUiPort"
    $logDirectory = Join-Path $projectRoot '.demo_logs'
    $stateDirectory = Join-Path $projectRoot '.demo_state'
    $pidFile = Join-Path $stateDirectory 'demo_processes.json'

    $runningProcesses = @(Get-DemoProcesses -PidFile $pidFile)
    if ($runningProcesses.Count -gt 0) {
        if (-not $ForceRestart) {
            if ($runningProcesses.Count -ne 2) { throw 'Only one demo server is running. Run start.bat -ForceRestart to recover.' }
            $meta = Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
            Wait-DemoHttp -Url "$($meta.api_url)/api/v1/health" -Process $runningProcesses[0]
            Wait-DemoHttp -Url $meta.user_ui_url -Process $runningProcesses[1]
            Write-Host "Demo is already running: $($meta.user_ui_url)/employee"
            if ($OneClick -and -not $NoBrowser) { Start-Process -FilePath "$($meta.user_ui_url)/employee" }
            return
        }
        foreach ($process in $runningProcesses) { Stop-DemoProcess -Process $process }
    }
    if ($ApiPort -eq $UserUiPort) { throw 'API and UI must use different ports.' }
    Assert-DemoPortAvailable -Port $ApiPort
    Assert-DemoPortAvailable -Port $UserUiPort

    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $nodeCommand -or -not $npmCommand) {
        throw 'Node.js and npm are missing. Install Node.js 22.12+ (or 24 LTS) from https://nodejs.org, then reopen start.bat.'
    }
    & $nodeCommand.Source -e "const [a,b]=process.versions.node.split('.').map(Number); process.exit(a>22 || (a===22 && b>=12) ? 0 : 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Node.js. Install Node.js 22.12+ (or 24 LTS), then reopen start.bat.' }

    $python = Join-Path $projectRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
        $pythonArgs = @('-3')
        if (-not $pythonCommand) {
            $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
            $pythonArgs = @()
        }
        if (-not $pythonCommand) {
            throw 'Python is missing. Install Python 3.10+ from https://python.org with Add Python to PATH, then reopen start.bat.'
        }
        & $pythonCommand.Source @pythonArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ is required. Install Python with Add Python to PATH, then reopen start.bat.' }
        Write-Host 'Creating a local Python environment...'
        & $pythonCommand.Source @pythonArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create .venv. Check Python installation and write access to the project folder.' }
    }
    & $python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'The existing .venv is unusable. Recreate it using Python 3.10+; keep .env and your data.' }
    & $python -m scripts.demo_setup check-deps
    $pythonNeedsInstall = $LASTEXITCODE -ne 0
    if (-not $pythonNeedsInstall) {
        & $python -m pip check | Out-Null
        $pythonNeedsInstall = $LASTEXITCODE -ne 0
    }
    if ($InstallDeps -or $pythonNeedsInstall) {
        Write-Host 'Installing Python dependencies (internet required on first launch)...'
        & $python -m pip install --disable-pip-version-check -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed. Check internet/proxy access to PyPI and retry start.bat.' }
        & $python -m scripts.demo_setup check-deps
        if ($LASTEXITCODE -ne 0) { throw 'Python packages are still unusable. Recreate .venv and retry; keep .env and your data.' }
        & $python -m pip check
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency conflict. Recreate .venv and retry; keep .env and your data.' }
    }

    New-Item -ItemType Directory -Force -Path $logDirectory, $stateDirectory | Out-Null
    $frontendDirectory = Join-Path $projectRoot 'frontend'
    $stampFile = Join-Path $stateDirectory 'frontend-dependencies.txt'
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $lockBytes = [System.IO.File]::ReadAllBytes((Join-Path $frontendDirectory 'package-lock.json'))
        $lockHash = [System.BitConverter]::ToString($hasher.ComputeHash($lockBytes)).Replace('-', '')
    } finally { $hasher.Dispose() }
    $nodeVersion = & $nodeCommand.Source -p "process.version + ':' + process.arch"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot determine Node.js version.' }
    $expectedStamp = "$lockHash/$nodeVersion"
    $stamp = if (Test-Path -LiteralPath $stampFile) { (Get-Content -LiteralPath $stampFile -Raw).Trim() } else { '' }
    Push-Location -LiteralPath $frontendDirectory
    try {
        $frontendNeedsInstall = $InstallDeps -or ($stamp -ne $expectedStamp)
        if (-not $frontendNeedsInstall) {
            $ErrorActionPreference = 'Continue'
            try {
                & $npmCommand.Source ls --depth=0 --json 2>$null | Out-Null
                $frontendNeedsInstall = $LASTEXITCODE -ne 0
            } finally { $ErrorActionPreference = 'Stop' }
        }
        if (-not $frontendNeedsInstall) {
            & $nodeCommand.Source --input-type=module -e "try { await import('vite'); await import('@tailwindcss/vite'); await import('@vitejs/plugin-react') } catch { process.exit(1) }"
            $frontendNeedsInstall = $LASTEXITCODE -ne 0
        }
        if ($frontendNeedsInstall) {
            Assert-DemoFrontendDependenciesUnlocked -FrontendDirectory $frontendDirectory
            Write-Host 'Installing frontend dependencies (internet required on first launch)...'
            & $npmCommand.Source ci --include=dev --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed. For EPERM/EBUSY, close this project''s development/preview servers and retry start.bat. For download errors, check internet/proxy access to npm. Keep .env and your data.' }
            & $nodeCommand.Source --input-type=module -e "await import('vite'); await import('@tailwindcss/vite'); await import('@vitejs/plugin-react')"
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies are unusable. Check the Node.js version and retry start.bat -InstallDeps.' }
            Set-Content -LiteralPath $stampFile -Value $expectedStamp -Encoding ASCII
        }
    } finally { Pop-Location }

    if ($env:PYTHON_DOTENV_DISABLED -ne '1') {
        $configurationJson = & $python -m scripts.demo_setup configure --json
        if ($LASTEXITCODE -ne 0) { throw 'Configuration failed. See the message above; no server was started.' }
        $configuration = $configurationJson | ConvertFrom-Json
        foreach ($property in $configuration.PSObject.Properties) {
            [Environment]::SetEnvironmentVariable($property.Name, [string]$property.Value, 'Process')
        }
        $configurationJson = $null
        $configuration = $null
    }
    & $python -c 'from core.settings import validate_auth_settings; validate_auth_settings()'
    if ($LASTEXITCODE -ne 0) { throw 'Authentication is not configured. Check DEMO_LOGIN_PASSWORD and DEMO_AUTH_SECRET in .env.' }
    $env:VITE_API_URL = $apiBaseUrl
    $env:APP_LAUNCH_URL = $userUiUrl
    $env:PYTHONUNBUFFERED = '1'
    if (-not $env:CORS_ORIGINS) { $env:CORS_ORIGINS = "$userUiUrl,http://localhost:$UserUiPort" }

    $apiProc = Start-DemoProcess -Name 'api' -FilePath $python -WorkingDirectory $projectRoot `
        -ArgumentList @('-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', "$ApiPort", '--no-proxy-headers')
    $frontendProc = Start-DemoProcess -Name 'frontend' -FilePath $nodeCommand.Source -WorkingDirectory $frontendDirectory `
        -ArgumentList @('node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', "$UserUiPort", '--strictPort')
    Wait-DemoHttp -Url "$apiBaseUrl/api/v1/health" -Process $apiProc
    Wait-DemoHttp -Url $userUiUrl -Process $frontendProc

    $indexExists = & $python -c 'from core.settings import INDEX_PATH; print(int(INDEX_PATH.exists()))'
    if (-not $SkipIndexRebuild -and $indexExists -eq '0') {
        try {
            $loginBody = @{ username = 'knowledge_admin'; password = $env:DEMO_LOGIN_PASSWORD } | ConvertTo-Json
            $login = Invoke-RestMethod -Uri "$apiBaseUrl/api/v1/auth/login" -Method Post -ContentType 'application/json' -Body $loginBody -TimeoutSec 10
            $headers = @{ Authorization = "Bearer $($login.access_token)" }
            $documents = Invoke-RestMethod -Uri "$apiBaseUrl/api/v1/documents" -Headers $headers -TimeoutSec 10
            if ($documents.documents.Count -gt 0) {
                $documentId = $documents.documents[0].id
                Invoke-RestMethod -Uri "$apiBaseUrl/api/v1/documents/$documentId/index" -Method Post -Headers $headers -TimeoutSec 180 | Out-Null
                Write-Host 'Initial document index created.'
            }
        } catch { Write-Warning 'Initial indexing failed. The app is running; retry Index as Knowledge Admin. See .demo_logs.' }
    }
    $meta = [ordered]@{
        processes = @($apiProc, $frontendProc) | ForEach-Object {
            @{ id = $_.Id; started_at = $_.StartTime.ToUniversalTime().ToString('o') }
        }
        api_url = $apiBaseUrl
        user_ui_url = $userUiUrl
        logs_dir = $logDirectory
    }
    $meta | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $pidFile -Encoding UTF8
    $startupComplete = $true
    Exit-DemoOperationLock -Lock $operationLock
    $operationLock = $null
    Write-Host "`nDemo services started."
    Write-Host "Employee:        $userUiUrl/employee"
    Write-Host "Manager:         $userUiUrl/manager"
    Write-Host "Knowledge Admin: $userUiUrl/knowledge"
    Write-Host "API:             $apiBaseUrl"
    Write-Host 'Login: employee / manager / knowledge_admin. Password: DEMO_LOGIN_PASSWORD in .env.'
    if (-not $env:OPENAI_API_KEY) { Write-Host 'OpenAI key is empty: local search and request workflows are available.' }
    Write-Host "Logs: $logDirectory"
    if ($OneClick -and -not $NoBrowser) {
        try { Start-Process -FilePath "$userUiUrl/employee" }
        catch { Write-Warning "Cannot open browser automatically. Open $userUiUrl/employee" }
    }
    if ($OneClick -and -not $NoWait) {
        try { Read-Host 'Keep this window open. Press Enter to stop the demo' | Out-Null }
        finally {
            $operationLock = Enter-DemoOperationLock -ProjectRoot $projectRoot
            foreach ($process in @($apiProc, $frontendProc)) { Stop-DemoProcess -Process $process }
            Remove-DemoProcessRecord -PidFile $pidFile -ExpectedRecords $meta.processes
        }
    } else { Write-Host 'To stop: double-click stop.bat.' }
} catch {
    if (-not $startupComplete) {
        foreach ($process in @($apiProc, $frontendProc)) {
            if ($process) { Stop-DemoProcess -Process $process }
        }
    }
    Write-Host "`nERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($OneClick -and -not $NoWait) { Read-Host 'Press Enter to close' | Out-Null }
    exit 1
} finally {
    Exit-DemoOperationLock -Lock $operationLock
}
