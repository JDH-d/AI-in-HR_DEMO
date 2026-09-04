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

function Get-DemoProcessEntries {
    param([Parameter(Mandatory = $true)]$State)

    if ($State.PSObject.Properties.Name -contains "services") {
        return @($State.services)
    }

    $entries = @()
    $legacyStartedAt = [string]$State.started_at
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

function Get-OwnedDemoProcess {
    param([Parameter(Mandatory = $true)]$Entry)

    $process = Get-Process -Id ([int]$Entry.pid) -ErrorAction SilentlyContinue
    if (-not $process) {
        return $null
    }

    try {
        $expectedStart = [DateTimeOffset]::Parse([string]$Entry.started_at)
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
    foreach ($entry in Get-DemoProcessEntries -State $State) {
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
            $unverified += $processId
            continue
        }
        Stop-Process -Id $owned.Id -Force -ErrorAction Stop
        $stopped += $owned.Id
    }
    return [pscustomobject]@{
        stopped = $stopped
        unverified = $unverified
    }
}

function New-DemoProcessEntry {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][string]$Marker
    )

    $current = Get-Process -Id $Process.Id -ErrorAction Stop
    return [ordered]@{
        name = $Name
        pid = $current.Id
        started_at = $current.StartTime.ToUniversalTime().ToString("o")
        executable = $current.Path
        marker = $Marker
    }
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
