# Architecture Overview

Setup, environment variables, startup, tests and bot connection instructions are maintained
only in the root [README](../README.md). This document describes implementation boundaries.

The application is organized as a React single-page product, a FastAPI backend,
document-based RAG, and SQLite workflow storage.

## High-Level Diagram

```text
React views -> feature hooks -> HTTP/NDJSON client
                                |
                           FastAPI /api/v1
                     DTOs, auth, error translation
                                |
          +---------------------+----------------------+
          |                     |                      |
      ChatService         WorkflowService        DocumentService
          |                     |                 AISettingsService
      RAGService          domain/workflow         QualityService
          |                     |                      |
   rag/index + Retriever        +---- storage/ --------+
          |                         SQLite / files
   integrations/                    JSON / JSONL
   OpenAI generation + embeddings
```


## Runtime Responsibilities

- `app.py` composes the HTTP application; `api/` owns DTOs, role checks and a shared domain-error-to-HTTP mapping. Routes do not read or write files or invoke the OpenAI SDK.
- `services/auth_service.py` issues and validates expiring signed tokens for
  Employee, Manager, and Knowledge Admin demo identities.
- `services/conversation_service.py` owns saved conversation turns and delegates answer generation to `services/chat_service.py`; `storage/conversation_store.py` enforces ownership, ordering and retry idempotency in SQLite.
- `services/chat_service.py` is the orchestration layer for chat outcomes.
- `services/chat_router.py` decides whether a message is a supported work question, small talk, invalid input, or a workflow-creation path.
- `services/rag_service.py` handles retrieval-backed answers and graceful fallbacks.
- `services/ai_settings_service.py` coordinates the saved AI configuration. `storage/ai_settings_store.py` and `storage/prompt_store.py` persist controls and prompts; `rag/prompts.py` only builds prompt messages. JSON and prompt writes share atomic text replacement.
- `services/document_service.py` coordinates upload, indexing and deletion. The document store restores the source if index rebuilding fails.
- `services/quality_service.py` combines workflow and chat data for administrator projections.
- `storage/document_store.py` and `storage/document_reader.py` handle document storage, ingestion, duplicate detection, and source metadata.
- `domain/workflow.py` defines interpretation, validation and state transitions;
  `services/workflow_service.py` orchestrates use cases; `storage/workflow_store.py`
  persists requests and audit events in one SQLite transaction.
- `frontend/` provides the React employee, manager, and knowledge administration workspaces.
- `integrations/` owns OpenAI adapters, personal Slack/Discord delivery, signature verification, Discord command handling, Gateway and proxy-aware network access. The unused Streamlit application has been removed.
- `services/runtime.py` composes dependencies at startup. Importing the application creates no database.

## Request Flow

1. A predefined demo account signs in through `POST /api/v1/auth/login`.
2. The client sends the signed Bearer token; identity never comes from a user header.
3. An Employee UI message reaches `POST /api/v1/conversations/{id}/messages/stream`. The compatibility `/api/v1/chat` and `/api/v1/chat/stream` endpoints use the same saved conversation service.
4. `ConversationService` loads the owner's persisted context and uses an idempotent turn ID. The compatibility adapter accepts the latest user message, not client-supplied history as authoritative context.
5. `ChatRouter` determines the intent and whether a prior topic should be reused.
6. An explicit action can create only a `draft`; policy questions continue to RAG.
7. The employee reviews extracted fields in a confirmation form. Submission validates
   real ISO calendar dates and transitions `draft -> submitted`.
8. Manager actions follow protected transitions and every change creates a
   `request_events` audit entry.
9. If the message needs retrieval, `RAGService` verifies the versioned index, performs hybrid lexical/vector retrieval, deduplicates sections, and builds the answer.
10. The final outcome is converted back to API DTOs and logged through `ChatLogStore`; invalid out-of-scope prompts are not retained.
11. Employee answer feedback stores the rated question and exact assistant answer;
    the Knowledge Admin API exposes an anonymized review projection without `user_id`.
12. The Quality queue combines rated conversations with real ungrounded workplace
    questions. Resolved and ignored gaps are persisted in `quality_reviews`.

## Workflow Storage

SQLite contains `users`, `workflow_requests`, `request_events`,
`request_numbers`, `request_attachments`, `request_comments`, `feedback`, `assistant_feedback`,
`quality_reviews`, `conversations`, and `chat_messages`.
Existing databases are migrated automatically when opened. Request migrations add columns and events;
original submitted/completed states and historical decisions are preserved. Legacy declined requests
become rejected with an explicit migration entry. Chat history has a separate `chat_migrations`
ledger and remains in the same database; workflow migrations do not replace conversations.

`domain/request_policy.py` defines a common lifecycle and participant access policy.
`services/request_service.py` validates content, decisions, evidence and reconsideration inside a transaction.
`storage/request_store.py` persists changes and append-only audit entries; `api/request_routes.py` exposes
validated HTTP inputs. Request revisions reject stale concurrent decisions. SQLite triggers block ordinary
updates/deletes of audit records; a database administrator can still replace the database, so this is not
cryptographic tamper resistance. Back up the complete SQLite database, including attachments.

The demo login intentionally still uses predefined roles and a shared demo password. Production deployment
needs individual identity-provider accounts and server-managed manager assignments. The workflow does not
claim legal compliance or guarantee that a human reviewer will never write an inappropriate rationale.

Knowledge documents remain filesystem-backed. Upload and deletion operations are
restricted to Knowledge Admins, and each deletion rebuilds the RAG index before it
is reported as successful.

Retrieval quality is guarded by `evals/rag_questions.json` and the deterministic
evaluation documented in the root README's test instructions.

## Frontend Architecture

Feature views contain JSX, presentation and navigation. Their hooks own requests,
mutations, form state and cache updates. `useRequests.ts` shares request-list and
detail queries and refreshes both Employee and Manager caches after a mutation.
Knowledge Admin is composed from overview, document, quality and settings sections;
`useKnowledge.ts` owns its API operations. Employee uses `/home`, `/requests` and `/employee`
(chat); Manager uses `/manager`, and Knowledge Admin uses `/knowledge`. Saved chats are
restricted to Employee in the UI, HTTP routes, and conversation service. Manager/Admin
receive HTTP 403 for conversation operations and compatibility chat endpoints, including
their own old conversations; those historical records remain stored. Employee access also
requires conversation ownership. Account registration during login is independent of chat access.


The React application uses React Router for role workspaces, TanStack Query for
server state, Zod for boundary validation, Radix primitives for accessible
dialogs, Tailwind design tokens, and an NDJSON reader for progressive chat
rendering. `run_demo.ps1` starts one Vite frontend; role navigation happens
inside the SPA.

The AI settings preview uses the same chat and RAG path as the Employee UI, but
passes the unsaved prompt and switches as request-scoped overrides. Workflow
draft creation and chat logging are disabled for preview requests.

Architecture tests guard dependency direction and prevent HTTP/cache operations from returning to feature views. Service regression tests cover document rollback, prompt persistence, manager decisions and preview isolation.

## Notification delivery

`services/notification_service.py` starts independent Slack and Discord delivery workers
from the FastAPI lifespan. `storage/notification_store.py` persists provider settings,
cursors and jobs in the application's SQLite database. `storage/personal_notification_store.py`
stores verified personal destinations and expiring, hashed link challenges. Linking requires
both the provider identity and confirmation by the signed-in application account.

`domain/notification_policy.py` selects one permitted recipient per event: Employee receives
only a request for additional information; the assigned Manager receives new requests,
Employee replies, reconsideration, reassignment and cancellation. Approval/rejection/completion
do not automatically notify Employee. Missing recipients never fall back to a public channel
or another account. Current request access, recipient and status are rechecked before delivery.

Provider cursors advance over `request_events` and queue identifiers, event metadata, audience
and recipient ID; secrets stay in server configuration. Request business services do not call
providers, so a delivery failure cannot roll back a saved request or decision. Unique event IDs,
expiring leases and fencing tokens limit duplicate work. External acknowledgements can still
be lost, so retries do not guarantee exactly-once delivery. Calls time out after ten seconds;
jobs allow at most five attempts with backoff and rate-limit handling. Disabling cancels queued
work, but an in-flight message may finish. Enabling does not replay historical events.

`integrations/direct_messages.py` sends through the official bot APIs, with TLS and proxy
handling in `integrations/network.py`. `integrations/notification_transport.py` supplies
shared payload formatting, URL validation, delivery-result and retry helpers. The unused
channel webhook transport has been removed. Channel webhook settings are not used.

`integrations/bot_security.py` verifies signed HTTP callbacks. Discord normally receives
link commands through `integrations/discord_gateway.py`; its optional HTTP mode uses
`api/personal_integration_routes.py`, as do Slack callbacks and application-side account
linking. A configured Gateway can accept linking commands while notification delivery is off.
Bots do not create or process requests: those actions remain in the web application.

`api/integration_routes.py` exposes administrator delivery controls; personal connection routes
are limited to Employee/Manager. `frontend/src/features/integrations` owns their views and hooks.
Credentials cannot be entered or read through those screens, and delivery errors are sanitized.
