# Connect Slack

## 1. Create and install the app

Open [Slack apps](https://api.slack.com/apps) → **Create New App → From a manifest**. Choose your workspace and paste [manifest.json](manifest.json) into the JSON tab. Create the app, then open **OAuth & Permissions → Install to Workspace** and allow access. The manifest sets up Socket Mode and the required permissions.

## 2. Fill in the root `.env`

Open the project's [START.bat](../START.bat) and choose **8**. Fill in these five fields in the shared root `.env`:

| Field | Where to get it |
| --- | --- |
| `SLACK_BOT_TOKEN` | App settings → **OAuth & Permissions → Bot User OAuth Token** (`xoxb-…`). |
| `SLACK_APP_TOKEN` | App settings → **Basic Information → App-Level Tokens → Generate Token and Scopes**. Add `connections:write`, generate and copy the `xapp-…` token. [Token setup help](https://docs.slack.dev/tools/bolt-python/creating-an-app/). |
| `SLACK_APP_ID` | App settings → **Basic Information → App ID** (`A…`). |
| `SLACK_TEAM_ID` | Open your workspace in a browser: copy the `T…` part of `app.slack.com/client/T…/…`. [Workspace ID help](https://slack.com/help/articles/221769328-Locate-your-Slack-URL-or-ID). |
| `SLACK_EMPLOYEE_USER_ID` | In Slack, open the demo employee's profile → **More → Copy member ID**. This member uses PeopleFlow's Employee account. [Member ID help](https://slack.com/help/articles/360003827751-Create-a-link-to-a-members-profile). |

## 3. Connect

Save `.env`, choose **2** in the launcher to restart, then **10** to check the connection. Open **PeopleFlow AI → Messages** in Slack. Keep PeopleFlow running while using the bot.

For everyday use and launcher controls, see the [main README](../README.md#4-connect-slack-optional).
