param(
    [string]$TeamsAppId = $env:TEAMS_APP_ID,
    [string]$MicrosoftAppId = $env:MICROSOFT_APP_ID,
    [string]$BotBaseUrl = $env:BOT_BASE_URL,
    [string]$BotDisplayName = $(if ($env:BOT_DISPLAY_NAME) { $env:BOT_DISPLAY_NAME } else { "MVP Assistant" }),
    [string]$OutputDir = "teams_app_manifest\dist"
)

$ErrorActionPreference = "Stop"

if (-not $TeamsAppId) {
    $TeamsAppId = [guid]::NewGuid().ToString()
    Write-Host "Generated TEAMS_APP_ID: $TeamsAppId"
}
if (-not $MicrosoftAppId) {
    throw "MICROSOFT_APP_ID is required. Use the App ID from your Azure Bot registration."
}
if (-not $BotBaseUrl) {
    throw "BOT_BASE_URL is required, for example https://your-tunnel.example.com"
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$templatePath = Join-Path $projectRoot "teams_app_manifest\manifest.template.json"
$outputPath = Join-Path $projectRoot $OutputDir
$manifestPath = Join-Path $outputPath "manifest.json"
$packagePath = Join-Path $outputPath "teams-app-package.zip"
$botDomain = ([uri]$BotBaseUrl).Host

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

$manifest = Get-Content -Path $templatePath -Raw -Encoding UTF8
$manifest = $manifest.Replace('${TEAMS_APP_ID}', $TeamsAppId)
$manifest = $manifest.Replace('${MICROSOFT_APP_ID}', $MicrosoftAppId)
$manifest = $manifest.Replace('${BOT_BASE_URL}', $BotBaseUrl.TrimEnd('/'))
$manifest = $manifest.Replace('${BOT_DISPLAY_NAME}', $BotDisplayName)
$manifest = $manifest.Replace('${BOT_DOMAIN}', $botDomain)
$manifest | Set-Content -Path $manifestPath -Encoding UTF8

Copy-Item -Path (Join-Path $projectRoot "teams_app_manifest\color.png") -Destination (Join-Path $outputPath "color.png") -Force
Copy-Item -Path (Join-Path $projectRoot "teams_app_manifest\outline.png") -Destination (Join-Path $outputPath "outline.png") -Force

if (Test-Path $packagePath) {
    Remove-Item -Path $packagePath -Force
}
Compress-Archive -Path (Join-Path $outputPath "manifest.json"), (Join-Path $outputPath "color.png"), (Join-Path $outputPath "outline.png") -DestinationPath $packagePath

Write-Host "Teams app package: $packagePath"

