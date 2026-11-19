# PeopleFlow AI 2.2

A demo workspace for employees and managers: answers grounded in company documents, requests with explained decisions, and persistent chat history. The interface and AI assistant use **English**.

**Start here:** [run the application](#quick-start--windows) → optionally [connect OpenAI](#openai-get-a-key-and-check-ai-answers), [connect Discord](#discord-gateway-without-ngrok), or [connect Slack](#slack-bot-and-signed-http-commands) → [link Employee and Manager](#link-accounts-without-enabling-notifications). Connect one service at a time; none is needed to sign in or manage requests.

## Quick start — Windows

OpenAI, Slack, and Discord are not required for the first launch. With **Python 3.10+ and Node.js 22.12+** already installed, setup takes three steps. Downloading dependencies requires internet access; installing Python/Node.js and connecting bots are outside the five-minute target.

1. Download the project ZIP from GitHub and **extract it** to a writable folder, such as `C:\Projects\PeopleFlow Demo`. Alternatively, use `git clone` with your repository URL. Do not run files from inside the ZIP.
2. Double-click **`start.bat`**. It creates `.venv`, installs Python and frontend dependencies, creates `.env`, prepares the database and demo document index, starts the API and frontend, and opens your browser. Wait for `Demo services started`.
3. Find the generated **`.env`** file next to `start.bat` → right-click → **Open with → Notepad**. Copy the value after **`DEMO_LOGIN_PASSWORD=` without the surrounding quotes**. On the sign-in page, choose **Employee** to fill **Username** with `employee`, enter the password, and click **Continue**. You can also type one of the usernames in the table below directly. The password is shared by the three demo roles, generated on your computer, and preserved across restarts. Do not confuse `.env` with the `.env.example` template.

If the browser does not open, visit **http://127.0.0.1:5173/login**. After signing in, open **Home → Create request**. An empty request list is normal in a fresh installation. Keep the launcher window open.

| Role | Username | Pages |
|---|---|---|
| Employee | `employee` | [Home](http://127.0.0.1:5173/home), [requests](http://127.0.0.1:5173/requests), [chats](http://127.0.0.1:5173/employee) |
| Manager | `manager` | [Queue](http://127.0.0.1:5173/manager) |
| Knowledge Admin | `knowledge_admin` | [Administration](http://127.0.0.1:5173/knowledge) |

API: [health check](http://127.0.0.1:8000/api/v1/health), [interactive documentation](http://127.0.0.1:8000/docs). Requests and local search work without OpenAI; generative answers require an API key.

**Stopping:** press Enter in the launcher window or double-click **`stop.bat`**. Closing the window with X may leave the servers running; use `stop.bat` in that case. Running `start.bat` again opens the existing application without creating a second pair of processes.

You do not need to activate `.venv`, use administrator privileges, or permanently change the PowerShell execution policy. The batch files apply the policy override only to their own PowerShell process.

**Clean-start recheck on November 16, 2026:** the final source passed on Windows with Python 3.14.3 / Node.js 24.14.0, from a path containing spaces and Cyrillic characters. No `.venv`, `node_modules`, env files, or working data were copied. The final clean installation took **12 minutes 50 seconds**, including package downloads; an earlier run with empty package caches took **11 minutes 12 seconds**. A five-minute first launch is therefore a target, **not a guarantee**. Checks covered the API, frontend, sign-in for all three roles, generated five-variable configuration, repeated startup with the same process IDs, shutdown, the frontend build, and local retrieval evaluation. The final automated check used free ports 18117/15217 and `-NoBrowser -NoWait`; normal startup opens the browser and waits for Enter. Sources were exported without local state: the workspace has no Git metadata, so downloading from GitHub and checking its history were not tested.

## System requirements

- Windows 10/11 and Windows PowerShell 5.1+ for the `.bat` launcher.
- **Python 3.10+** with `py` or `python` on PATH: [download](https://www.python.org/downloads/windows/). Enable **Add Python to PATH** during installation.
- **Node.js 22.12+** with npm: [download](https://nodejs.org/en/download).
- A modern browser, write access to the project folder, and free TCP ports **8000** and **5173**.
- Internet access for the first installation from PyPI/npm; access to OpenAI/Slack/Discord only when using the corresponding integration.

After installing Python/Node.js, reopen your terminal or `start.bat`. Docker, PostgreSQL, ngrok, and globally installed npm packages are not required for the core application.

## Employee and Manager features

**Employee:** a home page with current tasks, drafts, and chats; a step-by-step form for PTO, Sick leave, or Document requests; saving drafts, submitting, and cancelling requests. Employees can access only their own requests, with search, filters, sorting, progress, decision reasons, comments, attachments, and change history. They can answer a request for clarification and request reconsideration while preserving the previous decision in the history.

The English-language chat answers questions using documents and cites its sources. Conversations persist across restarts and can be reopened, continued, searched, renamed, and deleted. Help and private requests for clarification through Slack/Discord are available. Employees do not receive automatic notifications for every status change.

**Manager:** a queue of submitted requests assigned to that manager; private drafts and another manager's requests are inaccessible. Search and combine filters for status, category, priority, assignee, and requests needing attention. Actions include Start review, assigning an authorized reviewer, Request information, Approve, Reject, and Complete. Decisions require a reason, an objective basis, and confirmation that the same criteria were applied; response templates remain editable.

Managers can view request history, an activity log, key metrics, and overdue requests: **5 calendar days** after submission, reconsideration, or an Employee response. Waiting for clarification from an Employee does not count as an overdue Manager task; comments and reassignment do not reset the deadline. The only bulk action is **Start review**, for up to 20 selected, accessible requests, with an individual result for each. Decisions are made individually. Private notifications relate only to assigned work.

**Knowledge Admin** manages documents, the index, answer quality, AI settings, and integrations. Saved chats are available only to Employee in both the interface and API. Manager and Admin receive HTTP 403 for conversation and compatibility chat endpoints; their existing historical records remain stored. Employee history remains owner-scoped. Admin's separate **Test answer** preview remains available without creating a saved conversation. Light/dark themes, keyboard navigation, mobile layouts, and reduced-motion support are available.

Request statuses: `Draft`, `Submitted`, `In Review`, `Needs Information`, `Approved`, `Rejected`, `Cancelled`, `Completed`. The server checks permissions and allowed transitions; switching sections does not change a user's role.

## `.env` configuration: exactly five variables

[`.env.example`](.env.example) is a template without secrets. You normally do not need to copy it manually: `start.bat` creates `.env` and preserves existing settings.

| Variable | Purpose | On first launch |
|---|---|---|
| `OPENAI_API_KEY` | Optional key for generation and embeddings | Empty: local mode |
| `OPENAI_MODEL` | Generation model available to your API project | `gpt-5-nano-2025-08-07` |
| `DEMO_LOGIN_PASSWORD` | Shared password for the three demo roles | Generated automatically |
| `DEMO_AUTH_SECRET` | Token-signing secret, at least 32 characters | Generated automatically |
| `DATA_DIR` | Folder for the database, index, settings, and logs | `data` in a fresh installation |

For AI answers, follow [OpenAI setup](#openai-get-a-key-and-check-ai-answers) below. OpenAI calls may incur charges to your API project.

Other settings have defaults in `core/configuration.py`: documents in `documents/`, local CORS origins, an eight-hour token lifetime, masked user text in diagnostic logs, a 30-second OpenAI timeout, and up to two retries. Process environment variables take precedence over files.

**Do not change `DATA_DIR` unnecessarily when upgrading.** Older installations may use `.demo_state`; the launcher preserves that path without moving data. If both `data` and `.demo_state` contain data, explicitly select the correct folder. Relative paths resolve from the project root; `${...}` interpolation is disabled in dotenv files.

### OpenAI: get a key and check AI answers

1. Sign in to the [OpenAI API platform](https://platform.openai.com/). Select the organization and project that will pay for this demo. Use an existing project you can access, or ask its owner to create one and invite you. This is the API platform, not the ChatGPT conversation page.
2. Open [API billing](https://platform.openai.com/settings/organization/billing/overview) for that organization and check that API usage is funded and available. Add a payment method or credits if required; ask the organization owner if billing controls are unavailable. ChatGPT and API billing are separate, so check the actual API balance rather than assuming a ChatGPT subscription enables calls. See [OpenAI's billing explanation](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform).
3. Open the selected project's [API Keys](https://platform.openai.com/api-keys) page → **Create new secret key**, give it a recognizable name such as `PeopleFlow local demo`, and copy the full generated secret. This is not a project ID, organization ID, ChatGPT password, or Admin API key. Keep it private; if you lose the secret, create a replacement. For a restricted key, allow requests to **Responses** (`/v1/responses`) and **Embeddings** (`/v1/embeddings`), and ensure the project permits the models below. See [project key permissions](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform).
4. Stop PeopleFlow with `stop.bat`. Open the existing **`.env`** next to `start.bat` in Notepad and paste the secret after `OPENAI_API_KEY=`. Replace that line's value; do not add another copy of the variable, a `Bearer ` prefix, or angle brackets. Preserve the password, signing secret, and data path. The key belongs in the server's `.env`, never in frontend files or a `VITE_` variable.
5. Keep `OPENAI_MODEL=gpt-5-nano-2025-08-07` initially. It is this project's configured generation model; the default embedding model is `text-embedding-3-small`. If your project does not permit the generation model, ask its owner for access or use a permitted text model compatible with the Responses API. A model's display name in ChatGPT is not an API model ID; see the [API model catalog](https://developers.openai.com/api/docs/models).
6. Save `.env` and run `start.bat`. As **Knowledge Admin**, open **Documents** and check that the demo documents are indexed. Use **Index document / Re-index** if needed, including when adding embeddings to an index previously built in local mode. Indexing with a configured key can send document text to OpenAI and incur usage.
7. To test generation, open **AI settings → Test answer**, select **Payroll example**, then **Run test**. This sends the synthetic question and retrieved document excerpts to OpenAI; it does not save a chat. Check the answer and sources, then check [API Usage](https://platform.openai.com/usage) in the same project for a Responses request (allow for reporting delay). A local search answer or a successful health check alone does not prove OpenAI is connected. You can then sign in as Employee and try **My chats** with an English question about the demo documents.

If the key is rejected, replace it from the correct project and restart. For permission/model errors, check both endpoint permissions and model access. For quota errors, check API billing and project limits; repeated retries do not add credit. Embedding failures fall back to local retrieval, so an answer alone does not prove embeddings succeeded. To return to local mode, clear only `OPENAI_API_KEY`, save, and restart; keep all other settings and data.

## Manual startup for developers

Run these commands in **PowerShell from the project root**, without activating `.venv`. Install the system requirements first. Do not start manual servers on the same ports while `start.bat` is already running them.

To open PowerShell in the right folder, open the extracted project in File Explorer, click its address bar, type `powershell`, and press Enter. The folder must contain `start.bat` and this README. Use this method whenever the instructions below say “from the project root.”

Prepare a fresh copy:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m scripts.demo_setup configure
npm.cmd --prefix frontend ci --include=dev
```

If `py` is unavailable, use `python -m venv .venv` as the first command. `configure` creates the settings and password while preserving existing values.

Terminal 1 — API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Terminal 2 — frontend, also from the project root:

```powershell
npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173/login`. On the default ports, Vite proxies `/api` to `127.0.0.1:8000`; no additional variable is needed. For other ports, set `VITE_API_URL` in the frontend process environment and the matching `CORS_ORIGINS` in the API process environment, rather than in the main `.env`.

Manual startup does not run the launcher's initial indexing step: use Knowledge Admin → **Documents → Index document**. After changing source documents, use **Re-index**. TXT, MD, PDF, and DOCX are supported. To stop, press **Ctrl+C in each terminal**.

To use different ports with the normal launcher:

```powershell
.\start.bat -ApiPort 8001 -UserUiPort 5174
```

Launcher options: `-ForceRestart` restarts its servers; `-InstallDeps` reinstalls dependencies; `-NoBrowser -NoWait` runs without browser launch or an interactive wait for automated checks. The last option leaves the servers running until `stop.bat` is used.

## Slack and Discord — optional personal notifications

Without these integrations, all application features except external notifications remain available. The bots deliver **private notifications** and verify account linking. Creating or reviewing a request and answering a clarification are done in the web application using the message link. Legacy channel webhook URLs are not used.

Store bot settings in a separate local **`.env.integrations`** file next to this README, or in the server environment. When creating the file in Notepad, choose **All files**, **UTF-8** encoding, and the filename **`.env.integrations`**, without an added `.txt` extension. The main `.env` remains limited to five variables. Restart the application after changing tokens.

### Discord: Gateway, without ngrok

Use a Discord account that can manage a test server, plus two different Discord accounts for Employee and Manager. If you do not have a server, use Discord's **+ → Create My Own** and follow the prompts. Invite the other test account to that server before linking. One bot serves both roles; their account IDs determine the recipient.

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**, name it `PeopleFlow Demo`, and create it. Copy **General Information → Application ID**. Then open **Bot → Token** and use **Reset Token** if needed to obtain the secret; complete Discord's confirmation/MFA prompt. Resetting invalidates an older token, so update any existing local configuration. Do not use the OAuth2 Client Secret or Public Key as the bot token.
2. Create or open **`.env.integrations` next to `start.bat`** and paste each value after `=` below. Preserve existing Slack settings; replace existing Discord values instead of adding duplicate keys. Copy the token itself without a `Bot ` prefix, quotes, or angle brackets. Save as `.env.integrations`, not `.env.integrations.txt`.

   ```dotenv
   DISCORD_BOT_TOKEN=
   DISCORD_APPLICATION_ID=
   ```

3. Open **Installation** and enable **Guild Install** in **Installation Contexts**. Under **Install Link**, choose **Discord Provided Link**. In **Default Install Settings → Guild Install**, select the `bot` and `applications.commands` scopes and save. Administrator permissions and privileged intents are not required; leave privileged intent switches off.
4. Copy the **Install Link**, open it in your browser while signed in to the account managing the test server, choose **Add to server**, select the server, and authorize. Check that the bot appears in that server's member list. Installing only to **My Apps** is not the server installation used here. If your server is missing from the picker, use its owner or an account with **Manage Server** permission. The bot may appear offline until PeopleFlow starts.
5. In **General Information**, leave **Interactions Endpoint URL empty**, remove any old HTTP/ngrok URL, and save. Gateway opens an outbound connection from the API to Discord; `DISCORD_PUBLIC_KEY` is not needed. If an older configuration contains `DISCORD_CONNECTION_MODE=http`, remove that setting or change its value to `gateway`, including any Windows environment override. Otherwise the old value disables Gateway even when the portal's endpoint is empty.
6. Run `stop.bat`, then `start.bat`. Open PowerShell from the project root and register the command once:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.register_discord_command --register
   ```

   Expect `Registered /peopleflow link code:<code>. Other Discord commands were not changed.` This command contacts Discord and creates or updates `/peopleflow`; it does not send a notification. Without `--register`, it only displays a safe preview. Registration is not needed on every restart, but repeat it when changing to a different Discord application or updating the command definition.

7. In PeopleFlow, sign in as **Knowledge Admin → Integrations**. Discord should show **Ready to enable personal delivery**; leave delivery **Disabled** while linking. This means the required settings are present, not that a Discord connection has been proven. Resolve any registration or Gateway error before proceeding.
8. In Discord, open the test server's member list, select the bot, and choose **Message** to open its direct conversation. Both test accounts must share the server with the bot and allow its DMs. Check the server's privacy settings or **User Settings → Content & Social → Social permissions**; enable DMs for the test server rather than changing every server. See [Discord's privacy instructions](https://support.discord.com/hc/en-us/articles/217916488-Blocking-Privacy-Settings).
9. Follow [Link accounts without enabling notifications](#link-accounts-without-enabling-notifications), once for Employee and once for Manager. In the bot DM, type `/peopleflow` and select **link** from the command picker, then paste only the generated code into its **code** field. If pasting the complete displayed command stays ordinary text, use this picker instead. The bot does not answer ordinary messages. Keep PeopleFlow running for Gateway to receive the command.

If `/peopleflow` does not appear, refresh Discord, confirm the bot is installed on the shared test server and that registration succeeded for the same Application ID/token. Wait for Discord to refresh its command list before retrying. **Application did not respond** means installation alone is not enough: check the running API, Gateway mode, empty endpoint, and network access. Keep tokens and linking codes out of screenshots and logs shared with others.

Official instructions: [creating an application](https://docs.discord.com/developers/quick-start/getting-started), [Gateway and HTTP interactions](https://docs.discord.com/developers/interactions/receiving-and-responding). The alternative `DISCORD_CONNECTION_MODE=http` mode with `DISCORD_PUBLIC_KEY` requires a public HTTPS callback at `/api/v1/integrations/discord/interactions`; keep Gateway for the local demo.

### Slack: bot and signed HTTP commands

Slack sends `/peopleflow` commands to a public HTTPS **callback** on the API. This version does not implement Slack Socket Mode. The walkthrough below uses **ngrok on Windows** to forward those commands to the local application; no router port forwarding is needed. Use a test Slack workspace where you can install apps, an ngrok account, and two separate Slack accounts to test Employee and Manager. If your workspace restricts app installation, its administrator must approve the app first.

If you do not have a test workspace, open [Create a Slack workspace](https://slack.com/get-started#/createnew), sign in or enter your email, complete email verification, and choose **Create a Workspace**. Follow the prompts and keep this demo in that test workspace. See [Slack's workspace creation guide](https://slack.com/help/articles/206845317-Create-a-Slack-workspace).

Both Slack accounts must be members of **the same test workspace**. If the second account has not joined yet, use the workspace name menu → **Invite people**, invite its email address, and accept the invitation while signed in as that person; see [Slack's invitation instructions](https://slack.com/help/articles/201330256-Invite-new-members-to-your-workspace). Install **one bot** for the workspace: Employee and Manager share its bot token but link their own Slack user IDs. PeopleFlow's demo password and role selector do not create Slack accounts or sign you into Slack.

The tunnel below exposes only the Slack callback and a health check. Continue using the local browser address to sign in and work with requests. A Slack incoming-webhook URL is not used for this personal-message integration.

You will obtain **three Slack values** (`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_TEAM_ID`) and place them in `.env.integrations`. The **ngrok authtoken** is saved by ngrok itself; the **HTTPS address + callback path** goes into Slack's slash-command **Request URL**. No channel ID, Employee/Manager user ID, OAuth Client Secret, or incoming-webhook URL needs to be pasted into this file. User IDs are verified through account linking later.

#### 1. Start the local application

Run `start.bat` and wait for startup to finish. Open the [local API health check](http://127.0.0.1:8000/api/v1/health); it should return `{"status":"ok","api_version":"v1"}`. Resolve local startup errors before proceeding.

These instructions use the default **API port 8000**, not frontend port 5173. If you started with `-ApiPort 8001`, replace `8000` with `8001` in the health-check address and tunnel command below.

#### 2. Install and authenticate ngrok

1. Open the [official Windows download page](https://ngrok.com/download/windows) and install ngrok using its Microsoft Store option. Open **Start → Windows PowerShell** in a new window; administrator mode is not needed. Run `ngrok version` to confirm that Windows can find it. If Store installation is unavailable, choose **Download** on the same page and extract the ZIP. Open that extracted folder in File Explorer, type `powershell` into its address bar, and press Enter; use `.\ngrok.exe` instead of `ngrok` throughout the steps below, including after a restart.
2. Sign in to the [ngrok dashboard](https://dashboard.ngrok.com/), complete account verification if requested, and open [Your Authtoken](https://dashboard.ngrok.com/get-started/your-authtoken). Copy the token value, not the entire example command. This is an **ngrok authtoken**, not a Slack token or ngrok API key.
3. Run the first line below on its own, paste the token at the prompt, and press Enter. Then run the remaining two lines. Input is hidden; the literal secret is not written into PowerShell command history. ngrok saves it in its own local configuration, outside the project. Keep that configuration private. See the [ngrok setup guide](https://ngrok.com/docs/start).

   ```powershell
   $ngrokToken = Read-Host "Paste your ngrok authtoken" -AsSecureString
   ngrok config add-authtoken ([System.Net.NetworkCredential]::new("", $ngrokToken).Password)
   Remove-Variable ngrokToken
   ```

   Wait for ngrok to report that the token was saved. If it reports an error, resolve it before continuing. Paste the commands themselves, without the Markdown fence lines beginning with three backticks.

#### 3. Obtain a public HTTPS address

In the same PowerShell window, paste this entire block. It writes a small policy file to `%LOCALAPPDATA%\PeopleFlow`, outside the repository. The policy allows **POST to the Slack callback** and **GET to the health check**; other paths and methods receive `404`. This keeps the demo login, requests, chats, and administration API out of this tunnel. The [ngrok custom-response action](https://ngrok.com/docs/gateway/traffic-policy/actions/custom-response) rejects blocked traffic before it reaches the application.

```powershell
$slackTunnelDir = Join-Path $env:LOCALAPPDATA "PeopleFlow"
New-Item -ItemType Directory -Path $slackTunnelDir -Force | Out-Null
@'
{
  "on_http_request": [
    {
      "expressions": [
        "!(req.method == 'POST' && req.url.path == '/api/v1/integrations/slack/commands') && !(req.method == 'GET' && req.url.path == '/api/v1/health')"
      ],
      "actions": [
        {
          "type": "custom-response",
          "config": { "status_code": 404, "body": "Not found" }
        }
      ]
    }
  ]
}
'@ | Set-Content -LiteralPath (Join-Path $slackTunnelDir "slack-tunnel-policy.json") -Encoding ASCII
ngrok http http://127.0.0.1:8000 --traffic-policy-file "$slackTunnelDir\slack-tunnel-policy.json" --inspect=false
```

Leave that window open. Wait for **Session Status: online**, then copy the HTTPS address on the **Forwarding** line, before `->`. For example, if it shows `https://your-assigned-name.ngrok-free.app -> http://127.0.0.1:8000`, copy only `https://your-assigned-name.ngrok-free.app`. Use your actual address, not this example or ngrok's local inspection address.

ngrok supplies the HTTPS certificate and an assigned development domain; you do not need to buy a domain for this demo. The assigned domain can be reused after restarting the agent, but the tunnel is reachable only while the agent and application are running. Free accounts have usage limits; see [ngrok's current free-plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits). The command disables local HTTP inspection to avoid retaining linking codes there; treat any provider-side traffic logs as private too. The policy and inspection flags are documented in the [ngrok CLI reference](https://ngrok.com/docs/gateway/agent/cli).

#### 4. Create the Slack app and configure its callback

1. Open [Slack App Management](https://api.slack.com/apps) → **Create New App**. Choose **Pick features** or **Blank app / From scratch**, depending on the creation screen, name it **PeopleFlow Demo**, and select your test workspace. If the wizard asks for scopes and events, you can leave those steps empty, continue to its review page, and create the app; accept **Create Anyway** if prompted, since the next step adds the required scopes. Keep it limited to that workspace; public app distribution is not required. See [Slack's app-creation guide](https://docs.slack.dev/app-management/quickstart-app-settings/).
2. Open **OAuth & Permissions → Bot Token Scopes** and add `chat:write`, `im:write`, and `commands`. These allow the bot to send messages, open direct conversations, and receive the slash command. Channel-history and message-reading permissions are not needed.
3. Open **Slash Commands → Create New Command** and fill in:

   | Field | Value |
   |---|---|
   | Command | `/peopleflow` |
   | Request URL | Your HTTPS Forwarding address followed by `/api/v1/integrations/slack/commands` |
   | Short Description | `Link your PeopleFlow account` |
   | Usage Hint | `link <code>` |

   For the example domain above, the complete Request URL is `https://your-assigned-name.ngrok-free.app/api/v1/integrations/slack/commands`. Keep the exact path, with no trailing slash. Click **Save**. This belongs in the command's **Request URL**, not an OAuth Redirect URL, Events API URL, or Interactivity URL. PeopleFlow checks Slack's signature on each command. See [Slack's command configuration](https://docs.slack.dev/interactivity/implementing-slash-commands/) and [request verification](https://docs.slack.dev/authentication/verifying-requests-from-slack/).
4. Under **App Home**, enable the **Messages Tab** and **Allow users to send Slash commands and messages from the messages tab** if that option is shown. This makes it possible to enter the linking command in a private conversation with the app. Ordinary messages are not processed as chatbot questions; use `/peopleflow`. See [Slack's App Home guide](https://docs.slack.dev/surfaces/app-home/).
5. Under **OAuth & Permissions**, choose **Install to Workspace** and approve the permissions. Reinstall if you later change scopes. Leave **Socket Mode**, **Event Subscriptions**, and **Interactivity** off for this integration.

#### 5. Add the Slack credentials locally

Find these three values for **the same Slack app and workspace**:

| Project setting | Where to obtain it |
|---|---|
| `SLACK_BOT_TOKEN` | **OAuth & Permissions → Bot User OAuth Token**, available after installation; starts with `xoxb-`. Do not use a user token, app-level token, or webhook URL. |
| `SLACK_SIGNING_SECRET` | **Basic Information → App Credentials → Signing Secret → Show**. Do not use Client Secret or the deprecated Verification Token. |
| `SLACK_TEAM_ID` | Open that workspace in a browser. In `https://app.slack.com/client/T12345678/C12345678`, copy the `T12345678` segment. Use the workspace's `T…` ID, not a channel `C…`, user `U…`, or Enterprise organization `E…` ID. See [Slack's ID instructions](https://slack.com/help/articles/221769328-Locate-your-Slack-URL-or-ID). |

Open **`.env.integrations` in the project root**, beside `start.bat`, and fill in these lines. Preserve any existing Discord settings and replace existing Slack values rather than adding duplicate keys. The main `.env` still contains only its five core settings.

```dotenv
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
SLACK_TEAM_ID=
```

Paste each real value after `=`; do not include angle brackets, spaces, or the field name from Slack. Save the file as `.env.integrations`, not `.env.integrations.txt`. In File Explorer, enable **View → Show → File name extensions** (Windows 11) or **View → File name extensions** (Windows 10) to check the actual filename. Keep it private and out of Git. Run `stop.bat`, then `start.bat` so the API loads the new settings. **Leave ngrok running.** Neither the ngrok domain nor its authtoken belongs in these three settings.

In PeopleFlow, sign in as **Knowledge Admin** with the same generated `DEMO_LOGIN_PASSWORD` used for Employee, then open **Integrations**. Before linking accounts, check that the Slack card says **Ready to enable personal delivery** and **Disabled**. If Slack was already enabled in an existing installation, click its **Disable** button first; do not change Discord's setting. **Server setup is required** means the configuration was not loaded or is incomplete: check the filename, the three values, and the restart. This local readiness check does not yet prove that Slack accepts the token.

#### 6. Verify the callback, then link and test both recipients

Leave the ngrok window running and open **a second PowerShell window** using Start. Paste the HTTPS **base address only** at the prompt, without the callback path. These checks do not link accounts or send notifications:

```powershell
$slackBaseUrl = (Read-Host "Paste the HTTPS Forwarding address only").Trim().TrimEnd("/")
curl.exe -i --max-time 15 -H "ngrok-skip-browser-warning: 1" "$slackBaseUrl/api/v1/health"
curl.exe -i --max-time 15 -X POST "$slackBaseUrl/api/v1/integrations/slack/commands"
curl.exe -i --max-time 15 -H "ngrok-skip-browser-warning: 1" "$slackBaseUrl/docs"
```

Expected results, in order:

1. **HTTP 200** and `{"status":"ok","api_version":"v1"}`: ngrok reaches the local API.
2. **HTTP 401** and `Invalid Slack request signature.`: the callback is reachable and rejects an unsigned request. This is expected; only a genuine Slack command supplies the required signature.
3. **HTTP 404** and `Not found`: the policy blocks API documentation. Opening the callback in a browser also returns `404`, because a browser sends GET and the callback accepts POST through this tunnel. If `/docs` returns the application documentation instead, stop ngrok with **Ctrl+C** and restart it with the policy from step 3 before proceeding.

Now open Slack → **Apps → PeopleFlow Demo → Messages**, in the workspace where you installed the app. If Apps is not visible, open Slack's **More** menu to find it and search for your app's name. Send **`/peopleflow` without arguments** in the main message box, not inside a thread. Expect a private reply directing you to generate a code in **Personal notifications**. This confirms that a signed command reaches PeopleFlow; it does not create a request or link an account. A green health check alone does not verify this step.

Next follow [Link accounts without enabling notifications](#link-accounts-without-enabling-notifications) below, once for Employee and once for Manager. You can stop after both show **Connected**, leaving Slack **Disabled**. To verify real delivery later, follow the separate [Test actual delivery](#test-actual-delivery--sends-real-messages) steps; those buttons send real direct messages.

Connection is fully checked only when **the signed command, account confirmation, and actual direct-message delivery all succeed**. Automated mocks and a successful HTTP health check are separate checks, not evidence of real delivery.

#### 7. Restarting, links, and stopping

- Keep the application and ngrok running during Slack tests. After restarting Windows, run `start.bat`, open PowerShell, and repeat these two lines; the policy and ngrok authtoken remain saved:

  ```powershell
  $slackTunnelDir = Join-Path $env:LOCALAPPDATA "PeopleFlow"
  ngrok http http://127.0.0.1:8000 --traffic-policy-file "$slackTunnelDir\slack-tunnel-policy.json" --inspect=false
  ```

- Compare the new **Forwarding** address with the Slack command's **Request URL**. If the public address changed, update that URL in Slack and save it. If only the local API port changed, update the ngrok command's upstream port. Existing confirmed account links survive either change.
- **Request links and callbacks use different addresses.** This restricted tunnel does not publish the frontend. Leave `APP_PUBLIC_URL` unchanged for a demo used on this computer. Do not set it to the API-only ngrok address; it would produce unusable request links. To open requests from another device, provide a separately reachable frontend and configure `APP_PUBLIC_URL` as described below. A company deployment needs a maintained HTTPS endpoint and proper authentication, not this local demo setup.
- To stop, press **Ctrl+C** in the ngrok window and use **`stop.bat`** for PeopleFlow. Stopping does not remove saved requests, chats, or account links; Slack commands are unavailable until both services are running again.

#### Slack troubleshooting

| Symptom | What to check and how to continue |
|---|---|
| `ngrok` is not recognized | Reopen PowerShell after installation. For a standalone download, open its folder in PowerShell and use `.\ngrok.exe` in place of `ngrok`. |
| ngrok reports authentication failure or an account/usage limit | Complete account verification, repeat the authtoken step using **Your Authtoken**, and check the dashboard's usage or running endpoints. Keep the token out of screenshots. |
| `ERR_NGROK_9040` | ngrok is refusing the connection from the current public IP; retyping the Slack callback will not fix it. Follow [ngrok's explanation and support options](https://ngrok.com/docs/errors/err_ngrok_9040). If the service is unavailable to you, this ngrok walkthrough cannot be completed; use an organization-provided HTTPS endpoint with the same callback path and route restrictions. |
| Unknown `--traffic-policy-file` flag / policy rejected | Install the current ngrok agent from its official download page and copy the entire policy block again. Do not remove the policy option to make the command run: that would expose other API routes. |
| Endpoint offline / tunnel cannot connect / HTTP 502 | Keep ngrok open and the PC awake. Check the local health URL first, then match ngrok's upstream port to the API port. Check VPN/proxy connectivity if ngrok cannot reach its service. |
| HTTP 404 for the command | Check the exact path and policy file. Use the full callback path in Slack and send a slash command; opening the URL in a browser is not a POST test. |
| HTTP 401 for a real Slack command | Check the Signing Secret, `xoxb-` token, and workspace ID; all three are required for the integration to be configured. Restart PeopleFlow after editing the file. Sync Windows date/time; signatures older than five minutes are rejected. Do not disable signature checks. An unsigned `curl.exe` POST returning 401 is normal. |
| HTTP 403 for a Slack command | `SLACK_TEAM_ID` must match the workspace where the command was sent, and the command name must be exactly `/peopleflow`. Correct the setting and restart. |
| Command not found / message entry disabled / command not supported in threads | Install or reinstall the app in the correct workspace; enable the App Home Messages Tab and its command-entry option. Use the main Messages composer, not a thread or split-view reply. If another installed app owns `/peopleflow`, resolve that conflict in the test workspace. |
| `dispatch_failed` / timeout | Repeat the public health check and check `.demo_logs/api.err.log`. Slack expects an acknowledgement within three seconds; the API and tunnel must be running and reachable. See [Slack's response timing](https://docs.slack.dev/interactivity/implementing-slash-commands/). |
| Connect Slack is disabled / server setup is required | Check `.env.integrations` has no `.txt` suffix, includes all three Slack settings, and is next to `start.bat`. Restart PeopleFlow and refresh connections. Knowledge Admin configures delivery; only Employee and Manager have the personal Connect button. |
| Code expired / HTTP 429 when generating a code | Wait at least 30 seconds after the previous code generation, then click **Generate new Slack code** (or **Connect Slack** if the old code is no longer displayed). Send the latest command and confirm in PeopleFlow within ten minutes of generating it; a new code invalidates the older one. |
| Unexpected account ID / account already linked elsewhere | Do not confirm an ID belonging to the wrong person. Switch to the intended Slack account, generate a new code in the correct PeopleFlow role, and retry. If an incorrect link was already confirmed, use **Disconnect Slack → Confirm disconnect Slack** from that PeopleFlow role first. Requests and chats are preserved. |
| Linking works, but no test DM arrives | In Admin → Integrations, enable Slack, confirm the intended recipient is linked, and inspect Delivery activity. Check `chat:write` and `im:write`, reinstall after scope changes, and save the current Bot User OAuth Token before restarting. See [Slack direct-message requirements](https://docs.slack.dev/reference/methods/conversations.open/). |
| A browser shows an ngrok warning page | Use the supplied `curl.exe` health command with its warning-skip header. ngrok's browser warning is separate from the application's response; API clients are covered by its [programmatic-access guidance](https://ngrok.com/docs/pricing-limits/free-plan-limits#removing-the-interstitial-page). |
| The notification arrives, but its request link fails | Use the frontend address on the computer running PeopleFlow, or configure a reachable frontend and `APP_PUBLIC_URL`. The callback-only tunnel intentionally blocks website pages. |

### Link Employee/Manager accounts and test delivery

#### Link accounts without enabling notifications

Complete the chosen service's server setup above first. Use these two account pairings; the external accounts must be different people/accounts, not two display names for the same login:

| PeopleFlow sign-in role | External account that runs the command |
|---|---|
| **Employee** (`Demo Employee`) | Your Employee test account in Slack or Discord |
| **Manager** (`Demo Manager`) | A different Manager test account in the same Slack workspace or Discord test server |

1. In PeopleFlow, select **Employee** on the sign-in page and use `DEMO_LOGIN_PASSWORD` from this copy's `.env`. To switch from another role, open the avatar/name at the top right (**Account and appearance**) → **Sign out**, then select Employee. This password is for PeopleFlow only; use each service's own login for Slack/Discord.
2. Open **Personal notifications** at the bottom of the left navigation. On a narrow screen, open the top-left **Open menu** button first. Check the panel says **Signed in as Demo Employee (employee)**, then click **Connect Slack** or **Connect Discord** on the intended service card. Delivery may remain disabled.
3. Select and copy the **whole command** displayed in the read-only box. In Slack, sign in as the Employee test account and paste it into the bot's main **Messages** composer: `/peopleflow link <code>`. In Discord, use the bot's direct conversation and `/peopleflow link code:<code>`. Replace `<code>` with the generated value without angle brackets; copying the displayed command does this for you. Do not add `code:` to the Slack command, and do not post the code in a channel or thread.
4. The bot should reply **Account identity received**, with instructions to return to the app. In PeopleFlow, click **I linked it — refresh** or the panel's **Refresh** button. The card should show **Awaiting your confirmation** and the external account ID. This is not yet a completed connection.
5. Verify the ID belongs to the intended external account using the instructions below. If it differs, do not confirm: switch to the correct external account and generate a fresh code in PeopleFlow. If it matches, click **Confirm my Slack account** or **Confirm my Discord account**. Complete both the command and web confirmation within ten minutes of generating the code.
6. Success means the card now shows **Connected** and the expected **Connected account ID**. Close and reopen Personal notifications to check it persists. The disabled-delivery notice and a disabled **Send Slack/Discord test to me** button are normal while the administrator has delivery off. No test notification is sent by linking or confirming.
7. Sign out of PeopleFlow as described in step 1, select **Manager**, and use the same demo password. Sign in to Slack/Discord as the **different Manager test account**, then repeat steps 2–6; the PeopleFlow panel must now say **Signed in as Demo Manager (manager)**. One external account cannot be linked to both demo roles. Work through the roles one at a time; use separate browser profiles if you need both external accounts signed in simultaneously.
8. Sign out and sign in as **Knowledge Admin** with the same demo password → **Integrations**. Under the service's **Recipients**, both **Employee** and **Manager** should show **Connected**. Keep the service **Disabled** and do not click **Send test** if you only want to check linking. Knowledge Admin manages delivery; it does not need a personal bot account.

**How to verify your external account ID before confirming:**

| Service | Where to copy your own ID |
|---|---|
| Slack | Open **your own profile → More (⋯) → Copy member ID** and compare it with PeopleFlow. See [Slack's user-ID instructions](https://docs.slack.dev/surfaces/app-home/). Use your own account, not the bot's profile. |
| Discord | Enable **User Settings → Advanced → Developer Mode**. In the test server's member list, right-click your own account → **Copy User ID**; on mobile, open your own profile → **⋯ → Copy User ID**. Compare the numeric ID with PeopleFlow. Your display name, the bot's Application ID, and the server ID are different values. See [Discord's ID instructions](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID). |

#### Test actual delivery — sends real messages

These steps are optional for checking account links, but necessary to prove real delivery. Use your designated test accounts and a new test request; leave existing working requests unchanged.

1. Knowledge Admin → **Integrations**: click **Enable** on only the service you are testing. Both intended recipients should already be **Connected**. Slack and Discord are controlled independently; leave the other service unchanged.
2. In that service's **Employee** recipient row, click **Send test** once. Open **Delivery activity** and wait for `delivered`; **Test notification accepted** only means it was queued. Verify the message appears in the Employee account's direct conversation with the bot and not in the Manager account or a public channel. If it is `pending` or `failed`, check the displayed error rather than repeatedly clicking the test button.
3. Repeat in the **Manager** row and inspect the Manager account's direct conversation. A personal **Send Slack/Discord test to me** button is also available in each role's Personal notifications; it is an alternative test, not an additional required step.
4. Create a dedicated test request as Employee: the assigned Manager receives a notification. Their **Request information** action notifies Employee; the Employee's response notifies Manager. **Approve/Reject/Complete do not automatically notify Employee**. Check the request link while signed into PeopleFlow with the appropriate role; another role's session may correctly be denied access.
5. If notifications were enabled only for this check, return to Knowledge Admin → **Integrations** and **Disable** the tested service. Confirmed links remain saved.

Account linking works even when delivery is disabled. A missing recipient is never replaced by a public channel or another user. Delivery failures do not undo a saved request or decision; calls have a 10-second timeout and a maximum of five attempts. Enabling delivery does not replay old events. Disabling cancels queued work, but an in-flight send may finish. Check **Delivery activity** for status. Exactly-once delivery by an external service cannot be guaranteed.

For links that open on other devices, add `APP_PUBLIC_URL=https://YOUR-FRONTEND` to **`.env.integrations`**: use the reachable frontend address, not the API callback. `start.bat` supplies the local frontend port automatically. `127.0.0.1` works only on the computer running the server; setting `APP_PUBLIC_URL` does not publish the site to the network by itself.

## Stack and project structure

Backend: Python, FastAPI, Uvicorn, Pydantic, SQLite; the OpenAI SDK and RAG with a local JSON index and lexical/vector search. Frontend: React 19, TypeScript, Vite 8, Tailwind CSS 4, React Router, TanStack Query, Radix UI. Discord Gateway: discord.py. Tests: pytest, Vitest, React Testing Library. Versions are pinned in `requirements*.txt` and `frontend/package-lock.json`.

```text
app.py                 FastAPI application and lifecycle
api/                   /api/v1 routes, schemas, and authentication
core/                  Settings and defaults
domain/                Request models, rules, and transitions
services/              Chat, request, document, and notification workflows
storage/               SQLite, migrations, documents, and file stores
integrations/          OpenAI, Slack/Discord, transport, and Gateway
rag/                   Indexing, retrieval, context, and AI instructions
frontend/src/          Interface, shared components, and role workspaces
documents/             Demo documents, catalog, and uploaded sources
data/                  Local data; only .gitkeep belongs in source control
tests/                 Backend tests with temporary databases and mocked integrations
evals/                 Questions for retrieval evaluation
scripts/               Environment setup, processes, checks, and bot commands
tools/                 Demo document utilities
docs/                  Separate technical references
start.bat / stop.bat    Start and stop on Windows
run_demo.ps1            Dependency installation and server management
README.md              Single setup and startup guide
```

Requests, assignments, history, attachments, users, chats, and account links are stored in **`DATA_DIR/workflow.db`**. Schema creation and migrations run automatically. The index, AI settings, and JSONL logs are stored alongside it; source documents live in `documents/`. Restarting does not clear data. To back up, stop the application and save the complete `DATA_DIR`, `documents/`, and configuration with restricted access, including when using the older `DATA_DIR=.demo_state` location.

`Dockerfile` builds **only the API**, without the frontend. This is a separate deployment method requiring its own secrets, persistent data/document volumes, and a separately running frontend. The `start.bat` instructions do not use Docker.

## Tests and build

Run from the project root after preparing `.venv` and frontend dependencies. If you have only used `start.bat`, the first command adds the test dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m scripts.run_rag_eval
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

`pytest` uses a temporary database, disables local env files, and mocks external integrations. RAG evaluation runs without embeddings/OpenAI. Mocks **do not verify real Slack/Discord delivery**; test that separately using the buttons described above. The build output is placed in `frontend/dist/`.

Post-startup check: Employee → Create request → save a draft → reopen and submit → Manager → Start review → decide with an explanation → Employee → check the decision and history. See the [demo scenarios](DEMO_SCENARIOS.md) for more detail.

## Troubleshooting

| Symptom | Solution |
|---|---|
| Python / Node.js / npm not found | Install the required versions with PATH support, then reopen `start.bat`. |
| PowerShell blocks `.ps1` or `npm.ps1` | Use `start.bat`, `stop.bat`, and `npm.cmd`; do not disable the system-wide execution policy. |
| Dependency installation fails | Check PyPI/npm access and your VPN/proxy; run `.\start.bat -InstallDeps` in PowerShell from the project root. Do not delete `.env` or data. |
| Frontend dependency is locked / npm `EPERM` or `EBUSY` | Close development/preview servers using this project's `frontend/node_modules`, including servers on other ports. `stop.bat` stops servers started by the launcher; stop manually started servers in their own terminals with Ctrl+C. Retry `start.bat` to repair an interrupted installation. Do not delete `.env` or data, stop unrelated Node processes, or disable antivirus protection. |
| Port already in use | Stop the previous instance by double-clicking `stop.bat`, or run `.\start.bat -ApiPort 8001 -UserUiPort 5174`. Open the address printed by the launcher: this example runs the UI on port 5174. Unrelated processes are not stopped. |
| Only one server is running | Run `.\start.bat -ForceRestart`; see `.demo_logs/api.err.log` and `.demo_logs/frontend.err.log` for details. |
| Password rejected / session expired | Use `DEMO_LOGIN_PASSWORD` from this copy's `.env`, without quotes. Restart and sign in again after changing settings. A password from an older test copy is not universal. |
| Too many sign-in attempts (HTTP 429) | Wait one minute before trying again. The API allows up to ten unsuccessful or concurrent attempts per client in a rolling minute; changing the role does not reset the limit. Successful sign-ins release their attempt slot. |
| Request is too large (HTTP 413) | Reduce the payload. The API accepts up to 8 KiB for login, 256 KiB for other JSON requests, and 12 MiB including multipart overhead; documents still have a 10 MiB file limit and request attachments a 5 MiB file limit. |
| `DEMO_AUTH_SECRET` error | Stop the application, clear only the `DEMO_AUTH_SECRET` value in `.env`, preserve the other settings, and run `start.bat` to generate a new secret. Alternatively, set a random secret of at least 32 characters manually. Sign in again after changing it. Do not delete `.env` or data. |
| `Both data and .demo_state contain data` / conflicting paths | Back up first, then explicitly select the existing `DATA_DIR`. Do not delete databases to hide the error. |
| `Custom setting ... cannot be removed automatically` | Move bot settings to `.env.integrations` and other advanced settings to the process environment, preserving their values. Keep the main `.env` limited to five variables. |
| UI cannot reach the API | Check `/api/v1/health`, logs, and ports. Both terminals must remain running in manual mode; match `VITE_API_URL` and `CORS_ORIGINS` when using different ports. |
| No AI answer / invalid key / OpenAI limit | Local mode works without a key. Check the API project's key, access, quota, and `OPENAI_MODEL`, then restart. Access to generation does not guarantee access to embeddings. |
| Source changed, but answers have not | Knowledge Admin → Documents → Index document / Re-index; check the document status and logs. |
| Discord: `Application did not respond` | The API must be running; Interactions Endpoint URL must be empty for Gateway. Check Token/Application ID and VPN/proxy access, then restart. |
| Discord: `direct_messages_disabled` | Check that you share a server with the bot, allow direct messages, and have not blocked the bot. |
| `recipient_unlinked` / no notifications | Confirm the external ID in Personal notifications; separately enable the service in Admin → Integrations and check Delivery activity. |
| Slack does not accept the command | Follow [Slack troubleshooting](#slack-troubleshooting) to distinguish tunnel, signature, workspace, and account-linking errors. |
| Notification link does not open on a phone | Configure a reachable frontend and `APP_PUBLIC_URL`: `127.0.0.1` on a phone refers to the phone itself. |

Discord supports the system HTTPS proxy and `HTTPS_PROXY`/`NO_PROXY`; restart the application after changing VPN/proxy settings. Do not disable TLS verification to work around network errors.

## Protecting secrets and demo limitations

- **Do not commit or publish** `.env`, `.env.integrations`, keys, bot tokens, signing secrets, linking codes, databases, logs, or backups; do not expose them in screenshots. `.gitignore` and `.dockerignore` exclude local configuration and runtime data; `.env.example` contains no secrets.
- `.gitignore` does not remove a previously committed file from history. If a secret is exposed, revoke it with the provider, generate a replacement, and separately clean up published material and Git history.
- Only `.gitkeep` belongs in the source-controlled `data/` folder. Keep `.demo_state`, `.demo_logs`, `.tmp*`, installed dependencies, and build output out of the repository.
- When using OpenAI, questions, saved context, and document excerpts are sent to the API. Personal notifications send limited information to the designated recipient. Use synthetic data for the demo.
- Three predefined roles with a shared password are **demo authentication**, not SSO or individual corporate accounts. Do not publish this local setup as a production-ready corporate system. Tenant isolation and document-level permissions are not implemented.
- There is **no self-registration, password recovery, per-user password, MFA, or server-side session revocation**. Selecting a card fills a demo username; everyone given the shared password can sign into any demo role. Employee/Manager access checks are enforced against the server-issued identity, but these accounts do not establish a real employee's identity.
- `start.bat` runs the API and Vite development server on loopback for a supervised local demonstration. It is not an internet deployment. HTTP request limits and a bounded in-process login throttle protect the demo; they do not replace a production gateway, TLS, or shared rate limiting. All documented server commands (launcher, manual startup, Docker, and smoke check) use `--no-proxy-headers` so a caller cannot bypass the local throttle by changing `X-Forwarded-For`. Keep this flag when copying the commands. Behind a reverse proxy, the local throttle sees the proxy as one client; enforce suitable rate limiting at the gateway.
- Request rules provide transparency, consistent criteria, and reconsideration; the project does not claim legal compliance with the US Constitution or other laws and regulations.

### Before a real deployment

The project can demonstrate workflows with synthetic data and serve as an implementation starting point. A deployment handling real employees or HR data still needs:

1. An approved identity provider (OIDC/SSO), individual accounts, administrator-managed roles, MFA and session revocation. Remove demo account selection from the deployed authentication flow.
2. Organization and document access rules enforced in storage and retrieval, including isolation between customers if hosting more than one organization.
3. A production frontend host and API gateway with HTTPS, trusted proxy configuration, shared rate/resource limits, security headers, and restricted infrastructure access. Do not expose Vite to the internet.
4. Tested backup **and restore**, retention/deletion policies, monitoring, recovery procedures, and secrets management. SQLite is adequate for this single-instance demo; evaluate concurrency and multi-instance requirements before choosing deployment storage.
5. Approval for the data sent to OpenAI/Slack/Discord; a pilot with real user accounts, assistive technology, target devices, realistic load and failure/recovery scenarios. Automated tests and browser emulation do not establish these outcomes.

Run dependency audits again before release: `npm.cmd --prefix frontend audit` and, in a separate audit environment, `python -m pip_audit -r requirements.txt`. A clean advisory scan is a point-in-time check, not a guarantee that software is vulnerability-free.
