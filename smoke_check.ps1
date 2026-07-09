$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$tmpDir = Join-Path $root ".tmp_smoke"
$env:WORKFLOW_DB = Join-Path $tmpDir "workflow.db"
$env:LOG_PATH = Join-Path $tmpDir "chat_logs.jsonl"
$env:INDEX_PATH = Join-Path $tmpDir "index.json"
$env:SYSTEM_PROMPT_PATH = Join-Path $tmpDir "system_prompt.txt"
$env:ADMIN_TOKEN = "demo-admin-token"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

if (Test-Path $tmpDir) {
    Remove-Item $tmpDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

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

    $proc = Start-Process -FilePath python -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8011") -WorkingDirectory $root -PassThru -WindowStyle Hidden

    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8011/health" -Method Get -TimeoutSec 2
            if ($health.status -eq "ok") {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $ready) {
        throw "API did not become healthy on port 8011."
    }

    $capabilitiesBody = @{
        messages = @(
            @{
                role = "user"
                content = "What can you help with?"
            }
        )
    } | ConvertTo-Json -Depth 5

    $capabilities = Invoke-RestMethod -Uri "http://127.0.0.1:8011/chat" -Method Post -ContentType "application/json" -Headers @{ "X-User" = "demo-user" } -Body $capabilitiesBody -TimeoutSec 10
    if ($capabilities.intent -ne "view_capabilities") {
        throw "Capabilities flow returned unexpected intent: $($capabilities.intent)"
    }

    $workflowBody = @{
        messages = @(
            @{
                role = "user"
                content = "I need vacation from 2030-04-01 to 2030-04-03"
            }
        )
    } | ConvertTo-Json -Depth 5

    $workflow = Invoke-RestMethod -Uri "http://127.0.0.1:8011/chat" -Method Post -ContentType "application/json" -Headers @{ "X-User" = "demo-user" } -Body $workflowBody -TimeoutSec 10
    if ($workflow.workflow_request.status -ne "draft") {
        throw "Workflow flow did not create a confirmation draft."
    }

    $requestId = $workflow.workflow_request.id
    $confirmationBody = @{
        comment = "Confirmed by smoke test"
    } | ConvertTo-Json
    $confirmed = Invoke-RestMethod -Uri "http://127.0.0.1:8011/requests/$requestId/confirm" -Method Post -ContentType "application/json" -Headers @{ "X-User" = "demo-user" } -Body $confirmationBody -TimeoutSec 10
    if ($confirmed.request.status -ne "submitted") {
        throw "Workflow confirmation did not submit the draft."
    }

    $unauthorized = $null
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:8011/admin/system-prompt" -Method Get -TimeoutSec 10 | Out-Null
        throw "Admin route should reject missing auth."
    } catch {
        $unauthorized = $_.Exception.Response.StatusCode.value__
    }
    if ($unauthorized -ne 401) {
        throw "Admin route returned unexpected status without auth: $unauthorized"
    }

    $authorized = Invoke-RestMethod -Uri "http://127.0.0.1:8011/admin/system-prompt" -Method Get -Headers @{ "Authorization" = "Bearer demo-admin-token" } -TimeoutSec 10
    if (-not $authorized.system_prompt) {
        throw "Admin auth flow did not return system prompt."
    }

    $reviewBody = @{
        status = "in_review"
        comment = "Smoke review"
    } | ConvertTo-Json
    $reviewed = Invoke-RestMethod -Uri "http://127.0.0.1:8011/admin/requests/$requestId/status" -Method Put -ContentType "application/json" -Headers @{ "Authorization" = "Bearer demo-admin-token" } -Body $reviewBody -TimeoutSec 10
    if ($reviewed.request.status -ne "in_review") {
        throw "Workflow state transition did not enter review."
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

