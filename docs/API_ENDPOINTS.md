# API v1 Contract

The React-facing API is versioned under `/api/v1`. Application endpoints require
`Authorization: Bearer <token>` except for health and login. Provider callbacks use
Slack/Discord signatures instead of application Bearer tokens, as described below.

For setup, startup, environment variables and bot connection steps, use the root
[README](../README.md). `/docs` on the running API provides the generated schemas.

## Notification integrations

The following administrator endpoints require `knowledge_admin`; successful responses return `Cache-Control: no-store`.
Credentials are supplied only through the server environment or ignored `.env.integrations`.

| Method | Endpoint | Result |
| --- | --- | --- |
| GET | `/api/v1/admin/integrations` | Configuration presence, enabled flags, revisions, queue sizes and sanitized `active_delivery` / `last_delivery` status (nullable). Never webhook URLs or tokens. |
| PATCH | `/api/v1/admin/integrations/{slack\|discord}` | `{ "enabled": true, "expected_revision": 0 }`; returns updated overview. Stale revisions return 409. |
| POST | `/api/v1/admin/integrations/{slack\|discord}/test` | JSON `{ "audience": "employee" }` or `{ "audience": "manager" }`; an empty JSON object defaults to Manager. Queues a sample for a linked recipient on an enabled, configured provider. 202 means queued, not delivered. At most one test per provider and recipient per 30 seconds (429 otherwise). |

Personal endpoints below require Employee or Manager; they only operate on the signed-in
user's connection. `{provider}` is `slack` or `discord`.

| Method | Endpoint | Result |
| --- | --- | --- |
| GET | `/api/v1/me/integrations` | Connection state and pending provider identity, without credentials. |
| POST | `/api/v1/me/integrations/{provider}/link-code` | Issue an expiring code and linking command; no role selection. |
| POST | `/api/v1/me/integrations/{provider}/confirm` | JSON `{ "challenge_id": "<32-character challenge ID>" }`; confirm a provider identity already received for this user's challenge. |
| DELETE | `/api/v1/me/integrations/{provider}` | Disconnect this user's personal destination. |
| POST | `/api/v1/me/integrations/{provider}/test` | Queue a sample only to this user's linked destination; 202 is not delivery confirmation. |

Provider-facing callbacks do not accept application roles or channel destinations:

| Method | Endpoint | Authentication |
| --- | --- | --- |
| POST | `/api/v1/integrations/slack/commands` | Slack signing secret, timestamp, signature and configured workspace ID. |
| POST | `/api/v1/integrations/discord/interactions` | Discord Ed25519 signature and timestamp for the configured application; used in optional HTTP mode. |

Discord Gateway is the default command transport and does not need an incoming HTTP callback.
Both providers support account linking only; request creation and decisions remain in the web UI.

Notification links use `/requests?request=<id>`. Login preserves the link for Employee
and Manager; normal request authorization applies. Enabling does not replay prior events;
disabling cancels the queue but cannot retract an in-flight delivery. Provider errors are
reported as safe categories. A notification-storage failure returns 503 without affecting
request endpoints.

Employee receives only a request for additional information. Manager receives permitted events
for assigned requests: submission, Employee reply, reconsideration, assignment and cancellation.
Other status changes do not generate Employee notifications. A missing personal connection does
not fall back to a channel or another account.

## Demo Authentication

`POST /api/v1/auth/login`

```json
{
  "username": "employee",
  "password": "<your DEMO_LOGIN_PASSWORD>"
}
```

Available predefined accounts are `employee`, `manager`, and
`knowledge_admin`. The password comes from `DEMO_LOGIN_PASSWORD`. Tokens are
HMAC-signed, expire after `DEMO_TOKEN_TTL_SECONDS`, and resolve to server-owned
identities. `X-User` and arbitrary user IDs are not accepted.

## Core Routes

| Method | Path | Role |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Public |
| `POST` | `/api/v1/auth/login` | Public |
| `POST` | `/api/v1/chat` | Employee; compatibility endpoint |
| `POST` | `/api/v1/chat/stream` | Employee; compatibility NDJSON endpoint |
| `GET` | `/api/v1/me` | Authenticated |
| `GET/POST` | `/api/v1/conversations` | Employee; list/search own conversations or create one |
| `GET/PATCH/DELETE` | `/api/v1/conversations/{id}` | Employee conversation owner; read, rename or delete |
| `POST` | `/api/v1/conversations/{id}/messages/stream` | Employee conversation owner; persisted NDJSON response |
| `GET` | `/api/v1/request-options` | Employee, Manager; shared procedure and options |
| `GET/POST` | `/api/v1/requests` | Scoped list / Employee creates draft |
| `GET` | `/api/v1/manager/overview` | Manager; metrics and attention counts scoped to assigned requests |
| `GET` | `/api/v1/manager/activity` | Manager; scoped journal, `limit` and `offset` |
| `POST` | `/api/v1/manager/bulk-start-review` | Manager; begin review of selected assigned requests, with per-item results |
| `GET` | `/api/v1/requests/{id}` | Author or assigned Manager; drafts are author-only |
| `PATCH` | `/api/v1/requests/{id}` | Author; draft content only |
| `POST` | `/api/v1/requests/{id}/submit` | Author; Draft → Submitted |
| `POST` | `/api/v1/requests/{id}/actions/{action}` | Role and lifecycle checks described below |
| `POST` | `/api/v1/requests/{id}/comments` | Author or assigned Manager |
| `POST` | `/api/v1/requests/{id}/assign` | Assigned Manager; active requests, reason required |
| `POST` | `/api/v1/requests/{id}/attachments` | Participants; active requests; multipart upload |
| `GET` | `/api/v1/requests/{id}/attachments/{attachment_id}` | Participants; authenticated download |
| `GET` | `/api/v1/documents` | Knowledge Admin |
| `POST` | `/api/v1/documents` | Knowledge Admin |
| `GET` | `/api/v1/documents/{id}/download` | Knowledge Admin |
| `DELETE` | `/api/v1/documents/{id}` | Knowledge Admin |
| `POST` | `/api/v1/documents/{id}/index` | Knowledge Admin |
| `POST` | `/api/v1/feedback` | Employee |
| `GET` | `/api/v1/admin/feedback` | Knowledge Admin |
| `GET` | `/api/v1/admin/unanswered` | Knowledge Admin |
| `POST` | `/api/v1/admin/quality/{id}` | Knowledge Admin |
| `GET/PUT` | `/api/v1/admin/ai-settings` | Knowledge Admin |
| `POST` | `/api/v1/admin/ai-settings/test` | Knowledge Admin |
| `GET` | `/api/v1/admin/metrics` | Knowledge Admin |
| `GET/PUT` | `/api/v1/admin/system-prompt` | Knowledge Admin |
| `GET` | `/api/v1/admin/logs` | Knowledge Admin |

Both the web UI and saved-chat API are Employee-only and owner-scoped. Manager/Admin receive
HTTP 403 for every conversation operation and both compatibility chat endpoints, even for
their own historical conversations. Existing records are preserved. The separate Knowledge
Admin AI settings preview remains available without creating or modifying saved conversations.

Conversation list queries accept `q`, `limit` (1–100) and `offset`. Creation accepts optional
UUID `id` and `title`; rename accepts `title`. Sending uses `{ "content": "...", "request_id": "<UUID>" }`;
reuse the same request ID for a retry of the same message. Context is loaded from saved messages,
not trusted client-provided history. Compatibility chat endpoints accept `conversation_id` for
continuation; omitting it starts a new conversation. A pending turn prevents conflicting sends
or deletion until completed or retryable.

Document uploads accept `.md`, `.txt`, `.pdf`, and `.docx` files up to 10 MB.
Deletion rebuilds the RAG index and is rolled back if the index cannot be refreshed.

Assistant feedback stores the rated question and answer. The admin feedback route
returns those conversation fields, rating, optional note, and timestamp without a
user identifier.

The unanswered route returns only supported workplace questions that received no
reliable document-backed answer. Invalid and out-of-scope prompts are excluded.
Quality items can be marked `resolved` or `ignored`, which removes them from the
active queue and its dashboard count.

AI settings expose six boolean controls: strict grounding, concise answers,
clarifying questions, suggested next steps, source visibility, and automatic
indexing after upload. The test endpoint accepts an unsaved settings payload and
system prompt, runs a real answer preview, and deliberately disables workflow
creation and chat logging.

## Request Example

`POST /api/v1/requests`

```json
{
  "type": "pto",
  "title": "Family vacation",
  "priority": "normal",
  "start_date": "2030-04-10",
  "end_date": "2030-04-12",
  "comment": "Family vacation"
}
```

This creates a private `draft` with a stable number and revision. All subsequent writes require
`expected_revision` from the latest request response. A stale version returns `409` without a write.
`PATCH` saves draft fields; `/submit` validates title, description and applicable dates and produces `submitted`.
The existing `type`, `comment`, `applicant` and `approver` fields mean category, description, author and assignee.
Author and assignee are derived from authenticated identities, not from the creation payload.

Actions at `/actions/{action}`:

- Manager: `start_review` (Submitted → In Review), `request_information` (In Review → Needs Information).
- Employee: `provide_information` (Needs Information → In Review), `cancel` (active → Cancelled).
- Manager: `approve` / `reject` (In Review → Approved / Rejected), `complete` (Approved → Completed).
- Employee: `appeal` (Approved, Rejected or Completed → Submitted, incrementing the review round).

Every action except `start_review` requires `comment` with a substantive reason or additional information.
Both decisions additionally require `basis` (relevant policy or objective criteria) and
`fair_review_confirmed: true`. These are human decisions; the application does not score people or
make eligibility decisions from demographic attributes. Reconsideration goes to the assigned manager,
retains all prior decisions, and does not claim to be independent legal adjudication.

List queries accept `q`, `status`, `category`, `priority`, `sort` (created_at, updated_at, number, title,
priority), `assignee`, `attention` (all, overdue, needs_attention), `order` (asc/desc), `limit` (1–100) and `offset`. Responses include scoped `total` and status
`counts`. Search covers number, title, description, participant IDs and comments, including Unicode text.

Attachments: multipart `file` and `expected_revision`, at most five files per request, 5 MB each.
PDF, PNG, JPEG and UTF-8 TXT are accepted. File bytes are stored in SQLite with a checksum and audit event;
downloads are forced attachments with no-store/nosniff headers. No public file paths or inline rendering.
Files are not antivirus-scanned. Comments, attachments and audit records are append-only.

Bulk review accepts `{ "items": [{ "id": "<request ID>", "expected_revision": 1 }] }`, with
1–20 unique items. Only `start_review` is available in bulk. Each item checks assignment, current
status and revision independently; the response contains `results` with `id`, `success`, and
either the updated `request` or a safe `error`. A rejected item does not undo another successful item.

## React Integration

Configured local React origins are controlled through `CORS_ORIGINS`. The
default allows ports `3000` and `5173` on `localhost` and `127.0.0.1`.

HTTP error semantics:

- `401`: missing, invalid, or expired token;
- `403`: authenticated role is not allowed;
- `404`: resource is absent or outside the participant scope;
- `409`: invalid workflow transition or stale revision;
- `422`: invalid fields or calendar dates.
