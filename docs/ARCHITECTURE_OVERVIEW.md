# Architecture Overview

The application is organized as a compact demo stack: one FastAPI backend, two Streamlit frontends, a Microsoft Teams Bot Framework endpoint, document-based RAG, and SQLite workflow storage.

## High-Level Diagram

```text
Employee Streamlit UI          Admin Streamlit UI          Teams personal bot
         |                             |                             |
         +-----------------------------+-----------------------------+
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
- `services/document_service.py` and `services/document_reader.py` handle document storage, ingestion, and source metadata.
- `workflow.py` stores workflow requests in SQLite for simple demo persistence.
- `web_ui/` provides the employee/admin Streamlit experiences.
- `teams_bot/` exposes the Microsoft Teams Bot Framework personal-chat adapter.

## Request Flow

1. A user message reaches `POST /chat`.
2. `ChatService` converts API DTOs into internal chat models.
3. `ChatRouter` determines the intent and whether a prior topic should be reused.
4. If the message is a workflow request, `WorkflowService` creates a SQLite record.
5. If the message needs retrieval, `RAGService` ensures the index exists, queries embeddings, and builds the answer.
6. The final outcome is converted back to API DTOs and logged through `ChatLogService`.

Teams personal chat follows the same `ChatService` path through `POST /api/messages`, then appends document sources in a Teams-friendly message format.

## Packaging Note

For Stage 4, the minimal container target is the FastAPI API. The Streamlit demo apps remain better served by the existing local PowerShell scripts because they are presentation tooling rather than deployment-critical backend services.
