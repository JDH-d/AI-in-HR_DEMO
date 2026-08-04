# PeopleFlow Slack integration

This guide explains how to connect PeopleFlow to Slack from the beginning. It
assumes that you have never created a Slack app before.

PeopleFlow uses one Slack app named **PeopleFlow Notifications**. Do not create
one app for notifications and another app for HR questions. The same app handles
all Slack features.

## What the Slack integration can do

After setup, PeopleFlow can do four things in Slack:

1. **Send request notifications.** When an employee submits a request for
   review, PeopleFlow posts a request card in `#hr-requests-demo`.
2. **Let a manager make a decision.** An authorized manager can select
   **Approve** or **Decline** on an `IN REVIEW` card. A decline requires a
   reason.
3. **Open the correct request in Web.** The **Open in Web** button opens that
   exact request in the PeopleFlow manager page.
4. **Answer HR questions.** Anyone can run a command such as
   `/hr When are salaries paid?` in `#hr-bot`. The answer uses the same
   documents, search, and answer rules as the Web chat.

Slack is not a second database. The PeopleFlow Web application and its workflow
database remain the source of truth. Slack only shows information and sends
actions back to PeopleFlow.

## Simple connection map

```text
Employee submits a request in Web
        |
        v
PeopleFlow saves the request first
        |
        v
Incoming Webhook posts a card to #hr-requests-demo
        |
        v
Manager selects Approve or Decline
        |
        v
Socket Mode sends the action to PeopleFlow
        |
        v
PeopleFlow saves the decision and refreshes the same Slack card
```

HR questions use the same Socket Mode connection:

```text
/hr question in #hr-bot
        |
        v
Socket Mode sends the command to PeopleFlow
        |
        v
The existing chat_service searches the project documents
        |
        v
Slack shows the question, answer, and document sources
```

## Words used in this guide

| Word | Simple meaning |
| --- | --- |
| **Workspace** | The Slack space that contains your users and channels. |
| **Slack app** | The configuration that gives PeopleFlow access to Slack. |
| **Bot** | The Slack identity used by the app. Its visible name is **PeopleFlow Notifications**. |
| **Channel** | A Slack room such as `#hr-bot`. |
| **Scope** | One permission granted to the Slack app. |
| **Token** | A secret value that proves PeopleFlow is allowed to connect to Slack. |
| **Incoming Webhook** | A secret URL used only to post request cards into one selected channel. |
| **Socket Mode** | A WebSocket connection used to receive `/hr`, **Approve**, and **Decline** actions without a public server URL. |
| **Member ID** | A Slack user identifier that starts with `U`. It is used to decide who may approve or decline requests. |
| **`.env` file** | A local file that stores tokens and settings. It must never be committed to Git. |

## Before you start

You need:

- access to the `HR-Bot Slack` workspace;
- permission to create and install a Slack app in that workspace;
- the PeopleFlow project on your computer;
- a working local `.env` file;
- an OpenAI API key if you want generated HR answers instead of only local
  fallback behavior;
- two Slack channels:
  - `#hr-requests-demo` for request cards;
  - `#hr-bot` for `/hr` questions.

Use public channels for a simple demo. Use private channels before testing with
real employee information.

## Step 1: create the Slack channels

Create both channels in the Slack workspace before creating the webhook.

1. Open Slack.
2. Find **Channels** in the left sidebar.
3. Select **Add channels**.
4. Select **Create a new channel**.
5. Enter `hr-requests-demo` and create the channel.
6. Repeat the steps and create `hr-bot`.

The `#hr-requests-demo` channel receives application cards. The `#hr-bot`
channel keeps HR questions separate from application decisions.

## Step 2: create one Slack app

1. Open [Slack API apps](https://api.slack.com/apps).
2. Select **Create New App**.
3. Select **From scratch**.
4. Enter `PeopleFlow Notifications` as the app name.
5. Select the `HR-Bot Slack` workspace.
6. Select **Create App**.

You should now see the app configuration page. Keep this page open. Every Slack
setting in the next steps is inside this one app.

## Step 3: create the Incoming Webhook

The Incoming Webhook posts request cards to `#hr-requests-demo`. It is not used
for `/hr`, **Approve**, or **Decline**.

1. In the app configuration sidebar, select **Incoming Webhooks**.
2. Turn **Activate Incoming Webhooks** on.
3. Select **Add New Webhook to Workspace**.
4. Choose `#hr-requests-demo`.
5. Select **Allow**.
6. Return to **Incoming Webhooks**.
7. Find **Webhook URLs for Your Workspace**.
8. Select **Copy** next to the webhook for `#hr-requests-demo`.

The copied value starts like this:

```text
https://hooks.slack.com/services/...
```

This URL is a secret. It is called `SLACK_WEBHOOK_URL` in PeopleFlow.

If the page shows two webhook URLs, use the newest webhook that points to
`#hr-requests-demo`. Keep only one `SLACK_WEBHOOK_URL` line in `.env`.

## Step 4: add the bot permissions

PeopleFlow needs only two bot scopes for this demo.

1. In the app configuration sidebar, select **OAuth & Permissions**.
2. Scroll to **Scopes**.
3. Under **Bot Token Scopes**, select **Add an OAuth Scope**.
4. Add `chat:write`.
5. Select **Add an OAuth Scope** again.
6. Add `commands`.

What these scopes do:

| Scope | Why PeopleFlow needs it |
| --- | --- |
| `chat:write` | Lets the bot show action results, update request cards, and send private error messages. |
| `commands` | Installs and enables the `/hr` slash command. |

Do not add these as **User Token Scopes**. They belong under **Bot Token
Scopes**.

## Step 5: install the app and copy the bot token

1. Stay on **OAuth & Permissions**.
2. Select **Install to Workspace**.
3. Review the permissions.
4. Select **Allow**.
5. Return to **OAuth & Permissions**.
6. Find **Bot User OAuth Token**.
7. Select **Copy**.

The token starts with:

```text
xoxb-
```

This value is called `SLACK_BOT_TOKEN` in PeopleFlow. It lets the code act as
the **PeopleFlow Notifications** bot.

Whenever you add or change a scope or slash command, select **Reinstall to
Workspace** and copy the current token shown on the page.

## Step 6: create the app token for Socket Mode

The app token creates the WebSocket connection between your running PeopleFlow
API and Slack.

1. In the app configuration sidebar, select **Basic Information**.
2. Scroll to **App-Level Tokens**.
3. Select **Generate Token and Scopes**.
4. Enter a token name such as `PeopleFlow Socket`.
5. Select **Add Scope**.
6. Add only `connections:write`.
7. Select **Generate**.
8. Select **Copy**.

The token starts with:

```text
xapp-
```

This value is called `SLACK_APP_TOKEN` in PeopleFlow. It does not replace the
`xoxb-` bot token. The project needs both tokens.

## Step 7: enable Socket Mode

1. In the app configuration sidebar, select **Socket Mode**.
2. Turn **Enable Socket Mode** on.
3. If Slack asks for an app token, select the token created in Step 6.

Socket Mode means Slack sends commands and button actions through a WebSocket.
You do not need to publish your local API or create a public Request URL.

## Step 8: enable interactive buttons and modals

1. In the app configuration sidebar, select **Interactivity & Shortcuts**.
2. Turn **Interactivity** on.
3. Save the change if Slack shows a **Save Changes** button.

PeopleFlow needs interactivity for **Approve**, **Decline**, and the decline
reason modal. With Socket Mode enabled, no public Interactivity Request URL is
required.

## Step 9: create the `/hr` command

1. In the app configuration sidebar, select **Slash Commands**.
2. Select **Create New Command**.
3. Enter these values:

   | Field | Value |
   | --- | --- |
   | **Command** | `/hr` |
   | **Short Description** | `Ask PeopleFlow an HR question` |
   | **Usage Hint** | `[question about payroll, PTO, benefits, schedules, or IT]` |

4. Leave the Request URL unused when Socket Mode is enabled. Socket Mode sends
   the command to the running PeopleFlow API.
5. Select **Save**.
6. Return to **OAuth & Permissions**.
7. Select **Reinstall to Workspace**.
8. Select **Allow**.

Reinstallation is important. Slack may not make the command available until
the app is reinstalled with the `commands` scope.

## Step 10: add the bot to the demo channels

After installation, add the visible bot identity to both demo channels.

1. Open `#hr-requests-demo` in Slack.
2. Enter `/invite @PeopleFlow Notifications` and send it.
3. Open `#hr-bot`.
4. Enter `/invite @PeopleFlow Notifications` and send it.

The Incoming Webhook is already tied to `#hr-requests-demo`, but inviting the
app makes the channel setup clear and avoids channel-membership confusion while
testing.

## Step 11: copy the manager Member ID

PeopleFlow uses a Member ID allowlist. Only listed Slack users can approve or
decline requests.

1. Open the Slack profile of the user who will act as the demo manager.
2. Select **More** or the three-dot button.
3. Select **Copy member ID**.

The value starts with `U`, for example:

```text
U01234567
```

This value is called `SLACK_MANAGER_USER_IDS` in PeopleFlow. It is not the
display name and it is not the email address.

At least one Member ID is required when `SLACK_ACTIONS_ENABLED=true`. The
current project starts `/hr` and manager actions through one shared Socket Mode
service, so leaving `SLACK_MANAGER_USER_IDS` empty prevents that shared
connection from starting.

For several managers, separate Member IDs with commas:

```dotenv
SLACK_MANAGER_USER_IDS=U01234567,U07654321
```

## Step 12: understand every local value

| `.env` name | Example prefix or value | Where it comes from | What it controls |
| --- | --- | --- | --- |
| `SLACK_WEBHOOK_URL` | `https://hooks.slack.com/services/...` | **Incoming Webhooks** | Posts request cards to `#hr-requests-demo`. |
| `SLACK_BOT_TOKEN` | `xoxb-...` | **OAuth & Permissions** -> **Bot User OAuth Token** | Gives the bot permission to handle commands, buttons, modals, and messages. |
| `SLACK_APP_TOKEN` | `xapp-...` | **Basic Information** -> **App-Level Tokens** | Opens the Socket Mode WebSocket connection. |
| `SLACK_MANAGER_USER_IDS` | `U...` | Slack user profile -> **Copy member ID** | Lists the Slack users allowed to approve or decline. |
| `SLACK_NOTIFICATIONS_ENABLED` | `true` or `false` | You choose it | Turns outgoing request cards on or off. |
| `SLACK_ACTIONS_ENABLED` | `true` or `false` | You choose it | Starts or stops Socket Mode, manager actions, and `/hr`. |
| `SLACK_TIMEOUT_SECONDS` | `3` | You choose it | Limits how long PeopleFlow waits for the Incoming Webhook. |
| `PUBLIC_WEB_BASE_URL` | `http://127.0.0.1:5173` | Your Web address | Builds the **Open in Web** link. |
| `OPENAI_API_KEY` | `sk-...` | OpenAI API dashboard, not Slack | Lets the shared HR chat generate answers from retrieved project documents. |

The three Slack secret types are different:

- `SLACK_WEBHOOK_URL` sends request cards to one channel.
- `SLACK_BOT_TOKEN` authorizes the bot identity and Slack API operations.
- `SLACK_APP_TOKEN` opens Socket Mode.

Do not put one value into another field. An `xapp-...` token cannot replace an
`xoxb-...` token, and neither token can replace the webhook URL.

## Step 13: create the OpenAI API key

This is not a Slack token. It is used by the same PeopleFlow knowledge service
that answers questions in Web and through `/hr`.

1. Open the [OpenAI API key page](https://platform.openai.com/api-keys).
2. Sign in to the OpenAI Developer Platform.
3. Select the project that should pay for and own the PeopleFlow API usage.
4. Select **Create new secret key**.
5. Enter a clear name such as `PeopleFlow local demo`.
6. Choose permissions appropriate for the project. **All** is the simplest
   option for a local demo. Use a restricted key for a real deployment and
   grant the model and embedding operations used by this project.
7. Create the key.
8. Copy the full secret immediately. The full value is shown only when the key
   is created.

The key normally starts with `sk-` and may include a project-specific prefix.
PeopleFlow reads it from `OPENAI_API_KEY`.

If the key is lost, create a new key. Do not paste it into Slack, a README,
source code, or Git.

## Step 14: put the values into `.env`

Run commands from the repository root.

If `.env` does not exist, create it from the safe template:

```powershell
Copy-Item .env.example .env
```

Open the local file:

```powershell
notepad E:\gitcodetest\.env
```

Find the Slack lines and fill them with the real local values:

```dotenv
SLACK_NOTIFICATIONS_ENABLED=true
SLACK_ACTIONS_ENABLED=true
SLACK_WEBHOOK_URL=<paste-the-webhook-url-here>
SLACK_BOT_TOKEN=<paste-the-bot-token-here>
SLACK_APP_TOKEN=<paste-the-app-token-here>
SLACK_MANAGER_USER_IDS=<paste-the-manager-member-id-here>
SLACK_TIMEOUT_SECONDS=3
PUBLIC_WEB_BASE_URL=http://127.0.0.1:5173
```

Also make sure the OpenAI configuration is present if generated answers are
required:

```dotenv
OPENAI_API_KEY=<paste-your-openai-api-key-here>
OPENAI_MODEL=gpt-5-nano-2025-08-07
```

Rules for editing `.env`:

- keep exactly one line for each setting;
- do not add spaces before or after `=`;
- do not wrap values in Markdown backticks;
- do not paste comments onto the same line as a token;
- save the file after editing;
- restart the application after any change;
- never add `.env` to Git.

The repository tracks `.env.example`, which contains empty values and safe
placeholders. The real `.env` file is ignored by Git.

## Step 15: start or restart PeopleFlow

From the repository root, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_demo.ps1
```

If PeopleFlow is already running or `.env` changed, restart it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_demo.ps1 -ForceRestart -SkipIndexRebuild
```

Keep the API process running. Socket Mode exists only while the PeopleFlow API
is running. When the connection starts successfully, the API log contains:

```text
Slack request actions are connected through Socket Mode.
```

Open the Web application at:

```text
http://127.0.0.1:5173
```

## How each feature works

### Request notifications

Notifications are sent only after PeopleFlow saves one of these transitions:

- `draft -> in_review`: a new request is ready for a manager;
- `in_review -> approved`: the request was approved;
- `in_review -> declined`: the request was declined.

Creating a draft does not notify Slack. A request must be confirmed and moved
to `in_review` first.

Each Slack card contains:

- a short request ID;
- the request type;
- the dates;
- the employee name;
- the current status;
- the available action buttons.

An `IN REVIEW` card shows the buttons in this order:

1. **Approve**
2. **Decline**
3. **Open in Web**

### Approve

When an authorized manager selects **Approve**:

1. Slack sends the action through Socket Mode.
2. PeopleFlow checks the request and the manager allowlist.
3. PeopleFlow applies the existing `in_review -> approved` transition.
4. PeopleFlow reads the saved request again.
5. The same Slack card changes to `APPROVED`.
6. **Approve** and **Decline** disappear because the request is final.

### Decline

When an authorized manager selects **Decline**:

1. Slack opens the **Decline request** modal.
2. The manager enters a required reason.
3. PeopleFlow applies the existing `in_review -> declined` transition.
4. The reason is saved in the normal workflow event history.
5. The same Slack card changes to `DECLINED`.
6. The reason can be found in the Web application.

### Open in Web

The button opens this address:

```text
<PUBLIC_WEB_BASE_URL>/manager?request=<full-request-id>
```

For a local demo, the link works on the same computer where the React frontend
is running. For other computers, replace `PUBLIC_WEB_BASE_URL` with an HTTPS
address that those computers can reach.

### `/hr` knowledge questions

Use the command like this:

```text
/hr When are salaries paid?
```

PeopleFlow sends the text after `/hr` to the same `chat_service` used by the Web
chat. Slack does not have a second answer list or a second knowledge base.

The response contains:

- **Question**: the original user question;
- **Answer**: the answer generated from the existing HR knowledge flow;
- **Sources**: grouped document titles and unique supporting sections.

Internal file names such as `PTO_Policy.md` are hidden in Slack. Web can show
more source detail, such as document versions and excerpts, while Slack keeps
the response compact. The wording can vary when an LLM is used, but the meaning
and source set should match Web.

`/hr` uses `allow_workflow=False`. A sentence about PTO is treated as a
knowledge question and cannot create or submit a request from Slack.

Successful answers are visible in the channel. An empty `/hr` command returns a
private usage hint. Service failures return a short private error without a
stack trace or secret configuration details.

Examples:

```text
/hr When are salaries paid?
/hr Can I request a half day?
/hr How do I request VPN access?
```

## Roles and permissions

| Person | What they can do |
| --- | --- |
| Employee | Submit a request in Web and use `/hr` in Slack. |
| Authorized manager | Use `/hr`, **Approve**, **Decline**, and **Open in Web**. |
| Slack user not in `SLACK_MANAGER_USER_IDS` | Use `/hr` and **Open in Web**, but cannot approve or decline. |
| Knowledge admin | Manage the same project documents and answer settings used by both Web and Slack. |

A Slack Member ID in `SLACK_MANAGER_USER_IDS` maps to the existing
`manager.demo` identity. Slack does not create a new application role or a new
workflow status.

## Safe failure behavior

PeopleFlow always saves a valid Web operation before attempting Slack delivery.
This rule prevents a Slack outage from losing an employee request or manager
decision.

- If a notification fails, the request remains saved in Web.
- If a card refresh fails after a decision, the saved decision remains valid.
- If possible, Slack shows a private warning telling the manager to open Web.
- If Socket Mode cannot start, Web requests and Web chat still work.
- Logs hide tokens and webhook URLs.

Expected action messages:

| Situation | Slack message |
| --- | --- |
| The request was already approved or declined | `This request has already been decided.` |
| The request ID does not exist | `Request not found.` |
| The Slack user is not an allowed manager | `You are not allowed to manage this request.` |
| The decline reason is empty | `Please enter a reason for declining this request.` |

## First complete test

Perform this test after the first setup or after replacing a token.

### Test A: HR question

1. Open `#hr-bot`.
2. Run `/hr When are salaries paid?`.
3. Confirm that Slack shows **Question**, **Answer**, and **Sources**.
4. Ask the same question in the Web chat.
5. Confirm that the meaning and source set match.

### Test B: request notification

1. Open the PeopleFlow Web application.
2. Log in as `employee`.
3. Create a request draft.
4. Confirm that Slack does not receive a notification yet.
5. Confirm and submit the request.
6. Confirm that `#hr-requests-demo` receives an `IN REVIEW` card.

### Test C: approval

1. Use a Slack account listed in `SLACK_MANAGER_USER_IDS`.
2. Select **Approve** on the new card.
3. Confirm that the same card changes to `APPROVED`.
4. Open the manager page in Web.
5. Confirm that the request is also `approved` there.

### Test D: decline

1. Submit another request from Web.
2. Select **Decline** in Slack.
3. Enter a reason in the modal.
4. Submit the modal.
5. Confirm that the same card changes to `DECLINED`.
6. Open the request in Web.
7. Confirm that the workflow history contains the Slack decline reason.

### Test E: exact Web link

1. Select **Open in Web** on a Slack card.
2. Log in as `manager` if the login page appears.
3. Confirm that the manager page opens the exact request from that card.

## Troubleshooting

| Problem | Most likely cause | What to do |
| --- | --- | --- |
| `/hr` does not appear in Slack autocomplete | The slash command or `commands` scope is missing. | Create `/hr`, add `commands` under **Bot Token Scopes**, and select **Reinstall to Workspace**. |
| Slack shows `dispatch_failed` after `/hr` | The PeopleFlow API is stopped, Socket Mode is disconnected, or the `xapp-...` token is wrong. | Start or restart PeopleFlow, enable Socket Mode, and copy the current `SLACK_APP_TOKEN`. |
| The API log says the Slack configuration is incomplete | A bot token, app token, or manager Member ID is empty. | Fill `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, and at least one `SLACK_MANAGER_USER_IDS` value. |
| `/hr` works but request cards do not appear | The webhook feature is disabled, the webhook is wrong, or notifications are disabled. | Check `SLACK_WEBHOOK_URL`, `SLACK_NOTIFICATIONS_ENABLED=true`, and the webhook channel. |
| Request cards appear but have no **Approve** or **Decline** | Slack actions are disabled. | Set `SLACK_ACTIONS_ENABLED=true` and restart PeopleFlow. |
| Buttons say the user is not allowed | The current Slack Member ID is missing from the allowlist. | Copy the correct Member ID and add it to `SLACK_MANAGER_USER_IDS`. |
| **Decline** opens but cannot submit | The reason is empty. | Enter a reason before submitting the modal. |
| **Open in Web** opens the wrong place or cannot connect | `PUBLIC_WEB_BASE_URL` is wrong or only available on another computer. | Use `http://127.0.0.1:5173` on the local demo computer or a reachable HTTPS deployment URL. |
| The bot gives a generic fallback instead of a useful answer | The question is unsupported, the document index is stale, or the AI configuration is unavailable. | Ask a supported HR question, rebuild the index if documents changed, and check `OPENAI_API_KEY`. |
| New `.env` values are ignored | The application was not restarted or the file contains duplicate settings. | Keep one line per setting and run `run_demo.ps1 -ForceRestart -SkipIndexRebuild`. |
| An old webhook works but a new one does not | `.env` may still contain the old value. | Keep only the current webhook for `#hr-requests-demo`, save `.env`, and restart. |

## Enable or disable individual parts

### Everything enabled

```dotenv
SLACK_NOTIFICATIONS_ENABLED=true
SLACK_ACTIONS_ENABLED=true
```

This enables request cards, buttons, modals, and `/hr`.

### Notifications only

```dotenv
SLACK_NOTIFICATIONS_ENABLED=true
SLACK_ACTIONS_ENABLED=false
```

New request cards are posted, but they do not contain manager decision buttons.
`/hr` is unavailable because Socket Mode is not started.

### Socket Mode features only

```dotenv
SLACK_NOTIFICATIONS_ENABLED=false
SLACK_ACTIONS_ENABLED=true
```

`/hr` and Socket Mode handlers are available, but PeopleFlow does not post new
request cards through the webhook. The bot token, app token, and at least one
manager Member ID are still required.

### Slack completely disabled

```dotenv
SLACK_NOTIFICATIONS_ENABLED=false
SLACK_ACTIONS_ENABLED=false
```

PeopleFlow does not call Slack and does not start a Socket Mode connection. Web
requests and Web chat continue to work.

## Security rules

- Never commit `.env`.
- Never paste a real `xoxb-...` token, `xapp-...` token, webhook URL, OpenAI key,
  or full `.env` file into source code, README files, issues, commits, or chat.
- Use placeholders in examples.
- Treat webhook URLs and tokens like passwords.
- If a secret is exposed, revoke or replace it immediately in Slack and update
  the local `.env` file.
- Reinstall the Slack app after permission changes.
- Use private channels before processing real employee information.
- Review Git history as well as the current files when checking for leaked
  secrets. Deleting a secret from a later commit does not remove it from an
  earlier commit.

PeopleFlow uses Socket Mode, so the current architecture has no inbound Slack
HTTP endpoint. `SLACK_SIGNING_SECRET`, `X-Slack-Signature`, and
`X-Slack-Request-Timestamp` are not used. If the integration is later changed
to public HTTP Request URLs, request signature and timestamp verification must
be added before processing Slack actions.

## Local automated checks

The Slack adapter tests do not require a real Slack workspace:

```powershell
python -m pytest -q tests/test_slack_notification_service.py tests/test_slack_action_service.py tests/test_slack_hr_command_service.py
```

Run the knowledge comparison evaluation with:

```powershell
python -m scripts.run_rag_eval
```

Automated tests use fake Slack clients and placeholder values. Do not put real
workspace secrets into test files.

## Official references

### Slack

- [Create a Slack app from app settings](https://docs.slack.dev/app-management/quickstart-app-settings/)
- [Incoming Webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/)
- [Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/)
- [Bolt for Python Socket Mode](https://docs.slack.dev/tools/bolt-python/concepts/socket-mode/)
- [Slash Commands](https://docs.slack.dev/interactivity/implementing-slash-commands/)
- [`chat:write` scope](https://docs.slack.dev/reference/scopes/chat.write/)
- [`connections:write` scope](https://docs.slack.dev/reference/scopes/connections.write/)

### OpenAI

- [Create and use an OpenAI API key](https://help.openai.com/en/articles/4936850-how-to-create-and-use-an-api-key)
- [OpenAI API key safety](https://help.openai.com/en/articles/5112595-best-practices-for-api-key)
