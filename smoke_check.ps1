param([switch]$SkipChecks)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root "scripts/demo_processes.ps1")
$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Install requirements-dev.txt into .venv first." }
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("peopleflow-smoke-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmpDir | Out-Null
$env:WORKFLOW_DB = Join-Path $tmpDir "workflow.db"
$env:LOG_PATH = Join-Path $tmpDir "chat_logs.jsonl"
$env:INDEX_PATH = Join-Path $tmpDir "index.json"
$env:SYSTEM_PROMPT_PATH = Join-Path $tmpDir "system_prompt.txt"
$env:DEMO_AUTH_SECRET = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
$env:DEMO_LOGIN_PASSWORD = [guid]::NewGuid().ToString("N")
$env:OPENAI_API_KEY = ""
$env:PYTHON_DOTENV_DISABLED = "1"
$env:AI_SETTINGS_PATH = Join-Path $tmpDir "ai_settings.json"
$env:INDEX_STATUS_PATH = Join-Path $tmpDir "index_status.json"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

function Get-DemoToken {
    param(
        [string]$BaseUrl,
        [string]$Username
    )
    $body = @{
        username = $Username
        password = $env:DEMO_LOGIN_PASSWORD
    } | ConvertTo-Json
    $login = Invoke-RestMethod -Uri "$BaseUrl/api/v1/auth/login" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 10
    return $login.access_token
}

Push-Location $root
$proc = $null

try {
    if (-not $SkipChecks) {
    & $python -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed."
    }

    & $python -m scripts.run_rag_eval
    if ($LASTEXITCODE -ne 0) {
        throw "RAG evaluation failed."
    }

    Push-Location (Join-Path $root "frontend")
    try {
    npm.cmd test
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend tests failed."
    }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend production build failed."
    }
    } finally { Pop-Location }

    }
    Assert-DemoPortAvailable -Port 8011
    $proc = Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8011", "--no-proxy-headers") -WorkingDirectory $root -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $tmpDir "api.out.log") -RedirectStandardError (Join-Path $tmpDir "api.err.log")
    $baseUrl = "http://127.0.0.1:8011"

    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
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
        throw "API v1 did not become healthy on port 8011."
    }

    $unauthorized = $null
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/api/v1/me" -Method Get -TimeoutSec 10 | Out-Null
    } catch {
        $unauthorized = $_.Exception.Response.StatusCode.value__
    }
    if ($unauthorized -ne 401) {
        throw "Protected v1 route returned unexpected status without auth: $unauthorized"
    }

    $employeeToken = Get-DemoToken -BaseUrl $baseUrl -Username "employee"
    $managerToken = Get-DemoToken -BaseUrl $baseUrl -Username "manager"
    $adminToken = Get-DemoToken -BaseUrl $baseUrl -Username "knowledge_admin"
    $employeeHeaders = @{ "Authorization" = "Bearer $employeeToken" }
    $managerHeaders = @{ "Authorization" = "Bearer $managerToken" }
    $adminHeaders = @{ "Authorization" = "Bearer $adminToken" }

    $me = Invoke-RestMethod -Uri "$baseUrl/api/v1/me" -Method Get -Headers $employeeHeaders -TimeoutSec 10
    if ($me.user.id -ne "employee.demo" -or $me.user.role -ne "employee") {
        throw "Demo identity did not resolve to the predefined employee."
    }

    $capabilitiesBody = @{
        messages = @(@{ role = "user"; content = "What can you help with?" })
    } | ConvertTo-Json -Depth 5
    $capabilities = Invoke-RestMethod -Uri "$baseUrl/api/v1/chat" -Method Post -ContentType "application/json" -Headers $employeeHeaders -Body $capabilitiesBody -TimeoutSec 10
    if ($capabilities.intent -ne "view_capabilities") {
        throw "Capabilities flow returned unexpected intent: $($capabilities.intent)"
    }

    $workflowBody = @{
        messages = @(@{
            role = "user"
            content = "I need vacation from 2030-04-01 to 2030-04-03"
        })
    } | ConvertTo-Json -Depth 5
    $workflow = Invoke-RestMethod -Uri "$baseUrl/api/v1/chat" -Method Post -ContentType "application/json" -Headers $employeeHeaders -Body $workflowBody -TimeoutSec 10
    if ($workflow.workflow_request.status -ne "draft") {
        throw "Workflow chat flow did not create a draft."
    }

    $requestId = $workflow.workflow_request.id
    $reviewRequest = Invoke-RestMethod -Uri "$baseUrl/api/v1/requests/$requestId/submit" -Method Post -ContentType "application/json" -Headers $employeeHeaders -Body (@{expected_revision = $workflow.workflow_request.revision} | ConvertTo-Json) -TimeoutSec 10
    if ($reviewRequest.request.status -ne "submitted") {
        throw "Workflow submit route did not submit the draft."
    }

    $review = Invoke-RestMethod -Uri "$baseUrl/api/v1/requests/$requestId/actions/start_review" -Method Post -ContentType "application/json" -Headers $managerHeaders -Body (@{expected_revision = $reviewRequest.request.revision} | ConvertTo-Json) -TimeoutSec 10
    $decisionBody = @{expected_revision = $review.request.revision; comment = "Smoke approval"; basis = "Demo leave policy"; fair_review_confirmed = $true} | ConvertTo-Json
    $approved = Invoke-RestMethod -Uri "$baseUrl/api/v1/requests/$requestId/actions/approve" -Method Post -ContentType "application/json" -Headers $managerHeaders -Body $decisionBody -TimeoutSec 10
    if ($approved.request.status -ne "approved") {
        throw "Manager approval route did not approve the request."
    }

    $metrics = Invoke-RestMethod -Uri "$baseUrl/api/v1/admin/metrics" -Method Get -Headers $adminHeaders -TimeoutSec 10
    if ($metrics.metrics.total_requests -ne 1 -or $metrics.metrics.requests_by_status.approved -ne 1) {
        throw "Knowledge Admin metrics did not report the approved request."
    }

    $documents = Invoke-RestMethod -Uri "$baseUrl/api/v1/documents" -Method Get -Headers $adminHeaders -TimeoutSec 10
    if (-not $documents.documents -or -not $documents.documents[0].id) {
        throw "Versioned document contract did not return document IDs."
    }

    Write-Output "Smoke check passed."
} finally {
    if ($proc -and (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
        Stop-DemoProcess -Process $proc
    }
    Pop-Location
    if (Test-Path $tmpDir) {
        $resolvedSmoke = (Resolve-Path -LiteralPath $tmpDir).Path
        $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if (-not $resolvedSmoke.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not ([System.IO.Path]::GetFileName($resolvedSmoke)).StartsWith("peopleflow-smoke-")) {
            throw "Unexpected smoke cleanup path."
        }
        Remove-Item -LiteralPath $resolvedSmoke -Recurse -Force
    }
}
