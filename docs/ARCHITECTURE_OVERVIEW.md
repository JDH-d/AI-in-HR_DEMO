# Architecture Overview

The application is organized as a React single-page product, a FastAPI backend,
document-based RAG, and SQLite conversation and workflow storage.

## High-Level Diagram

```text
          React / TypeScript SPA
 Employee | Manager | Knowledge Admin
                  |
                  v
          FastAPI /api/v1 + identity
            |                  |
            v                  v
       ChatService       ConversationService
       |     |    |       (SQLite user history)
       |     |    |
       v     v    v
   Router  Workflow  RAGService
           Service   (retrieval + answers)
              |             |
              v             v
          SQLite DB    Retriever + documents
              ^
              |
      requests + conversations

   ChatService --> ChatLogService --> JSONL demo logs
```

## Runtime Responsibilities

- `app.py` exposes only the versioned `/api/v1` router and configured React CORS origins.
- `services/auth_service.py` issues and validates expiring signed tokens for
  Employee, Manager, and Knowledge Admin demo identities.
- `services/chat_service.py` is the orchestration layer for chat outcomes.
- `services/conversation_service.py` stores user-scoped conversations, messages,
  source evidence, and linked workflow drafts in SQLite.
- `services/chat_router.py` decides whether a message is a supported work question, small talk, invalid input, or a workflow-creation path.
- `services/rag_service.py` handles retrieval-backed answers and graceful fallbacks.
- `services/ai_settings_service.py` persists the six administrator-facing AI controls with safe defaults.
- `services/document_service.py` and `services/document_reader.py` handle document storage, ingestion, duplicate detection, and source metadata.
- `workflow.py` implements structured action interpretation, calendar validation,
  an explicit workflow state machine, SQLite persistence, and audit events.
- `frontend/` provides the React employee, manager, and knowledge administration workspaces.
- `web_ui/` is retained only as a legacy reference and is not started by `run_demo.ps1`.

## Request Flow

1. A predefined demo account signs in through `POST /api/v1/auth/login`.
2. The client sends the signed Bearer token; identity never comes from a user header.
3. The employee opens or creates a user-scoped conversation.
4. A user message reaches `POST /api/v1/chat` or `/api/v1/chat/stream` with its conversation ID.
5. `ChatService` converts API DTOs into internal chat models.
6. `ChatRouter` determines the intent and whether a prior topic should be reused.
7. An explicit action can create only a `draft`; policy questions continue to RAG.
8. The employee reviews extracted fields in a confirmation form. PTO submission
   validates real ISO calendar dates and transitions `draft -> in_review`. Sick
   leave records availability-only details and transitions `draft -> reported`.
9. Manager actions follow protected transitions (`in_review -> approved/declined`
   or `reported -> acknowledged`) and every change creates a
   `request_events` audit entry.
10. If the message needs retrieval, `RAGService` verifies the versioned index, performs hybrid lexical/vector retrieval, deduplicates sections, and builds the answer.
11. `ConversationService` stores the completed exchange and its evidence;
    analytics-safe logging continues through `ChatLogService`.
12. Employee answer feedback stores the rated question and exact assistant answer;
    the Knowledge Admin API exposes an anonymized review projection without `user_id`.
13. The Quality queue combines rated conversations with real ungrounded workplace
    questions. Resolved and ignored gaps are persisted in `quality_reviews`.

## Workflow Storage

SQLite contains `conversations`, `conversation_messages`, `users`,
`workflow_requests`, `request_events`, `request_comments`, `feedback`,
`assistant_feedback`, and `quality_reviews`.
Existing databases are migrated automatically when opened.

Type-specific request fields live in the `workflow_requests.details` JSON object.
This keeps the shared request lifecycle compact while allowing the Sick Leave UI
to store expected return and availability details without medical information.

Knowledge documents remain filesystem-backed. Upload and deletion operations are
restricted to Knowledge Admins, and each deletion rebuilds the RAG index before it
is reported as successful.

Retrieval quality is guarded by `evals/rag_questions.json` and the deterministic
`python -m scripts.run_rag_eval` command.

## Frontend Architecture

The React application uses React Router for role workspaces, TanStack Query for
server state, Zod for boundary validation, Radix primitives for accessible
dialogs, Tailwind design tokens, and an NDJSON reader for progressive chat
rendering. `run_demo.ps1` starts one Vite frontend; role navigation happens
inside the SPA.

The AI settings preview uses the same chat and RAG path as the Employee UI, but
passes the unsaved prompt and switches as request-scoped overrides. Workflow
draft creation and chat logging are disabled for preview requests.
