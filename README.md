# AI HR Knowledge Assistant (MVP)
![Python Version](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi)
![Streamlit](https://img.shields.io/badge/Streamlit-App-success?style=for-the-badge&logo=streamlit)
![OpenAI API](https://img.shields.io/badge/OpenAI-API-orange?style=for-the-badge&logo=openai)
![Status](https://img.shields.io/badge/Status-MVP-yellow?style=for-the-badge)

An AI assistant MVP for answering company-specific questions from internal documents and turning employee requests into trackable workflows.

The included demo uses HR and IT policies because they are easy to understand in a portfolio review, but the architecture is domain-agnostic. The same approach can support healthcare operations, construction companies, field teams, compliance teams, customer support, finance operations, or any organization that needs document-grounded answers and lightweight request handling.

## Features
- Employee-facing chat for company policy and operations questions
- Retrieval-augmented generation over internal documents
- Source snippets returned with assistant answers
- Workflow creation for PTO, sick leave, and document requests
- Admin console for prompts, documents, logs, index rebuilds, and request status updates
- Optional Microsoft Teams personal bot for employee chat
- Configurable log privacy via `LOG_USER_TEXT_MODE`
- Local-first setup with FastAPI, Streamlit, SQLite, and OpenAI models

## Business Value
Most internal teams answer the same operational questions repeatedly: policies, benefits, access requests, schedules, onboarding, compliance rules, safety procedures, and document requests.

This project demonstrates a practical internal assistant that does more than generate text:
- grounds answers in approved company documents
- creates requests when the conversation requires action
- gives admins visibility into documents, logs, prompts, and workflows
- can be adapted to multiple industries by replacing documents, prompts, and workflow scenarios

For a business reviewer, the value proposition is simple: reduce repetitive internal support work while keeping answers tied to approved materials.

## Project Structure
```
.
├─ app.py                     # FastAPI entrypoint
├─ api/                       # HTTP routes, schemas, and auth dependencies
├─ core/                      # Settings and environment helpers
├─ services/                  # Chat, RAG runtime, documents, logs, LLM wrapper
├─ rag/                       # Prompts, retrieval, topic routing, index bootstrap
├─ workflow.py                # SQLite workflow request storage
├─ web_ui/                    # Streamlit employee and admin interfaces
├─ teams_bot/                 # Microsoft Teams Bot Framework integration
├─ teams_app_manifest/        # Teams app manifest template and icons
├─ documents/                 # Demo knowledge base documents
├─ docs/                      # API and architecture notes
├─ tests/                     # Unit and interaction tests
├─ run_demo.ps1               # Starts API + employee UI + admin UI
├─ smoke_check.ps1            # Demo readiness validation
├─ requirements.txt           # Pinned dependencies
├─ .env.example               # Example environment file
└─ README.md                  # This file
```

## Prerequisites
- Python 3.10+
- An OpenAI API key
- Windows PowerShell for the included demo scripts
- Optional: Docker, if you want to run the API-only container

## Quickstart
1) Create and activate a virtual environment

   Windows (PowerShell):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   macOS/Linux (bash):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2) Install dependencies
```bash
pip install -r requirements.txt
```

3) Configure environment
```powershell
Copy-Item .env.example .env
```

Edit `.env` and set at least `OPENAI_API_KEY` and `ADMIN_TOKEN`.

4) Run the full local demo
```powershell
powershell -ExecutionPolicy Bypass -File .\run_demo.ps1
```

Default local endpoints:
- User UI: http://127.0.0.1:8501
- Admin UI: http://127.0.0.1:8502
- API: http://127.0.0.1:8000
- API health: http://127.0.0.1:8000/health

5) Stop the demo
```powershell
powershell -ExecutionPolicy Bypass -File .\stop_demo.ps1
```

## Environment
The app reads configuration from environment variables via `.env`.

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key used for generation and embeddings. |
| `OPENAI_MODEL` | No | `gpt-5-nano` | Primary model used by the assistant. |
| `OPENAI_FALLBACK_MODEL` | No | `gpt-4o-mini` | Fallback chat model. |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model for document retrieval. |
| `ADMIN_TOKEN` | Yes | `change-me` | Token required for admin endpoints and admin UI actions. |
| `DOCUMENTS_DIR` | No | `documents` | Directory containing source documents. |
| `INDEX_PATH` | No | `data/index.json` | Local retrieval index path. |
| `LOG_PATH` | No | `data/chat_logs.jsonl` | Chat log path. |
| `WORKFLOW_DB` | No | `data/workflow.db` | SQLite workflow database path. |
| `SYSTEM_PROMPT_PATH` | No | `data/system_prompt.txt` | Runtime-editable system prompt path. |
| `LOG_USER_TEXT_MODE` | No | `masked` | Use `masked`, `raw`, or `off`. |
| `API_BASE_URL` | No | `http://127.0.0.1:8000` | API URL used by the Streamlit UI. |
| `MICROSOFT_APP_ID` | Teams only | empty | Azure Bot application/client ID. |
| `MICROSOFT_APP_PASSWORD` | Teams only | empty | Azure Bot client secret. |
| `MICROSOFT_APP_TENANT_ID` | Teams only | empty | Microsoft Entra tenant ID. |
| `TEAMS_BOT_HISTORY_DB` | No | `data/teams_conversations.db` | SQLite history for Teams personal chats. |

## How It Works
- The employee UI sends chat messages to the FastAPI backend.
- `ChatService` routes the request through intent detection, workflow creation, or retrieval-backed answering.
- The RAG layer builds or loads a local document index and retrieves relevant chunks from `documents/`.
- The assistant generates a concise answer using the retrieved context and returns source snippets.
- Workflow-style messages can create SQLite-backed requests.
- The admin UI can inspect logs, update prompts, manage documents, rebuild the index, and update request statuses.

## xample Questions
- What can you help with?
- How often are salaries paid?
- How far in advance should I request vacation?
- Can I request partial-day PTO?
- How do I request VPN access?
- I need vacation from 04/10 to 04/12

## Demo Flow
1. Open the employee chat.
2. Ask what the assistant can help with.
3. Ask a policy question about payroll, benefits, schedules, VPN access, or PTO.
4. Ask a follow-up question and show that context is preserved.
5. Create a workflow request.
6. Open the admin console and review the created request.
7. Show document management, logs, prompt configuration, or index rebuild.
8. Optionally show the same employee chat flow through Microsoft Teams personal chat.

Detailed scripts are available in [DEMO_SCENARIOS.md](DEMO_SCENARIOS.md).

## Example Domains
The current repository ships with HR and IT sample documents, but the same structure can be adapted to other industries:

- Healthcare: staff SOPs, patient intake guidance, internal policies, insurance workflows
- Construction: safety rules, site procedures, equipment requests, incident reporting
- Legal or compliance: policy lookup, audit preparation, evidence request workflows
- Finance operations: reimbursement rules, payroll questions, approval workflows
- Customer support: product knowledge, escalation rules, case routing

The domain changes primarily by replacing the documents, prompts, workflow scenarios, and admin policies.

## Architecture
```text
Employee Web UI / Teams Personal Bot
          |
          v
     FastAPI Backend
          |
          v
      ChatService
   /      |        \
  /       |         \
NLP   Workflow      RAG
      SQLite    documents + embeddings
          |
          v
       Admin UI
```

More detail is available in [docs/ARCHITECTURE_OVERVIEW.md](docs/ARCHITECTURE_OVERVIEW.md).

## Validation
Run the test suite:
```powershell
python -m pytest -q
```

Before a live demo, run the smoke check:
```powershell
powershell -ExecutionPolicy Bypass -File .\smoke_check.ps1
```

The smoke check validates unit tests, API health, a core chat flow, workflow creation, and admin authentication.

## API-Only Docker Run
```powershell
docker build -t enterprise-knowledge-assistant .
docker run --rm -p 8000:8000 --env-file .env enterprise-knowledge-assistant
```

The Docker target is intentionally API-only. The Streamlit apps are local presentation tools and are started by `run_demo.ps1`.

## Microsoft Teams Bot
The Teams integration is a Bot Framework personal-chat bot, not an outgoing webhook. The bot uses the same backend path as the Web UI and appends source documents below answers when retrieval returns sources.

Run the API:
```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Expose `POST /api/messages` over public HTTPS, configure Azure Bot Service, and upload the generated Teams app package. See [TEAMS_SETUP.md](TEAMS_SETUP.md).

## Troubleshooting
- Missing API key: set `OPENAI_API_KEY` in `.env`.
- Admin actions fail: check that `ADMIN_TOKEN` is set and loaded by the UI.
- Index not updating after document changes: use the admin UI `Rebuild Index` action.
- Demo services already running: restart with `.\run_demo.ps1 -ForceRestart`.
- API unavailable in the UI: confirm that http://127.0.0.1:8000/health returns `{"status":"ok"}`.
- Teams bot does not respond: verify Azure Bot messaging endpoint, `MICROSOFT_APP_ID`, `MICROSOFT_APP_PASSWORD`, Teams channel enablement, and the public HTTPS tunnel.

## Privacy & Data Handling
- Source documents are stored locally in `documents/`.
- Workflow requests are stored in SQLite.
- Chat logs are written to JSONL and can mask, store, or omit user text via `LOG_USER_TEXT_MODE`.
- When using OpenAI models, user questions and retrieved excerpts may be sent to the OpenAI API.
- Do not use sensitive production data in this MVP unless your data handling policies allow it.

## Known Limitations
- No production SSO or enterprise identity provider integration.
- No role-based authorization model.
- No multi-tenant isolation.
- No enterprise secret management.
- SQLite and file-based state are used for local simplicity.
- Intent routing is heuristic and tuned for predictable demo flows.
- Retrieval uses a local index and is not a replacement for production search infrastructure.

## Roadmap (Ideas)
- Add domain packs for healthcare, construction, finance, or compliance demos
- Add role-based access control for admin operations
- Add production authentication via SSO/OAuth
- Add stronger retrieval with re-ranking and better evaluation
- Add deployment templates for cloud environments

## Supporting Docs
- API summary: [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md)
- Architecture overview: [docs/ARCHITECTURE_OVERVIEW.md](docs/ARCHITECTURE_OVERVIEW.md)
- Demo scripts: [DEMO_SCENARIOS.md](DEMO_SCENARIOS.md)
- Teams setup: [TEAMS_SETUP.md](TEAMS_SETUP.md)
