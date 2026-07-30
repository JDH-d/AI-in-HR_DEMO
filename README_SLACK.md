# Slack request notifications

PeopleFlow sends demo request notifications to the public `#hr-requests-demo`
channel. A separate channel keeps workflow events out of general conversation
and makes the integration easy to demonstrate. Use a private channel instead
before sending real employee data.

Slack is a notification and manager-action surface. The application and its
SQLite workflow database remain the source of truth for request status. Slack
does not introduce a separate request status or a separate HR bot.

## Events

Notifications are sent after these persisted status changes:

- `draft` to `in_review`: new request
- `in_review` to `approved`: final approval
- `in_review` to `declined`: final decline

Draft creation does not notify Slack. Cancelling a request does not currently
notify Slack.

Each English message includes the request ID, type, dates, employee, current
status, and an **Open in Web** button. An `in_review` card also contains
**Approve** and **Decline** in this exact order:

1. **Approve**
2. **Decline**
3. **Open in Web**

The two decision buttons are added to the existing notification card; no
second action card is created. After a Slack decision, that same card is
updated to the final status and its decision buttons are removed.

**Decline** opens a Slack modal with a required reason. The reason is saved in
the existing workflow event history and is visible in Web. **Open in Web**
opens:

```text
<PUBLIC_WEB_BASE_URL>/manager?request=<request-id>
```

Only Slack user IDs listed in `SLACK_MANAGER_USER_IDS` are mapped to the
existing `manager.demo` identity. The shared decision service verifies that
the mapped identity has the `manager` role before changing data and uses the
same `in_review -> approved/declined` transitions as Web.

If Slack cannot refresh a card after saving a decision, the saved workflow
transition remains valid and an ephemeral warning is attempted. Slack startup
or notification failures do not block Web. Integration logs are redacted and
do not contain webhook URLs or tokens.

Before showing a successful Slack result, PeopleFlow reads the request again
from the workflow database and confirms the saved final status. Stale actions
and validation failures return these English messages:

- repeated action: `This request has already been decided.`
- missing request: `Request not found.`
- unauthorized Slack user: `You are not allowed to manage this request.`
- empty decline reason: `Please enter a reason for declining this request.`

## Configure the existing Slack app

1. Go to [Slack API apps](https://api.slack.com/apps) and create an app for the
   `HR-Bot Slack` workspace.
2. Enable **Incoming Webhooks**.
3. Add a webhook to the `#hr-requests-demo` channel.
4. Enable **Socket Mode**.
5. Create an app-level token with only `connections:write`.
6. Enable **Interactivity & Shortcuts**.
7. Add the bot scope `chat:write` and reinstall the app to the workspace.
8. During reinstall, select `#hr-requests-demo` for the webhook.
9. Copy the generated secrets directly into the local `.env` file. Never
   paste it into source code, documentation, chat, or Git.
10. Copy the Slack Member ID of each allowed manager into
    `SLACK_MANAGER_USER_IDS`. Member IDs are not passwords, but the allowlist
    still belongs in local configuration.
11. Set the following values:

```dotenv
SLACK_NOTIFICATIONS_ENABLED=true
SLACK_ACTIONS_ENABLED=true
SLACK_WEBHOOK_URL=<your-local-secret>
SLACK_BOT_TOKEN=<your-local-xoxb-token>
SLACK_APP_TOKEN=<your-local-xapp-token>
SLACK_MANAGER_USER_IDS=<allowed-manager-slack-user-id>
SLACK_TIMEOUT_SECONDS=3
PUBLIC_WEB_BASE_URL=http://127.0.0.1:5173
```

Use a comma-separated list when several Slack users should act as the existing
demo manager:

```dotenv
SLACK_MANAGER_USER_IDS=U01234567,U07654321
```

Keep only one `SLACK_WEBHOOK_URL` entry in `.env`. Reinstalling an app creates
a new webhook URL; use the latest one for the selected channel.

For a local demo, the **Open in Web** button works on the same computer where
the React frontend is running. Replace `PUBLIC_WEB_BASE_URL` with a reachable
HTTPS URL when the application is deployed.

## Socket Mode security

Manager actions use Slack Socket Mode. PeopleFlow opens an authenticated
WebSocket connection to Slack with `SLACK_APP_TOKEN`; Slack does not send
actions to a public PeopleFlow HTTP Request URL. The bot token is read from
`SLACK_BOT_TOKEN`, and no Slack credential is stored in source code.

Because there is no inbound Slack HTTP endpoint in this architecture,
`SLACK_SIGNING_SECRET`, `X-Slack-Signature`, and
`X-Slack-Request-Timestamp` validation do not apply. Bolt also skips its HTTP
request-verification middleware for Socket Mode payloads. If the integration
is changed to use an HTTP Request URL, add `SLACK_SIGNING_SECRET` to the local
environment and verify both the signature and the request age before
processing any action.

## Start locally

From the repository root, start the API and Web application with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_demo.ps1
```

To restart already running demo processes without rebuilding the document
index, use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_demo.ps1 -ForceRestart -SkipIndexRebuild
```

Open `http://127.0.0.1:5173` after the script reports that the services are
ready.

## Disable notifications

Set:

```dotenv
SLACK_NOTIFICATIONS_ENABLED=false
SLACK_ACTIONS_ENABLED=false
```

No notification is attempted when notifications are disabled. No Socket Mode
connection is started when actions are disabled.

## Verification

1. Start the application.
2. Log in as `employee` and create a draft. Confirm that Slack stays unchanged.
3. Submit the request. Confirm that Slack shows `IN REVIEW`.
4. Click **Approve**. Confirm that the same card changes to `APPROVED` and Web
   immediately shows the same status.
5. Submit another request and click **Decline**. Confirm that Slack requires a
   reason and the same card changes to `DECLINED`.
6. Open the declined request in Web and confirm that its event history contains
   the Slack decline reason.
7. Use **Open in Web** and confirm that it opens the exact request.
8. Try a Slack user not listed in `SLACK_MANAGER_USER_IDS` and confirm that the
   request stays `in_review`.
9. Temporarily use an invalid local webhook value and confirm that the request
   still changes status in Web.
