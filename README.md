<p align="center">
  <img src="frontend/public/favicon.svg" alt="PeopleFlow AI logo" width="64" height="64" />
</p>

<h1 align="center">PeopleFlow AI</h1>

<p align="center">
  <a href="https://github.com/JDH-d/AI-in-HR_DEMO/actions/workflows/ci.yml"><img src="https://github.com/JDH-d/AI-in-HR_DEMO/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-a3b4fa?style=flat-square&labelColor=141b24" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/React-19-a3b4fa?style=flat-square&labelColor=141b24" alt="React 19" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-8ad0bf?style=flat-square&labelColor=141b24" alt="MIT license" /></a>
</p>

<p align="center">
  <a href="#quick-start"><strong>Quick start</strong></a>
  &nbsp;·&nbsp;
  <a href="#what-to-try">Demo flows</a>
  &nbsp;·&nbsp;
  <a href="#architecture">Architecture</a>
  &nbsp;·&nbsp;
  <a href="#development">Development</a>
</p>

PeopleFlow AI is a local-first HR operations demo. Employees ask questions against approved company documents, continue real conversations, request PTO, and report sick leave without leaving one workspace.

Managers keep the decisions. Knowledge admins keep the sources and answer quality under control. Every important state is persisted locally and remains easy to inspect.

> [!NOTE]
> This tech demo is designed for a short walkthrough of internal company questions, PTO approval, and sick-leave reporting, using a small set of sample scenarios.

## Quick start

**You need:** Windows PowerShell, Python 3.10+, and Node.js 22.12+. The launcher includes an installation menu for missing Python or Node.js. Git is optional if you download and extract the project ZIP.

### 1. Get the project

Download and extract the project ZIP, or clone this repository. Open the project folder containing `START.bat`.

### 2. Double-click START.bat

Open **[START.bat](START.bat)** in the project folder. No terminal commands or administrator launch are required.

The launcher prepares the local environment and dependencies on first use, starts the API and interface in the background, waits for them to become ready, and opens your browser. Later runs reuse the installed dependencies. If PeopleFlow is already running, it opens that instance instead of creating another one. Occupied default ports are replaced with available local ports.

Keep the launcher window for these controls:

| Key | Action |
| --- | --- |
| **1** | Open or start PeopleFlow |
| **2** | Restart after code or configuration changes |
| **3** | Stop PeopleFlow |
| **4** | Edit the saved API key and settings in `.env` |
| **5** | Open the log folder |
| **6** | Reinstall project dependencies if setup needs repair |
| **7** | Install Python or Node.js using Windows Package Manager, or open their download pages |
| **0** | Close the launcher and leave PeopleFlow running |
| **9** | Stop PeopleFlow and close the launcher |

The first dependency installation needs internet access. Python/Node installers may show their normal Windows permission dialog. Project setup does not replace your `.env`, chats, requests or documents. The knowledge index is prepared when needed instead of being rebuilt on every launch.

### 3. Add an OpenAI key (optional)

The launcher creates a missing `.env` automatically. To enable generated answers and embeddings, choose **4**, fill in `OPENAI_API_KEY`, save, then choose **2** to restart. The saved key is reused; you do not enter it at every launch.

> [!TIP]
> No API key yet? The demo works with deterministic answers and lexical document search. The sign-in screen has three demo accounts and a prefilled password.

### Demo accounts

Choose an account on the sign-in screen. The default password, `demo-password`, is already filled in.

| Account | Workspace | What it demonstrates |
| --- | --- | --- |
| Employee | Employee | Chat, history, PTO, sick leave |
| Manager | Manager | PTO decisions and sick-leave acknowledgement |
| Knowledge Admin | Knowledge | Documents, retrieval quality, metrics, AI settings |

## What to try

| Flow | Start here | What to look for |
| --- | --- | --- |
| **Grounded chat** | Ask <code>When is payroll processed?</code> | Streamed answer, approved sources, contextual follow-up, persistent history |
| **Chat history** | Start a **New Chat**, then reopen it from **Recents** | Saved exchanges; deleting a chat keeps its requests in **My requests** |
| **PTO** | Create time off as <code>employee</code> | Draft review, submission confirmation, manager approval or decline, shared timeline |
| **Sick leave** | Report an absence as <code>employee</code> | Availability-first form, direct report, manager acknowledgement instead of approval |
| **Knowledge operations** | Open Documents as <code>knowledge_admin</code> | Upload, safe index rebuild, lexical fallback, gaps, feedback, editable AI behavior |

A complete presenter walkthrough is available in [DEMO_SCENARIOS.md](DEMO_SCENARIOS.md).

All three workspaces support dark and light themes. Use the switch in the top-right corner; your choice is saved in the browser. Navigation and forms also adapt to smaller screens.

## Architecture

The React app talks only to the versioned FastAPI contract. Application services own the use cases; domain rules and persistence stay outside the HTTP layer.

~~~mermaid
flowchart LR
    E[Employee] --> UI[React SPA]
    M[Manager] --> UI
    K[Knowledge admin] --> UI

    UI --> API[FastAPI /api/v1]
    API --> CHAT[Chat service]
    API --> FLOW[Workflow service]
    API --> OPS[Knowledge operations]

    CHAT --> RAG[Retrieval]
    RAG --> DOCS[Approved documents]
    CHAT --> HISTORY[(Conversation SQLite)]
    FLOW --> REQUESTS[(Workflow SQLite)]
    OPS --> DOCS
~~~

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Interface | React 19, TypeScript, Vite, Tailwind | Three role-based workspaces |
| API | FastAPI, Pydantic | Authentication, validation, role boundaries |
| AI | OpenAI Responses API + embeddings | Generated answers and semantic retrieval |
| Fallback | Deterministic responses + lexical search | Usable demo without provider access |
| State | SQLite + atomic JSON files | Conversations, workflows, feedback, index metadata |
| Quality | Pytest, Vitest, Ruff, Biome, GitHub Actions | Repeatable local and CI verification |

For the full boundaries and persistence flows, read [docs/ARCHITECTURE_OVERVIEW.md](docs/ARCHITECTURE_OVERVIEW.md).

## Configuration

The local <code>.env</code> stays intentionally small:

~~~dotenv
OPENAI_API_KEY=your_openai_api_key

OPENAI_MODEL=gpt-5-nano-2025-08-07
EMBEDDING_MODEL=text-embedding-3-small
~~~

Add `OPENAI_API_KEY` to enable generated answers and embeddings. Model settings, runtime paths, authentication, CORS, logging, retries, and timeouts already have local defaults.

OpenAI requests may contain the employee question, recent conversation context, and retrieved document excerpts. Do not use sensitive production data in this demo unless your data policy allows it.

## Development

### Project map

~~~text
START.bat                    Double-click entry point for Windows
scripts/launcher.ps1          Setup, startup, browser launch, and control menu
run_demo.ps1 / stop_demo.ps1   Background service lifecycle
api/routes/                  HTTP endpoints and role checks
services/                    Chat, documents, history, settings, runtime wiring
rag/                         Indexing, retrieval, routing, prompts
workflow_domain.py           Request rules and validation
workflow_service.py          Authorization and use cases
workflow_repository.py       Operational SQLite queries
workflow_schema.py           Schema creation and migrations
frontend/src/features/       Employee, manager, request, and knowledge UI
documents/                   Approved demo source material
tests/                       Isolated backend coverage
~~~

### Contributor checks

Start the project with `START.bat` once to prepare the environment. The launcher installs application dependencies; install the additional Python test and lint tools before running checks:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\smoke_check.ps1
~~~

The smoke check runs backend lint and tests, the deterministic RAG evaluation, frontend checks and build, then exercises authentication, history, streaming, PTO, sick leave, documents, and metrics against an isolated API.

<details>
<summary><strong>Run checks individually</strong></summary>

~~~powershell
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m ruff format --check .
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m scripts.run_rag_eval
npm.cmd --prefix frontend run check
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
~~~

To verify the configured embedding provider instead of the deterministic lexical path:

~~~powershell
./.venv/Scripts/python.exe -m scripts.run_rag_eval --use-embeddings
~~~

</details>

GitHub Actions runs the deterministic gate on Python 3.10 and 3.12 with Node.js 22.
Windows-specific launcher tests run locally on Windows and are skipped on other platforms.

## Local data

- The launcher stores runtime databases and index files in <code>.demo_state/</code>.
- Launcher logs are written to <code>.demo_logs/</code>.
- Both directories are ignored by Git.
- Source documents live in <code>documents/</code> and may be Markdown, text, PDF, or DOCX.
- Conversation messages are stored in full until the chat is deleted. Deleting a chat removes its messages while preserving associated requests and their timelines.
- Quality logs mask employee text by default.

## Deliberate scope

- Demo authentication is intentionally simple and is not SSO or OAuth.
- Ask HR is a fixed interaction; it does not notify a real person.
- PTO approval and sick-leave reporting are the two implemented request workflows.
- PTO counts calendar days; company-specific working calendars are outside this demo.
- Local SQLite and files prioritize inspectability, not multi-instance deployment.
- The Docker image serves the FastAPI API only; use the launcher for the complete experience.

<details>
<summary><strong>Run the API-only Docker image</strong></summary>

~~~powershell
docker build -t peopleflow-ai .
docker run --rm -p 8000:8000 --env-file .env peopleflow-ai
~~~

Interactive API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

</details>

## Documentation

| Document | Use it for |
| --- | --- |
| [INSTRUCTIONS.txt](INSTRUCTIONS.txt) | Minimal local setup |
| [DEMO_SCENARIOS.md](DEMO_SCENARIOS.md) | Presenter walkthrough |
| [API endpoints](docs/API_ENDPOINTS.md) | Routes, roles, payloads, errors |
| [Architecture overview](docs/ARCHITECTURE_OVERVIEW.md) | Boundaries, storage, migrations |

## License

Released under the [MIT License](LICENSE).
