# API v1 contract

The React application uses `/api/v1`. Health and login are public; every other route requires `Authorization: Bearer <token>`.

## Authentication

`POST /api/v1/auth/login`

```json
{
  "username": "employee",
  "password": "demo-password"
}
```

Valid usernames are `employee`, `manager`, and `knowledge_admin`. The server maps each name to a fixed identity and manager relationship. Tokens are HMAC-signed and expire after `DEMO_TOKEN_TTL_SECONDS`; identity headers and arbitrary user IDs are not accepted.

## Routes and roles

| Method | Path | Access |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Public |
| `POST` | `/api/v1/auth/login` | Public |
| `GET` | `/api/v1/me` | Authenticated |
| `POST` | `/api/v1/chat` | Employee |
| `POST` | `/api/v1/chat/stream` | Employee |
| `GET` | `/api/v1/conversations` | Employee owner |
| `GET` | `/api/v1/conversations/{id}` | Employee owner |
| `GET` | `/api/v1/requests` | Authenticated, role-scoped |
| `POST` | `/api/v1/requests` | Employee |
| `GET` | `/api/v1/requests/{id}` | Employee owner, assigned Manager, or Knowledge Admin |
| `POST` | `/api/v1/requests/{id}/submit` | Employee owner |
| `POST` | `/api/v1/requests/{id}/cancel` | Employee owner |
| `POST` | `/api/v1/requests/{id}/approve` | Assigned Manager, PTO only |
| `POST` | `/api/v1/requests/{id}/decline` | Assigned Manager, PTO only |
| `POST` | `/api/v1/requests/{id}/acknowledge` | Assigned Manager, sick leave only |
| `POST` | `/api/v1/requests/{id}/comments` | Assigned Manager |
| `GET` | `/api/v1/documents` | Knowledge Admin |
| `POST` | `/api/v1/documents` | Knowledge Admin |
| `GET` | `/api/v1/documents/{id}/download` | Knowledge Admin |
| `DELETE` | `/api/v1/documents/{id}` | Knowledge Admin |
| `POST` | `/api/v1/documents/index` | Knowledge Admin |
| `POST` | `/api/v1/feedback` | Employee |
| `GET` | `/api/v1/admin/feedback` | Knowledge Admin |
| `GET` | `/api/v1/admin/unanswered` | Knowledge Admin |
| `POST` | `/api/v1/admin/quality/{id}` | Knowledge Admin |
| `GET`, `PUT` | `/api/v1/admin/ai-settings` | Knowledge Admin |
| `POST` | `/api/v1/admin/ai-settings/test` | Knowledge Admin |
| `GET` | `/api/v1/admin/metrics` | Knowledge Admin |

## Chat and history

A new chat request omits `conversation_id`. The server creates a conversation only after it can persist the complete user/assistant exchange, so empty recent-history rows are impossible.

```json
{
  "messages": [{ "role": "user", "content": "When is payroll processed?" }],
  "top_k": 4,
  "min_similarity": 0.25,
  "conversation_id": null
}
```

For a follow-up, send the returned `conversation_id` and only the newest user message. The server verifies ownership, loads authoritative history, and builds the internal prompt. `min_similarity` accepts the full range `0.0`–`1.0`, including an intentional zero.

`POST /chat/stream` returns `application/x-ndjson` with these event shapes:

```json
{"type":"start"}
{"type":"token","content":"Salaries "}
{"type":"replace","content":"Deterministic fallback text"}
{"type":"complete","intent":"work","language":"en","outcome_code":"grounded","sources":[],"workflow_request":null,"conversation_id":"..."}
```

`replace` is emitted when provider streaming fails after partial output, preventing the UI from combining an incomplete model answer with the fallback. `outcome_code` records the semantic result independently of whether source cards are visible. A validation or persistence problem ends with `{"type":"error","message":"..."}`.

Conversation detail hydrates linked request cards from current workflow state. The historical assistant text and evidence stay unchanged; status does not become stale.

## Workflow requests

Only `pto` and `sick_leave` are accepted. The server owns applicant and approver identity; those fields cannot be supplied by the client.
Employee drafts remain private: manager list and detail routes expose them only after submission.

PTO draft:

```json
{
  "type": "pto",
  "start_date": "2030-04-10",
  "end_date": "2030-04-12",
  "comment": "Handoff is ready.",
  "details": {}
}
```

`POST /requests` creates `draft`; `POST /requests/{id}/submit` validates it again and transitions to `in_review`. The assigned manager can then move it to `approved` or `declined`. Decline requires a comment.

Sick leave draft:

```json
{
  "type": "sick_leave",
  "start_date": "2030-04-10",
  "end_date": "2030-04-10",
  "comment": "Coverage note",
  "details": {
    "expected_return_date": "2030-04-11",
    "expected_return_unknown": false,
    "time_away": "full_day",
    "partial_hours": null,
    "extended_or_recurring": false
  }
}
```

Submission transitions `draft → reported`; the assigned manager uses `acknowledge` for `reported → acknowledged`. Approval and decline are invalid for sick leave. There is no diagnosis or medical-document field.

## Documents and indexing

Uploads accept `.md`, `.txt`, `.pdf`, and `.docx` up to 10 MB. IDs are stable hashes of relative source paths, so nested files with equal stems cannot collide.

Retrieval uses one corpus-wide index. `POST /documents/index` rebuilds it globally and returns `scope: "all_documents"`. Uploads rebuild automatically when that AI setting is enabled; deletes always rebuild. Both operations restore the prior document and index files if the rebuild fails.

Index mode is `embedding` or `lexical`. A transient embedding failure produces a usable lexical index with a retry time rather than permanently disabling semantic retrieval.

## Quality and AI settings

Assistant feedback stores rating, optional note, rated question, and rated answer without an employee identifier. The unanswered queue uses explicit outcome codes; it does not infer current failures from display text. Items can be marked `resolved` or `ignored`.

The AI settings preview uses the same RAG path with request-scoped unsaved settings, while workflow creation, conversation persistence, and quality logging remain disabled.

## Error semantics

- `400`: malformed chat or document input;
- `401`: missing, invalid, or expired token;
- `403`: role or ownership does not allow the action;
- `404`: resource is absent or intentionally hidden outside scope;
- `409`: duplicate document or invalid workflow transition;
- `413`: upload exceeds 10 MB;
- `422`: structured validation failed;
- `503`: conversation persistence or index rebuild failed safely.
