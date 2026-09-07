# Shared Slack lifecycle helpers. Configuration results never contain credentials.
function Read-ProjectEnvironment {
    param([Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$PythonPath)
    if (-not (Test-Path -LiteralPath $Path)) { return @{} }
    # Keep the same parser and process-over-file precedence as the API and Slack.
    # The JSON is captured in memory only; never write it to the console or logs.
    $code = 'import json, os, sys; from dotenv import dotenv_values, load_dotenv; keys = dotenv_values(sys.argv[1], interpolate=False, encoding=''utf-8-sig''); load_dotenv(sys.argv[1], override=False, encoding=''utf-8-sig''); print(json.dumps({key: os.environ[key] for key in keys if key in os.environ}))'
    $serialized = & $PythonPath -I -c $code $Path
    if ($LASTEXITCODE -ne 0) { throw 'Could not load .env with the project Python. Reinstall dependencies and try again.' }
    $values = @{}
    $configuration = ($serialized -join "`n") | ConvertFrom-Json
    foreach ($property in $configuration.PSObject.Properties) {
        if ($property.Name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw 'The .env file contains an invalid environment variable name.'
        }
        $values[$property.Name] = [string]$property.Value
    }
    return $values
}

function Get-SlackConfiguration {
    param([Parameter(Mandatory = $true)][string]$Root, [string]$PythonPath = '')

    $required = @('SLACK_BOT_TOKEN', 'SLACK_APP_TOKEN', 'SLACK_TEAM_ID', 'SLACK_EMPLOYEE_USER_ID')
    $values = @{}
    if (-not $PythonPath) { $PythonPath = Join-Path $Root '.venv/Scripts/python.exe' }
    if (Test-Path -LiteralPath $PythonPath) {
        $values = Read-ProjectEnvironment -Path (Join-Path $Root '.env') -PythonPath $PythonPath
    }
    foreach ($key in $required) {
        $inherited = [Environment]::GetEnvironmentVariable($key, 'Process')
        if ($null -ne $inherited) { $values[$key] = $inherited }
    }
    $missing = @($required | Where-Object { [string]::IsNullOrWhiteSpace($values[$_]) })
    return [pscustomobject]@{
        configured = $missing.Count -eq 0
        partial = $missing.Count -gt 0 -and $missing.Count -lt $required.Count
        missing = $missing
    }
}

function Get-SlackServiceStatus {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][string]$Root)
    $entry = @(Get-DemoProcessEntries -State $State | Where-Object { $_.name -eq 'slack' })
    if ($entry.Count -ne 1) {
        if ($State.slack_status -eq 'not_configured') { return 'not_configured' }
        if ($State.slack_status -eq 'disabled') { return 'disabled' }
        if (-not (Get-SlackConfiguration -Root $Root).configured) { return 'not_configured' }
        return 'stopped'
    }
    if (-not (Get-OwnedDemoProcess -Entry $entry[0])) { return 'stopped' }
    $healthPath = Join-Path $Root '.demo_state/slack_health.json'
    try {
        $health = Get-Content -LiteralPath $healthPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $age = ([DateTimeOffset]::UtcNow - (ConvertTo-DemoTimestamp -Value $health.updated_at)).TotalSeconds
        if ([int]$health.pid -ne [int]$entry[0].pid -or $health.api_url -ne $State.api_url -or
            $age -lt -5 -or $age -gt 30) { return 'unresponsive' }
        if ($health.status -in @('starting', 'connected', 'disconnected', 'failed', 'stopped')) {
            return [string]$health.status
        }
    } catch { }
    return 'unresponsive'
}

function Wait-SlackReady {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][string]$Root,
        [int]$TimeoutSeconds = 60)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $status = Get-SlackServiceStatus -State $State -Root $Root
        if ($status -eq 'connected') { return $true }
        if ($status -in @('failed', 'stopped')) { return $false }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Show-SlackStatus {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][string]$Root)
    $status = Get-SlackServiceStatus -State $State -Root $Root
    switch ($status) {
        'connected' { Write-Host 'Slack: connected. Open PeopleFlow AI in Slack.' -ForegroundColor Green }
        'not_configured' { Write-Host 'Slack: not configured. Choose 8 to connect it; the web app is ready.' -ForegroundColor DarkCyan }
        'disabled' { Write-Host 'Slack: disabled for this launch.' -ForegroundColor DarkCyan }
        default { Write-Host "Slack: $status. Choose 2 to restart; details are in slack.err.log." -ForegroundColor Yellow }
    }
}
