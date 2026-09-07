function Read-DemoProcessState {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Cannot parse demo process state: $Path"
    }
}

function Enter-DemoLifecycleLock {
    param([Parameter(Mandatory = $true)][string]$Root)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($Root).ToLowerInvariant())
        $key = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '')
    } finally { $sha.Dispose() }
    $mutex = [Threading.Mutex]::new($false, "Local\PeopleFlow-Services-$key")
    try {
        try { $acquired = $mutex.WaitOne(0) }
        catch [Threading.AbandonedMutexException] { $acquired = $true }
        if (-not $acquired) { throw 'Another PeopleFlow start or stop is in progress. Try again when it finishes.' }
        return $mutex
    } catch {
        $mutex.Dispose()
        throw
    }
}

function Exit-DemoLifecycleLock {
    param([Parameter(Mandatory = $true)][Threading.Mutex]$Mutex)
    try { $Mutex.ReleaseMutex() } finally { $Mutex.Dispose() }
}

function Get-AvailableDemoPort {
    param([int]$Preferred)
    for ($candidate = $Preferred; $candidate -lt [Math]::Min($Preferred + 50, 65536); $candidate++) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $candidate)
        try {
            $listener.Server.ExclusiveAddressUse = $true
            $listener.Start()
            return $candidate
        } catch [Net.Sockets.SocketException] {
            # Never stop an unrelated process to claim its port.
        } finally { $listener.Stop() }
    }
    throw "No available port found near $Preferred. Close unused local servers and try again."
}

function Get-DemoProcessEntries {
    param([Parameter(Mandatory = $true)]$State)

    if (($State -is [Collections.IDictionary] -and $State.Contains('services')) -or
        $State.PSObject.Properties.Name -contains "services") {
        return @($State.services)
    }

    $entries = @()
    $legacyStartedAt = $State.started_at
    foreach ($definition in @(
        @{ Name = "api"; Property = "api_pid"; Marker = "app:app" },
        @{ Name = "frontend"; Property = "frontend_pid"; Marker = "vite" }
    )) {
        if (-not ($State.PSObject.Properties.Name -contains $definition.Property)) {
            continue
        }
        $value = [int]$State.($definition.Property)
        if ($value -le 0) {
            continue
        }
        $entries += [pscustomobject]@{
            name = $definition.Name
            pid = $value
            started_at = $legacyStartedAt
            executable = ""
            marker = $definition.Marker
            legacy = $true
        }
    }
    return $entries
}

function ConvertTo-DemoTimestamp {
    param([Parameter(Mandatory = $true)]$Value)
    # PowerShell 7 converts JSON dates to DateTime; 5.1 keeps ISO strings.
    # Casting a UTC DateTime to string first silently loses its timezone.
    if ($Value -is [DateTimeOffset]) { return $Value }
    if ($Value -is [DateTime]) { return [DateTimeOffset]$Value }
    return [DateTimeOffset]::Parse([string]$Value, [Globalization.CultureInfo]::InvariantCulture)
}

function Get-OwnedDemoProcess {
    param([Parameter(Mandatory = $true)]$Entry)

    $process = Get-Process -Id ([int]$Entry.pid) -ErrorAction SilentlyContinue
    if (-not $process) {
        return $null
    }

    try {
        $expectedStart = ConvertTo-DemoTimestamp -Value $Entry.started_at
        $actualStart = [DateTimeOffset]$process.StartTime.ToUniversalTime()
    } catch {
        return $null
    }
    $toleranceSeconds = if ($Entry.PSObject.Properties.Name -contains "legacy" -and $Entry.legacy) {
        45
    } else {
        2
    }
    if ([Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt $toleranceSeconds) {
        return $null
    }

    $expectedExecutable = [string]$Entry.executable
    if ($expectedExecutable) {
        try {
            if (-not [string]::Equals(
                [IO.Path]::GetFullPath($process.Path),
                [IO.Path]::GetFullPath($expectedExecutable),
                [StringComparison]::OrdinalIgnoreCase
            )) {
                return $null
            }
        } catch {
            return $null
        }
    }

    $marker = [string]$Entry.marker
    if ($marker) {
        $details = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)" -ErrorAction SilentlyContinue
        if (-not $details -or -not ([string]$details.CommandLine).Contains($marker)) {
            return $null
        }
    }
    return $process
}

function Stop-DemoProcesses {
    param([Parameter(Mandatory = $true)]$State)

    $stopped = @()
    $unverified = @()
    $seen = [Collections.Generic.HashSet[int]]::new()
    $services = @(Get-DemoProcessEntries -State $State)
    [array]::Reverse($services) # Disconnect Slack before stopping its API.
    $stopEntries = @()
    foreach ($service in $services) {
        $stopEntries += @(Get-DemoStopEntries -Entry $service)
    }
    foreach ($entry in $stopEntries) {
        $processId = [int]$entry.pid
        if (-not $seen.Add($processId)) {
            continue
        }
        $existing = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if (-not $existing) {
            continue
        }
        $owned = Get-OwnedDemoProcess -Entry $entry
        if (-not $owned) {
            # A Python redirector can exit by itself just after its worker was stopped.
            $existing.Refresh()
            if ($existing.HasExited) { continue }
            $unverified += $processId
            continue
        }
        Stop-Process -Id $owned.Id -Force -ErrorAction Stop
        $null = $owned.WaitForExit(5000)
        $stopped += $owned.Id
    }
    return [pscustomobject]@{
        stopped = $stopped
        unverified = $unverified
    }
}

function Get-DemoChildEntries {
    param([Parameter(Mandatory = $true)]$Entry)
    if (-not (Get-OwnedDemoProcess -Entry $Entry)) { return }
    foreach ($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($Entry.pid)" -ErrorAction SilentlyContinue)) {
        # Python venv redirectors keep the same module arguments in their real worker.
        # Never include unrelated descendants solely because of their parent PID.
        if (-not $Entry.marker -or -not ([string]$child.CommandLine).Contains([string]$Entry.marker)) { continue }
        $process = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        try {
            if ($process.StartTime.ToUniversalTime() -lt (ConvertTo-DemoTimestamp -Value $Entry.started_at).UtcDateTime) { continue }
            [pscustomobject]@{
                name = $Entry.name
                pid = $process.Id
                started_at = $process.StartTime.ToUniversalTime().ToString('o')
                executable = $process.Path
                marker = $Entry.marker
            }
        } catch { continue }
    }
}

function Get-DemoStopEntries {
    param([Parameter(Mandatory = $true)]$Entry)
    foreach ($child in @(Get-DemoChildEntries -Entry $Entry)) {
        Get-DemoStopEntries -Entry $child
    }
    $Entry
    if ($Entry.PSObject.Properties.Name -contains 'launcher' -and $Entry.launcher) {
        $Entry.launcher
    }
}

function New-DemoProcessEntry {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][string]$Marker
    )

    $current = Get-Process -Id $Process.Id -ErrorAction Stop
    $entry = [pscustomobject][ordered]@{
        name = $Name
        pid = $current.Id
        started_at = $current.StartTime.ToUniversalTime().ToString("o")
        executable = $current.Path
        marker = $Marker
    }
    if ($Name -in @('api', 'slack') -and [IO.Path]::GetFileName($current.Path) -eq 'python.exe') {
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            $children = @(Get-DemoChildEntries -Entry $entry)
            if ($children.Count -gt 0) {
                $worker = $children[0]
                $worker | Add-Member -MemberType NoteProperty -Name launcher -Value $entry
                return $worker
            }
            Start-Sleep -Milliseconds 100
        }
    }
    return $entry
}

function Write-DemoProcessState {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$State
    )

    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temporaryPath = Join-Path $directory "demo_processes.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        $State | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}
