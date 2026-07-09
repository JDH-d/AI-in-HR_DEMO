# Microsoft Teams Bot Setup

This project now uses a real Bot Framework endpoint for Microsoft Teams personal chat.
The old outgoing-webhook gateway has been removed.

## Runtime Behavior

- Scope: personal chat only.
- Endpoint: `POST /api/messages`.
- Health check: `GET /teams/health`.
- The bot calls the same `ChatService` used by the Web UI.
- Source documents are appended under a `Sources` block when retrieval returns sources.

## Required Environment Variables

```env
MICROSOFT_APP_ID=<Azure Bot App ID>
MICROSOFT_APP_PASSWORD=<Azure Bot client secret>
MICROSOFT_APP_TENANT_ID=<Microsoft Entra tenant ID>

# Optional
TEAMS_BOT_HISTORY_DB=data/teams_conversations.db
TEAMS_BOT_MAX_CONTEXT=12
TEAMS_BOT_MAX_SOURCES=3
TEAMS_BOT_ENABLED=true
```

`MicrosoftAppId`, `MicrosoftAppPassword`, and `MicrosoftAppTenantId` are also accepted.

## Local Test Flow

1. Start the API:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

2. Expose it through a public HTTPS tunnel:

```powershell
ngrok http 8000
```

or:

```powershell
devtunnel host -p 8000 --allow-anonymous
```

3. In Azure Bot, set the messaging endpoint:

```text
https://<public-host>/api/messages
```

4. Enable the Microsoft Teams channel for the Azure Bot.

5. Build the Teams app package:

```powershell
$env:MICROSOFT_APP_ID="<Azure Bot App ID>"
$env:BOT_BASE_URL="https://<public-host>"
$env:BOT_DISPLAY_NAME="MVP Assistant"
powershell -ExecutionPolicy Bypass -File .\scripts\build_teams_package.ps1
```

6. Upload `teams_app_manifest\dist\teams-app-package.zip` in Teams Developer Portal or Teams Admin Center.

## What To Collect From Azure

- Application/client ID of the bot registration.
- Client secret value for that app registration.
- Directory/tenant ID.
- Public HTTPS domain used for the bot endpoint.

The OpenAI key and document/RAG settings are the same ones used by the Web UI.

