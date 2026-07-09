# Architecture Overview

The application is organized as a compact demo stack: one FastAPI backend, two Streamlit frontends, document-based RAG, and SQLite workflow storage.

## High-Level Diagram

```text
Employee Streamlit UI          Admin Streamlit UI
         |                             |
         +-----------------------------+
                       |
                       v
                FastAPI Application
         public_routes / chat_routes / admin_routes
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

- `app.py` wires the FastAPI app and route modules.
- `services/chat_service.py` is the orchestration layer for chat outcomes.
- `services/chat_router.py` decides whether a message is a supported work question, small talk, invalid input, or a workflow-creation path.
- `services/rag_service.py` handles retrieval-backed answers and graceful fallbacks.
- `services/document_service.py` and `services/document_reader.py` handle document storage, ingestion, duplicate detection, and source metadata.
- `workflow.py` implements structured action interpretation, calendar validation,
  an explicit workflow state machine, SQLite persistence, and audit events.
- `web_ui/` provides the employee/admin Streamlit experiences.

## Request Flow

1. A user message reaches `POST /chat`.
2. `ChatService` converts API DTOs into internal chat models.
3. `ChatRouter` determines the intent and whether a prior topic should be reused.
4. An explicit action can create only a `draft`; policy questions continue to RAG.
5. The employee reviews extracted fields in a confirmation form. Submission validates
   real ISO calendar dates and transitions `draft -> submitted`.
6. Manager actions follow protected transitions and every change creates a
   `request_events` audit entry.
7. If the message needs retrieval, `RAGService` verifies the versioned index, performs hybrid lexical/vector retrieval, deduplicates sections, and builds the answer.
8. The final outcome is converted back to API DTOs and logged through `ChatLogService`.

## Workflow Storage

SQLite contains `users`, `workflow_requests`, `request_events`,
`request_comments`, and `feedback`. Existing Stage 1 request databases are
migrated automatically when opened.

Retrieval quality is guarded by `evals/rag_questions.json` and the deterministic
`python -m scripts.run_rag_eval` command.

## Packaging Note

For Stage 4, the minimal container target is the FastAPI API. The Streamlit demo apps remain better served by the existing local PowerShell scripts because they are presentation tooling rather than deployment-critical backend services.
