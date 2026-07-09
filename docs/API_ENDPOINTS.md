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
| `POST` | `/api/v1/requests/{id}/complete` | Manager |
| `POST` | `/api/v1/requests/{id}/comments` | Manager |
| `GET` | `/api/v1/documents` | Knowledge Admin |
| `POST` | `/api/v1/documents` | Knowledge Admin |
| `DELETE` | `/api/v1/documents/{id}` | Knowledge Admin |
| `POST` | `/api/v1/documents/{id}/index` | Knowledge Admin |
| `POST` | `/api/v1/feedback` | Employee |
| `GET` | `/api/v1/admin/metrics` | Knowledge Admin |
| `GET/PUT` | `/api/v1/admin/system-prompt` | Knowledge Admin |
| `GET` | `/api/v1/admin/logs` | Knowledge Admin |

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
validation and transitions it to `submitted`.

Manager `approve` and `decline` endpoints open a submitted request for review
before applying the decision, producing separate audit events.

## React Integration

Configured local React origins are controlled through `CORS_ORIGINS`. The
default allows ports `3000` and `5173` on `localhost` and `127.0.0.1`.

HTTP error semantics:

- `401`: missing, invalid, or expired token;
- `403`: authenticated role is not allowed;
- `404`: resource is absent or outside the employee scope;
- `409`: invalid workflow transition;
- `422`: invalid fields or calendar dates.
