# Slack request notifications

PeopleFlow sends demo request notifications to the public `#hr-requests-demo`
channel. A separate channel keeps workflow events out of general conversation
and makes the integration easy to demonstrate. Use a private channel instead
before sending real employee data.

Slack is a notification surface only. The application and its SQLite workflow
database remain the source of truth for request status.

## Events

Notifications are sent after these persisted status changes:

- `draft` to `in_review`: new request
- `in_review` to `approved`: final approval
- `in_review` to `declined`: final decline

Draft creation does not notify Slack. Cancelling a request does not currently
notify Slack.

Each English message includes the request ID, type, dates, employee, current
status, and an **Open in Web** button. The button opens:

```text
<PUBLIC_WEB_BASE_URL>/manager?request=<request-id>
```

If Slack is unavailable, the saved workflow transition and the Web response
still succeed. The integration logs a redacted warning and does not log the
webhook URL.

## Configure an Incoming Webhook

1. Go to [Slack API apps](https://api.slack.com/apps) and create an app for the
   `HR-Bot Slack` workspace.
2. Enable **Incoming Webhooks**.
3. Add a webhook to the `#hr-requests-demo` channel.
4. Copy the generated webhook URL directly into the local `.env` file. Never
   paste it into source code, documentation, chat, or Git.
5. Set the following values:

```dotenv
SLACK_NOTIFICATIONS_ENABLED=true
SLACK_WEBHOOK_URL=<your-local-secret>
SLACK_TIMEOUT_SECONDS=3
PUBLIC_WEB_BASE_URL=http://127.0.0.1:5173
```

The incoming webhook is bound to the selected channel, so the application does
not need a Slack channel ID or a bot token.

For a local demo, the **Open in Web** button works on the same computer where
the React frontend is running. Replace `PUBLIC_WEB_BASE_URL` with a reachable
HTTPS URL when the application is deployed.

## Disable notifications

Set:

```dotenv
SLACK_NOTIFICATIONS_ENABLED=false
```

No Slack request is attempted when notifications are disabled.

## Verification

1. Start the application.
2. Log in as `employee` and create a draft. Confirm that Slack stays unchanged.
3. Submit the request. Confirm that Slack shows `IN REVIEW`.
4. Use **Open in Web**, log in as `manager`, and open the exact request.
5. Approve or decline it. Confirm that Slack shows the final status.
6. Temporarily use an invalid local webhook value and confirm that the request
   still changes status in Web.
