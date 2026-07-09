# API Endpoint Summary

This project exposes a small FastAPI surface intended for local demos and portfolio review.

## Public Endpoints

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness check used by local scripts and smoke tests | None |
| `POST` | `/chat` | Policy answers and workflow draft preparation | Optional `X-User` |
| `GET` | `/requests` | List workflow requests created by the current user | Optional `X-User` |
| `GET` | `/requests/{request_id}` | Read one request owned by the current user | Optional `X-User` |
| `POST` | `/requests/{request_id}/confirm` | Validate editable draft fields and submit the request | Optional `X-User` |
| `POST` | `/requests/{request_id}/cancel` | Cancel an eligible request | Optional `X-User` |
| `GET` | `/requests/{request_id}/history` | Read status events and manager comments | Optional `X-User` |
| `POST` | `/requests/{request_id}/feedback` | Add a 1–5 workflow rating | Optional `X-User` |

## Admin Endpoints

Admin routes accept either `Authorization: Bearer <token>` or `X-Admin-Token: <token>`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/admin/system-prompt` | Read the active system prompt |
| `PUT` | `/admin/system-prompt` | Update the system prompt |
| `GET` | `/admin/documents` | List uploaded/readable documents |
| `POST` | `/admin/documents` | Upload a new `.txt`, `.md`, `.pdf`, or `.docx` document |
| `DELETE` | `/admin/documents/{doc_name}` | Delete a document by relative path/name |
| `POST` | `/admin/rebuild-index` | Rebuild the RAG index from `documents/` |
| `GET` | `/admin/logs` | Read recent chat logs |
| `GET` | `/admin/requests` | List workflow requests across users |
| `PUT` | `/admin/requests/{request_id}/status` | Apply an allowed workflow status transition |
| `GET` | `/admin/requests/{request_id}/history` | Read the complete audit history |
| `POST` | `/admin/requests/{request_id}/comments` | Add a manager comment |

## Core Request Shapes

`POST /chat`

```json
{
  "messages": [
    {"role": "user", "content": "How often are salaries paid?"}
  ],
  "top_k": 4,
  "min_similarity": 0.25
}
```

Typical response fields:

```json
{
  "message": {"role": "assistant", "content": "..."},
  "intent": "work",
  "language": "en",
  "sources": [
    {
      "source": "Payroll_FAQ.md",
      "title": "Payroll and Pay Practices Handbook",
      "section": "How often are salaries paid?",
      "category": "Payroll",
      "version": "2026.1",
      "excerpt": "Pacific Beacon pays on a semi-monthly schedule...",
      "score": 0.87
    }
  ]
}
```

An explicit action such as `I need vacation from 2030-04-01 to 2030-04-03`
returns a `workflow_request` with status `draft`. The employee must submit
`POST /requests/{id}/confirm`; chat never submits the request implicitly.

Workflow states are:

```text
draft -> submitted -> in_review -> approved -> completed
                                \-> declined
draft/submitted/in_review -> cancelled
```

## Notes

- `X-User` defaults to `anonymous` if not provided.
- `POST /chat` can return document-grounded answers, guidance, or a workflow draft.
- Policy questions do not create workflow records.
- Invalid transitions return HTTP `409`; invalid dates or fields return HTTP `422`.
- Admin document changes do not silently mutate the index; the explicit rebuild endpoint keeps demo behavior predictable.
