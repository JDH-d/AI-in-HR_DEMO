# Architecture Overview

The application is organized as a React single-page product, a FastAPI backend,
document-based RAG, and SQLite workflow storage.

## High-Level Diagram

```text
          React / TypeScript SPA
 Employee | Manager | Knowledge Admin
         |
                       |
                       v
                FastAPI Application
          /api/v1 + signed demo identity
                       |
                       v
                  ChatService
                    +----------------+------------------+
                    |                |                  |
                    v                v                  v
               ChatRouter        WorkflowService      RAGService
               (intent +         (SQLite requests)    (index bootstrap,
               topic flow)                           retrieval, answer generation)
                    |                                   |
                    v                                   v
             DocumentService                    rag/index + Retriever
             document metadata                  documents/ + embeddings
                    |
                    v
             ChatLogService
             JSONL demo logs
```

## Runtime Responsibilities

- `app.py` exposes only the versioned `/api/v1` router and configured React CORS origins.
- `services/auth_service.py` issues and validates expiring signed tokens for
  Employee, Manager, and Knowledge Admin demo identities.
- `services/chat_service.py` is the orchestration layer for chat outcomes.
- `services/chat_router.py` decides whether a message is a supported work question, small talk, invalid input, or a workflow-creation path.
- `services/rag_service.py` handles retrieval-backed answers and graceful fallbacks.
- `services/document_service.py` and `services/document_reader.py` handle document storage, ingestion, duplicate detection, and source metadata.
- `workflow.py` implements structured action interpretation, calendar validation,
  an explicit workflow state machine, SQLite persistence, and audit events.
- `frontend/` provides the React employee, manager, and knowledge administration workspaces.
- `web_ui/` is retained only as a legacy reference and is not started by `run_demo.ps1`.

## Request Flow

1. A predefined demo account signs in through `POST /api/v1/auth/login`.
2. The client sends the signed Bearer token; identity never comes from a user header.
3. A user message reaches `POST /api/v1/chat`.
4. `ChatService` converts API DTOs into internal chat models.
5. `ChatRouter` determines the intent and whether a prior topic should be reused.
6. An explicit action can create only a `draft`; policy questions continue to RAG.
7. The employee reviews extracted fields in a confirmation form. Submission validates
   real ISO calendar dates and transitions `draft -> in_review`.
8. Manager actions follow protected transitions and every change creates a
   `request_events` audit entry.
9. If the message needs retrieval, `RAGService` verifies the versioned index, performs hybrid lexical/vector retrieval, deduplicates sections, and builds the answer.
10. The final outcome is converted back to API DTOs and logged through `ChatLogService`.
11. Employee answer feedback stores the rated question and exact assistant answer;
    the Knowledge Admin API exposes an anonymized review projection without `user_id`.

## Workflow Storage

SQLite contains `users`, `workflow_requests`, `request_events`,
`request_comments`, `feedback`, and `assistant_feedback`. Existing databases are
migrated automatically when opened.

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
