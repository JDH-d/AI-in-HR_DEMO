# API v1 Contract

The React-facing API is versioned under `/api/v1`. Except for health and login,
every endpoint requires `Authorization: Bearer <token>`.

## Demo Authentication

`POST /api/v1/auth/login`

```json
{
  "username": "employee",
  "password": "demo-password"
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
| `POST` | `/api/v1/chat` | Authenticated |
| `GET` | `/api/v1/me` | Authenticated |
| `GET` | `/api/v1/requests` | Authenticated, role-scoped |
| `POST` | `/api/v1/requests` | Employee |
| `GET` | `/api/v1/requests/{id}` | Owner, Manager, Knowledge Admin |
| `POST` | `/api/v1/requests/{id}/submit` | Employee owner |
| `POST` | `/api/v1/requests/{id}/cancel` | Employee owner |
| `POST` | `/api/v1/requests/{id}/approve` | Manager |
| `POST` | `/api/v1/requests/{id}/decline` | Manager |
| `POST` | `/api/v1/requests/{id}/comments` | Manager |
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
  "start_date": "2030-04-10",
  "end_date": "2030-04-12",
  "comment": "Family vacation"
}
```

This creates a `draft`. `POST /api/v1/requests/{id}/submit` performs final
validation and transitions it to `in_review`.

Manager `approve` and `decline` endpoints apply a decision to a request that is
already `in_review`, producing a single decision audit event.

## React Integration

Configured local React origins are controlled through `CORS_ORIGINS`. The
default allows ports `3000` and `5173` on `localhost` and `127.0.0.1`.

HTTP error semantics:

- `401`: missing, invalid, or expired token;
- `403`: authenticated role is not allowed;
- `404`: resource is absent or outside the employee scope;
- `409`: invalid workflow transition;
- `422`: invalid fields or calendar dates.
