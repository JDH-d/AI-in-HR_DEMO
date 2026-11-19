function Enter-DemoOperationLock {
    param([string]$ProjectRoot)
    $canonicalPath = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\').ToUpperInvariant()
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($canonicalPath)
        $key = [System.BitConverter]::ToString($hasher.ComputeHash($bytes)).Replace('-', '')
    } finally { $hasher.Dispose() }
    $mutex = [System.Threading.Mutex]::new($false, "Local\PeopleFlowDemo-$key")
    try {
        try { $acquired = $mutex.WaitOne(0) }
        catch [System.Threading.AbandonedMutexException] { $acquired = $true }
        if (-not $acquired) {
            throw 'Another start/stop is in progress for this project. Wait for it to finish, then reopen start.bat.'
        }
        return $mutex
    } catch {
        $mutex.Dispose()
        throw
    }
}

function Exit-DemoOperationLock {
    param([System.Threading.Mutex]$Lock)
    if ($Lock) {
        try { $Lock.ReleaseMutex() }
        finally { $Lock.Dispose() }
    }
}

function Remove-DemoProcessRecord {
    param([string]$PidFile, [object[]]$ExpectedRecords)
    if (-not (Test-Path -LiteralPath $PidFile)) { return }
    $current = Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($current.processes.Count -ne $ExpectedRecords.Count) { return }
    foreach ($record in $current.processes) {
        $match = @($ExpectedRecords | Where-Object {
            $_.id -eq $record.id -and ([datetime]$_.started_at) -eq ([datetime]$record.started_at)
        })
        if ($match.Count -ne 1) { return }
    }
    Remove-Item -LiteralPath $PidFile -Force
}

function Get-DemoProcesses {
    param([string]$PidFile)
    if (-not (Test-Path -LiteralPath $PidFile)) { return @() }
    $meta = Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $meta.processes) {
        throw "Legacy PID file found. Stop the old servers in their terminals, then remove $PidFile."
    }
    foreach ($item in $meta.processes) {
        $process = Get-Process -Id $item.id -ErrorAction SilentlyContinue
        $recordedStart = ([datetime]$item.started_at).ToUniversalTime()
        if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq $recordedStart.Ticks) {
            $process
        }
    }
}

function Wait-DemoHttp {
    param([string]$Url, [System.Diagnostics.Process]$Process, [int]$TimeoutSeconds = 45)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) { throw "Server exited before becoming ready: $Url. Check .demo_logs." }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw "Server did not become ready: $Url. Check .demo_logs."
}

function Stop-DemoProcess {
    param([System.Diagnostics.Process]$Process)
    $current = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
    if ($current -and $current.StartTime -eq $Process.StartTime) {
        # Windows venv launchers can spawn a child Python process. Stop the owned tree.
        & taskkill.exe /PID $current.Id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not stop demo process $($current.Id)." }
    }
}

function Assert-DemoPortAvailable {
    param([int]$Port)
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Server.ExclusiveAddressUse = $true
    try { $listener.Start() }
    catch { throw "Port $Port is already in use. Stop its server or choose another port." }
    finally { $listener.Stop() }
}

function Assert-DemoFrontendDependenciesUnlocked {
    param([string]$FrontendDirectory)
    $modulesDirectory = Join-Path $FrontendDirectory 'node_modules'
    if (-not (Test-Path -LiteralPath $modulesDirectory)) { return }
    # A Vite preview on another port can hold a native module even when it is not
    # listed in our PID file. Detect this before npm ci removes any packages.
    foreach ($module in (Get-ChildItem -LiteralPath $modulesDirectory -Filter '*.node' -File -Recurse -Force)) {
        $probe = $null
        try {
            $probe = [System.IO.File]::Open($module.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        } catch [System.IO.IOException] {
            throw "Frontend dependency $($module.Name) is locked or inaccessible. Close this project's development/preview servers (including other ports), then retry start.bat. No frontend packages were changed by this attempt."
        } catch [System.UnauthorizedAccessException] {
            throw "Frontend dependency $($module.Name) is not writable. Check access to frontend/node_modules and close this project's development/preview servers, then retry start.bat. No frontend packages were changed by this attempt."
        } finally {
            if ($probe) { $probe.Dispose() }
        }
    }
}
