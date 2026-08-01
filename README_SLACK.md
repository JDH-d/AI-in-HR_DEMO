# Slack integration

PeopleFlow sends demo request notifications to the public `#hr-requests-demo`
channel. A separate channel keeps workflow events out of general conversation
and makes the integration easy to demonstrate. Use a private channel instead
before sending real employee data.

Use the public `#hr-bot` channel for HR knowledge questions. The `/hr` command
is available workspace-wide, but a dedicated channel keeps the demo focused.

Slack is a notification, manager-action, and HR question surface. The
application remains the source of truth for request status and knowledge.
There is one Slack app, one bot, and one Socket Mode connection.

## HR knowledge command

Ask an HR question with:

```text
/hr When are salaries paid?
```

The command passes the original question to the same `chat_service` used by
Web. It does not contain Slack-only answers or a separate knowledge base.
Workflow creation is disabled for this surface with `allow_workflow=False`, so
PTO wording is answered as a knowledge question and cannot create a request.

A successful response is posted in the channel and shows the original question,
the answer, and grouped source titles with their unique supporting sections.
Internal file names such as `PTO_Policy.md` are not shown in Slack. An empty
command shows a private usage hint. Service errors show a short private message
without a stack trace or technical details.

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

Do not create a second app for `/hr`. Notifications, manager buttons, and the
knowledge command are all connected through the existing **PeopleFlow
Notifications** app.

Create the public `#hr-requests-demo` and `#hr-bot` channels in the workspace
before configuring the app. Use the first for request cards and the second for
HR questions.

### Settings in Slack API

1. Open [Slack API apps](https://api.slack.com/apps), choose **Create New App**,
   select **From scratch**, choose the `HR-Bot Slack` workspace, and create the
   app.
2. Open **Incoming Webhooks**, turn the feature on, choose **Add New Webhook to
   Workspace**, and select `#hr-requests-demo`.
3. Open **Basic Information** -> **App-Level Tokens**, generate an app token
   with only the `connections:write` scope, and keep the resulting `xapp-...`
   value for `SLACK_APP_TOKEN`.
4. Open **Socket Mode**, enable it, and select the app-level token created in
   the previous step.
5. Open **Interactivity & Shortcuts** and enable interactivity. A public Request
   URL is not needed because actions arrive through Socket Mode.
6. Open **Slash Commands**, create `/hr`, set a description such as
   `Ask PeopleFlow an HR question`, and optionally use
   `[question about payroll, PTO, benefits, schedules, or IT]` as the usage
   hint. A public Request URL is not required in Socket Mode.
7. Open **OAuth & Permissions** -> **Scopes** and add these **Bot Token
   Scopes**:
   - `chat:write` for Slack messages and request-card updates;
   - `commands` for `/hr`.
8. Select **Install to Workspace** or **Reinstall to Workspace** after changing
   commands or scopes. Copy the resulting `xoxb-...` **Bot User OAuth Token**
   into `SLACK_BOT_TOKEN`.

The four local values come from these places:

| Local setting | Where to get it | Used for |
| --- | --- | --- |
| `SLACK_WEBHOOK_URL` | **Incoming Webhooks** | Request notifications in `#hr-requests-demo` |
| `SLACK_BOT_TOKEN` | **OAuth & Permissions** | `/hr`, buttons, modals, and card updates |
| `SLACK_APP_TOKEN` | **Basic Information** -> **App-Level Tokens** | The Socket Mode connection |
| `SLACK_MANAGER_USER_IDS` | Slack profile -> **More** -> **Copy member ID** | Manager authorization |

Copy these values directly into the local `.env` file. Never paste a real
webhook, token, or `.env` content into source code, documentation, chat, or
Git. Set:

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

`SLACK_ACTIONS_ENABLED=true` starts the single Socket Mode connection used by
both manager actions and `/hr`. `SLACK_NOTIFICATIONS_ENABLED=true` separately
enables outbound request notifications. Therefore `/hr` needs the bot and app
tokens but does not use the incoming webhook.

For a local demo, the **Open in Web** button works on the same computer where
the React frontend is running. Replace `PUBLIC_WEB_BASE_URL` with a reachable
HTTPS URL when the application is deployed.

### Confirm the first connection

1. Restart PeopleFlow so it reads the new environment values:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_demo.ps1 -ForceRestart -SkipIndexRebuild
   ```

2. In `#hr-bot`, run:

   ```text
   /hr When are salaries paid?
   ```

   A connected bot posts the original question, the answer, and its grouped
   document sources in the channel.
3. Submit a request in Web and confirm that an `IN REVIEW` card appears in
   `#hr-requests-demo`.
4. Use **Approve** or **Decline** as a Slack user listed in
   `SLACK_MANAGER_USER_IDS`, then confirm that Web shows the same final state.

If `/hr` is absent from Slack autocomplete, confirm that the slash command and
the `commands` scope exist, then reinstall the app. If Slack reports
`dispatch_failed`, confirm that PeopleFlow is running, Socket Mode is enabled,
`SLACK_ACTIONS_ENABLED=true`, and the `xapp-...` token is current. If request
cards do not arrive but `/hr` works, check the webhook URL, its selected
channel, and `SLACK_NOTIFICATIONS_ENABLED`.

## Socket Mode security

Manager actions and `/hr` use the same Slack Socket Mode connection. PeopleFlow
opens an authenticated WebSocket connection to Slack with `SLACK_APP_TOKEN`;
Slack does not send actions or commands to a public PeopleFlow HTTP Request
URL. The bot token is read from `SLACK_BOT_TOKEN`, and no Slack credential is
stored in source code.

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
connection is started when actions are disabled, so `/hr` is also unavailable.

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

### Verify `/hr`

Run the adapter tests without a real Slack workspace:

```powershell
python -m pytest -q tests/test_slack_hr_command_service.py
```

Then start the application and, in `#hr-bot`, ask:

```text
/hr When are salaries paid?
/hr What is the PTO policy?
/hr How do I get VPN access?
```

Ask the same three questions in Web. The wording can vary when an LLM is used,
but the meaning and returned source set must match because both surfaces call
the same service. Also verify that `/hr` without text shows a private usage
hint and that a temporary service failure shows only a private generic error.
