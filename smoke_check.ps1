$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$tmpDir = Join-Path $root ".tmp_smoke"
$env:WORKFLOW_DB = Join-Path $tmpDir "workflow.db"
$env:LOG_PATH = Join-Path $tmpDir "chat_logs.jsonl"
$env:INDEX_PATH = Join-Path $tmpDir "index.json"
$env:SYSTEM_PROMPT_PATH = Join-Path $tmpDir "system_prompt.txt"
$env:DEMO_AUTH_SECRET = "stage-three-smoke-secret"
$env:DEMO_LOGIN_PASSWORD = "smoke-demo-password"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

if (Test-Path $tmpDir) {
    Remove-Item $tmpDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

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
    python -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed."
    }

    python -m scripts.run_rag_eval
    if ($LASTEXITCODE -ne 0) {
        throw "RAG evaluation failed."
    }

    Push-Location (Join-Path $root "frontend")
    npm test
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend tests failed."
    }
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend production build failed."
    }
    Pop-Location

    $proc = Start-Process -FilePath python -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8011") -WorkingDirectory $root -PassThru -WindowStyle Hidden
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
        Invoke-WebRequest -Uri "$baseUrl/api/v1/me" -Method Get -TimeoutSec 10 | Out-Null
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
    $reviewRequest = Invoke-RestMethod -Uri "$baseUrl/api/v1/requests/$requestId/submit" -Method Post -ContentType "application/json" -Headers $employeeHeaders -Body "{}" -TimeoutSec 10
    if ($reviewRequest.request.status -ne "in_review") {
        throw "Workflow submit route did not submit the draft."
    }

    $approved = Invoke-RestMethod -Uri "$baseUrl/api/v1/requests/$requestId/approve" -Method Post -ContentType "application/json" -Headers $managerHeaders -Body '{"comment":"Smoke approval"}' -TimeoutSec 10
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
        Stop-Process -Id $proc.Id -Force
    }
    Pop-Location
    if (Test-Path $tmpDir) {
        Remove-Item $tmpDir -Recurse -Force
    }
}
