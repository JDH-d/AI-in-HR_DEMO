param()

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSCommandPath))
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Run .\run_demo.ps1 -InstallDeps first."
}

$stateDirectory = [IO.Path]::GetFullPath((Join-Path $projectRoot ".demo_state"))
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null
$temporaryDirectory = [IO.Path]::GetFullPath(
    (Join-Path $stateDirectory "smoke-$([Guid]::NewGuid().ToString('N'))")
)
if ([IO.Path]::GetDirectoryName($temporaryDirectory) -ne $stateDirectory) {
    throw "Smoke directory escaped the expected state directory."
}
New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null

$smokeEnvironmentNames = @(
    "WORKFLOW_DB",
    "CONVERSATION_DB",
    "LOG_PATH",
    "INDEX_PATH",
    "INDEX_STATUS_PATH",
    "AI_SETTINGS_PATH",
    "DEMO_AUTH_SECRET",
    "DEMO_LOGIN_PASSWORD",
    "OPENAI_API_KEY",
    "PYTHONUNBUFFERED",
    "PYTHONDONTWRITEBYTECODE"
)
$smokeEnvironmentSnapshot = @{}
foreach ($name in $smokeEnvironmentNames) {
    $smokeEnvironmentSnapshot[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

function Assert-NativeSuccess {
    param([string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Get-DemoToken {
    param([string]$BaseUrl, [string]$Username)

    $body = @{
        username = $Username
        password = $env:DEMO_LOGIN_PASSWORD
    } | ConvertTo-Json
    $login = Invoke-RestMethod `
        -Uri "$BaseUrl/api/v1/auth/login" `
        -Method Post `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 10
    return $login.access_token
}

function Get-FreeTcpPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
    }
}

$apiProcess = $null
try {
    $env:WORKFLOW_DB = Join-Path $temporaryDirectory "workflow.db"
    $env:CONVERSATION_DB = Join-Path $temporaryDirectory "conversations.db"
    $env:LOG_PATH = Join-Path $temporaryDirectory "chat_logs.jsonl"
    $env:INDEX_PATH = Join-Path $temporaryDirectory "index.json"
    $env:INDEX_STATUS_PATH = Join-Path $temporaryDirectory "index_status.json"
    $env:AI_SETTINGS_PATH = Join-Path $temporaryDirectory "ai_settings.json"
    $env:DEMO_AUTH_SECRET = "peopleflow-smoke-secret"
    $env:DEMO_LOGIN_PASSWORD = "smoke-demo-password"
    $env:OPENAI_API_KEY = "your_openai_api_key"
    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"

    & $python -m ruff check $projectRoot
    Assert-NativeSuccess "Backend lint"
    & $python -m ruff format --check $projectRoot
    Assert-NativeSuccess "Backend format check"
    & $python -m pytest -q -p no:cacheprovider
    Assert-NativeSuccess "Backend tests"
    & $python -m scripts.run_rag_eval
    Assert-NativeSuccess "Deterministic RAG evaluation"

    $frontendDirectory = Join-Path $projectRoot "frontend"
    & npm --prefix $frontendDirectory run check
    Assert-NativeSuccess "Frontend lint and format check"
    & npm --prefix $frontendDirectory test -- --run
    Assert-NativeSuccess "Frontend tests"
    & npm --prefix $frontendDirectory run build
    Assert-NativeSuccess "Frontend production build"

    $port = Get-FreeTcpPort
    $baseUrl = "http://127.0.0.1:$port"
    $apiProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "$port") `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput (Join-Path $temporaryDirectory "api.out.log") `
        -RedirectStandardError (Join-Path $temporaryDirectory "api.err.log") `
        -WindowStyle Hidden `
        -PassThru

    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $apiProcess.Refresh()
        if ($apiProcess.HasExited) {
            break
        }
        try {
            $health = Invoke-RestMethod -Uri "$baseUrl/api/v1/health" -Method Get -TimeoutSec 2
            if ($health.status -eq "ok" -and $health.api_version -eq "v1") {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) {
        throw "API v1 did not become healthy on the isolated smoke port."
    }

    $unauthorizedStatus = $null
    try {
        Invoke-WebRequest -Uri "$baseUrl/api/v1/me" -Method Get -TimeoutSec 10 | Out-Null
    } catch {
        $unauthorizedStatus = $_.Exception.Response.StatusCode.value__
    }
    if ($unauthorizedStatus -ne 401) {
        throw "Protected API route returned unexpected status without auth: $unauthorizedStatus"
    }

    $employeeHeaders = @{ Authorization = "Bearer $(Get-DemoToken $baseUrl 'employee')" }
    $managerHeaders = @{ Authorization = "Bearer $(Get-DemoToken $baseUrl 'manager')" }
    $adminHeaders = @{ Authorization = "Bearer $(Get-DemoToken $baseUrl 'knowledge_admin')" }

    $chatBody = @{
        messages = @(@{ role = "user"; content = "What can you help with?" })
    } | ConvertTo-Json -Depth 5
    $chat = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/chat" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $employeeHeaders `
        -Body $chatBody `
        -TimeoutSec 15
    if ($chat.intent -ne "view_capabilities" -or -not $chat.conversation_id) {
        throw "Capability chat did not create a persisted conversation."
    }
    $history = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/conversations/$($chat.conversation_id)" `
        -Method Get `
        -Headers $employeeHeaders `
        -TimeoutSec 10
    if ($history.messages.Count -ne 2 -or $history.messages[0].role -ne "user") {
        throw "Conversation history did not restore the completed exchange."
    }

    $stream = Invoke-WebRequest `
        -Uri "$baseUrl/api/v1/chat/stream" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $employeeHeaders `
        -Body $chatBody `
        -TimeoutSec 30
    $streamText = if ($stream.Content -is [byte[]]) {
        [Text.Encoding]::UTF8.GetString($stream.Content)
    } elseif ($stream.Content -is [string]) {
        $stream.Content
    } else {
        @($stream.Content) -join "`n"
    }
    $streamEvents = @(
        $streamText -split "`r?`n" |
            Where-Object { $_.Trim() } |
            ForEach-Object { $_ | ConvertFrom-Json }
    )
    $tokenEvents = @($streamEvents | Where-Object { $_.type -eq "token" })
    $completeEvents = @($streamEvents | Where-Object { $_.type -eq "complete" })
    if ($tokenEvents.Count -eq 0 -or $completeEvents.Count -ne 1) {
        throw "Chat stream did not emit token and completion events."
    }
    if (-not $completeEvents[0].outcome_code) {
        throw "Chat stream completion did not include an outcome code."
    }

    $ptoBody = @{
        messages = @(@{
            role = "user"
            content = "I need vacation from 2030-04-01 to 2030-04-03"
        })
    } | ConvertTo-Json -Depth 5
    $ptoDraft = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/chat" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $employeeHeaders `
        -Body $ptoBody `
        -TimeoutSec 15
    $ptoId = $ptoDraft.workflow_request.id
    $ptoSubmitted = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/requests/$ptoId/submit" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $employeeHeaders `
        -Body "{}" `
        -TimeoutSec 10
    $ptoApproved = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/requests/$ptoId/approve" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $managerHeaders `
        -Body '{"comment":"Smoke approval"}' `
        -TimeoutSec 10
    if ($ptoSubmitted.request.status -ne "in_review" -or $ptoApproved.request.status -ne "approved") {
        throw "PTO lifecycle did not reach approved."
    }

    $sickBody = @{
        type = "sick_leave"
        start_date = "2030-04-05"
        comment = "Coverage note"
        details = @{
            expected_return_date = "2030-04-06"
            expected_return_unknown = $false
            time_away = "full_day"
            partial_hours = $null
            extended_or_recurring = $false
        }
    } | ConvertTo-Json -Depth 5
    $sickDraft = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/requests" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $employeeHeaders `
        -Body $sickBody `
        -TimeoutSec 10
    $sickId = $sickDraft.request.id
    $sickReported = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/requests/$sickId/submit" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $employeeHeaders `
        -Body $sickBody `
        -TimeoutSec 10
    $sickAcknowledged = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/requests/$sickId/acknowledge" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $managerHeaders `
        -Body "{}" `
        -TimeoutSec 10
    if (
        $sickReported.request.status -ne "reported" -or
        $sickAcknowledged.request.status -ne "acknowledged"
    ) {
        throw "Sick-leave lifecycle did not reach acknowledged."
    }

    $documents = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/documents" `
        -Method Get `
        -Headers $adminHeaders `
        -TimeoutSec 10
    if (-not $documents.documents -or -not $documents.documents[0].id) {
        throw "Document API did not return stable document IDs."
    }
    $indexResult = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/documents/index" `
        -Method Post `
        -Headers $adminHeaders `
        -TimeoutSec 180
    if ($indexResult.scope -ne "all_documents" -or $indexResult.index.mode -notin @("embedding", "lexical")) {
        throw "Global knowledge index rebuild returned an invalid result."
    }

    $metrics = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/admin/metrics" `
        -Method Get `
        -Headers $adminHeaders `
        -TimeoutSec 10
    if (
        $metrics.metrics.total_requests -ne 2 -or
        $metrics.metrics.requests_by_status.approved -ne 1 -or
        $metrics.metrics.requests_by_status.acknowledged -ne 1 -or
        $metrics.metrics.questions -lt 3
    ) {
        throw "Knowledge metrics did not reflect the smoke scenarios."
    }

    Write-Output "Smoke check passed: tooling, history, streaming, PTO, sick leave, documents, and metrics."
} finally {
    foreach ($name in $smokeEnvironmentNames) {
        [Environment]::SetEnvironmentVariable(
            $name,
            $smokeEnvironmentSnapshot[$name],
            "Process"
        )
    }
    if ($apiProcess) {
        try {
            $apiProcess.Refresh()
            if (-not $apiProcess.HasExited) {
                Stop-Process -InputObject $apiProcess -Force -ErrorAction SilentlyContinue
            }
        } catch {
            Write-Warning "The isolated smoke API process could not be inspected during cleanup."
        }
    }
    if (
        (Test-Path -LiteralPath $temporaryDirectory) -and
        [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($temporaryDirectory)) -eq $stateDirectory
    ) {
        Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
    }
}
