# API Endpoint Summary

This project exposes a small FastAPI surface intended for local demos and portfolio review.

## Public Endpoints

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness check used by local scripts and smoke tests | None |
| `POST` | `/chat` | Main employee chat entrypoint for company-policy questions and workflow creation | Optional `X-User` |
| `GET` | `/requests` | List workflow requests created by the current user | Optional `X-User` |

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
| `PUT` | `/admin/requests/{request_id}/status` | Update workflow status |

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

## Notes

- `X-User` defaults to `anonymous` if not provided.
- `POST /chat` can return document-grounded answers, topic-selection guidance, small-talk responses, or workflow creation confirmations.
- Admin document changes do not silently mutate the index; the explicit rebuild endpoint keeps demo behavior predictable.
