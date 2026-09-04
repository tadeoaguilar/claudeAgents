# Market Research Intelligence — Enterprise Web Application

## Overview

This document describes the enterprise web application built around the **Market Research Intelligence Pipeline** in `exercises/06-capstone-pipeline/`. The pipeline was originally a CLI tool; this layer wraps it in a FastAPI backend and a browser-based frontend without changing any core pipeline logic.

**What it does end-to-end:**

1. A user submits a research query (e.g. *"Tesla electric vehicles Q4 2024"*) via the web UI.
2. The backend starts a pipeline run in a background thread and immediately returns a `run_id`.
3. The browser connects to a Server-Sent Events stream and watches each pipeline stage check off in real time.
4. If the AI determines the risk score exceeds the threshold (> 0.70), the pipeline pauses and an approval panel appears in the browser.
5. The operator clicks **Approve** or **Reject** — the pipeline thread unblocks and continues or halts accordingly.
6. The finished markdown report is rendered directly in the browser, with an export-to-file button.

---

## Repository Layout

```
exercises/06-capstone-pipeline/
│
│  ── Core pipeline (minimally modified) ──────────────────────────
├── pipeline.py          Orchestrator: coordinates agents, skills, HITL, report assembly
├── agents.py            AgentWorker base class + NewsAgent, SentimentAgent, FinancialsAgent
├── tools.py             5 tool definitions + mock implementations
├── skills.py            SKILL_REGISTRY: generate_executive_summary, classify_risk
├── hitl.py              ★ Modified — HITL gate: stdin (CLI) or threading.Event (web)
├── observability.py     ★ Modified — PipelineTracer, SpanContext, TokenUsage, write_log_event
├── pipeline_runs.jsonl  Append-only structured event log (JSONL)
│
│  ── Web backend ──────────────────────────────────────────────────
├── backend/
│   ├── main.py          FastAPI application entry point
│   ├── state.py         RunRecord dataclass + RunRegistry (thread-safe in-memory store)
│   ├── runner.py        ThreadPoolExecutor bridge — runs blocking pipeline asynchronously
│   ├── requirements.txt Backend-only Python dependencies
│   └── routes/
│       ├── runs.py      POST/GET /api/v1/runs + GET /api/v1/runs/{id}
│       ├── reports.py   GET /api/v1/runs/{id}/report
│       ├── hitl.py      POST /api/v1/runs/{id}/approve|reject
│       └── events.py    GET /api/v1/runs/{id}/events  (SSE stream)
│
│  ── Web frontend ─────────────────────────────────────────────────
└── frontend/
    ├── index.html       Query submission form + run history table
    ├── run.html         Live stage progress, HITL approval UI, rendered report
    └── assets/
        ├── app.js       Vanilla JS: API client, SSE handler, page controllers
        └── styles.css   Dark enterprise CSS theme (no framework)
```

`★` = files that were modified from the original exercise; everything else is unchanged.

---

## Architecture

```
Browser
  │
  │  HTTP / SSE
  ▼
┌─────────────────────────────────────────────────┐
│  FastAPI  (uvicorn, single process)             │
│                                                 │
│  REST routes          SSE route                 │
│  POST /runs  ────►  BackgroundTask              │
│  GET  /runs           │                         │
│  GET  /runs/{id}      │  asyncio event loop     │
│  POST /approve        │  (non-blocking)         │
│  POST /reject         │                         │
│  GET  /report         │                         │
│                       │ run_in_executor         │
│  Static files         ▼                         │
│  /  → frontend/  ThreadPoolExecutor             │
│                  (up to 4 threads)              │
│                       │                         │
│              ┌────────┘                         │
│              │  worker thread (blocking OK)      │
│              ▼                                  │
│         Orchestrator.run_pipeline()             │
│              │                                  │
│    ┌─────────┼─────────┐                        │
│    ▼         ▼         ▼                        │
│  News    Sentiment  Financials   ← agentic loops │
│  Agent   Agent      Agent         (Claude API)  │
│    └─────────┼─────────┘                        │
│              ▼                                  │
│    generate_executive_summary  ← skill          │
│    classify_risk               ← skill          │
│              │                                  │
│         risk > 0.70?                            │
│         YES → hitl_gate() ──► threading.Event   │◄── POST /approve or /reject
│              │ wait(3600s)                       │    (unblocks the thread)
│              ▼                                  │
│         assemble & save report                  │
│              │                                  │
│         registry.update_status("delivered")     │
│         registry.append_event("pipeline_complete")│
└─────────────────────────────────────────────────┘
              │
              ▼
     pipeline_runs.jsonl   report_{run_id}.md
```

### Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Async model | `ThreadPoolExecutor` + `run_in_executor` | Pipeline is fully blocking (synchronous Claude API calls); this offloads it to a thread without touching any pipeline code |
| HITL synchronization | `threading.Event.wait()` | The pipeline lives in an OS thread, not the asyncio event loop — `asyncio.Event` is not thread-safe here |
| Live progress | Server-Sent Events (SSE) | Unidirectional push, auto-reconnects in all browsers, works through HTTP proxies; REST handles the reverse direction |
| SSE event store | Append-only `list` on `RunRecord` | Any client that reconnects (tab refresh, network blip) replays from `Last-Event-ID` without losing history |
| State store | In-memory `RunRegistry` | Single-process deployment; the `RunRegistry` interface is the only swap needed to move to Redis later |
| Run history | JSONL hydration on startup | Past CLI runs and server-session runs all appear in the history table — no database needed |
| Frontend | Vanilla JS + marked.js CDN | Zero build toolchain; the project is Python-only — no npm, no webpack, no Node.js required |

---

## Module Reference

### Pipeline Modules (original, mostly unchanged)

#### `pipeline.py` — Orchestrator

The top-level coordinator. Owns a `PipelineTracer` and drives the five stages sequentially.

```
Orchestrator.run_pipeline(query)
  Stage 1 → _run_agent(NewsAgent, ...)
  Stage 1 → _run_agent(SentimentAgent, ...)
  Stage 1 → _run_agent(FinancialsAgent, ...)
  Stage 2 → invoke_skill("generate_executive_summary", ...)
  Stage 2 → invoke_skill("classify_risk", ...)
  Stage 3 → hitl_gate(ApprovalRequest)  [conditional, risk > 0.70]
  Stage 4 → _assemble_report(...)
  returns dict: {status, report, run_id, elapsed_s, total_cost_usd}
```

#### `agents.py` — Worker Agents

`AgentWorker` base class implements the standard agentic loop:

```
while iterations < 10:
    response = anthropic.messages.create(...)
    if stop_reason == "end_turn":   break and return result
    if stop_reason == "tool_use":   execute tools, append results, continue
```

Context trimming fires when `input_tokens > TOKEN_BUDGET (6,000)` — it collapses the middle of the conversation into a single summary message while preserving the first user message and last two turns (API requirement).

Three concrete agents, each with a scoped system prompt and allowed tool list:

| Agent | Tools | Output fields |
|---|---|---|
| `NewsAgent` | `search_news`, `filter_by_date` | `key_events`, `overall_narrative` |
| `SentimentAgent` | `analyze_sentiment`, `get_social_metrics` | `sentiment_score`, `sentiment_label`, `social_momentum`, `key_signals` |
| `FinancialsAgent` | `get_financial_signals` | `financial_health`, `price_momentum`, `analyst_view`, `key_metrics` |

#### `tools.py` — Tool Definitions & Mocks

Five tools defined as Anthropic tool schemas and backed by mock implementations that return realistic-looking data.

| Tool | Purpose |
|---|---|
| `search_news` | Returns recent news articles for a query |
| `filter_by_date` | Filters articles to a rolling window (default 60 days) |
| `analyze_sentiment` | Scores sentiment for a list of texts |
| `get_social_metrics` | Returns social media mention counts and sentiment ratio |
| `get_financial_signals` | Returns stock price change, analyst consensus, P/E ratio |

#### `skills.py` — Skill Registry

Higher-level Claude API calls that synthesize multi-agent output into structured JSON. Skills are not tools — they are direct `messages.create` calls with no agentic loop.

| Skill | Input | Output |
|---|---|---|
| `generate_executive_summary` | `research_data` dict | `headline`, `situation`, `opportunity`, `watch_items`, `verdict` |
| `classify_risk` | `research_data` dict | `risk_score` (0–1), `risk_level`, `primary_risk_factors`, `mitigating_factors` |

#### `hitl.py` — Human-In-The-Loop Gate ★ Modified

`hitl_gate(request, event_registry=None)` now has two execution paths:

**CLI path** (`event_registry=None`, unchanged):
```python
_print_gate(request)
while True:
    answer = input("Approve? [y/n]: ")
    ...
```

**Web path** (`event_registry` is the `RunRegistry` singleton):
```python
def _web_gate(request, event_registry):
    event = event_registry.register_hitl(request.run_id, request)
    timed_out = not event.wait(timeout=3600)   # suspends thread, frees CPU
    if timed_out: return False
    return event_registry.get_hitl_decision(request.run_id)
```

The thread suspends for up to 1 hour. When the operator POSTs to `/api/v1/runs/{id}/approve` or `/reject`, the route calls `registry.resolve_hitl(run_id, approved)` which stores the decision and calls `event.set()`, waking the thread within milliseconds.

#### `observability.py` — Structured Logging ★ Modified

`LOG_FILE` is now configurable via environment variable:

```python
LOG_FILE = Path(os.getenv("PIPELINE_LOG_FILE",
                str(Path(__file__).parent / "pipeline_runs.jsonl")))
```

This allows the backend to point all sessions at the same canonical log file regardless of working directory. All other behavior is unchanged.

`write_log_event(event_type, data)` appends one JSON line to `pipeline_runs.jsonl`. Event types:

| Event | When |
|---|---|
| `pipeline_start` | Run begins |
| `agent_start` / `agent_end` | Each agentic loop starts/finishes |
| `tool_call` | Each tool invocation |
| `context_trimmed` | Context window trimming fires |
| `skill_invoke` | Each skill call |
| `hitl_triggered` | HITL gate is entered |
| `hitl_decision` | Operator approves/rejects (or timeout) |
| `pipeline_end` | Run completes (status: delivered / rejected) |

---

### Backend Modules

#### `backend/state.py` — Run Registry

The central nervous system of the web layer. All state lives here.

**`RunRecord` dataclass fields:**

| Field | Type | Description |
|---|---|---|
| `run_id` | `str` | 12-char hex UUID |
| `query` | `str` | Original research query |
| `status` | `RunStatus` | Current lifecycle state |
| `started_at` | `float` | Unix timestamp |
| `finished_at` | `float \| None` | Unix timestamp when terminal state reached |
| `error` | `str \| None` | Error message if status is `error` |
| `report` | `str \| None` | Final markdown report text |
| `risk_score` | `float \| None` | Risk score from `classify_risk` skill |
| `hitl_request` | `dict \| None` | HITL gate context (headline, risk level, reason) |
| `events` | `list[dict]` | Append-only SSE event log |
| `_hitl_event` | `threading.Event` | Private — blocks the pipeline thread at the HITL gate |
| `_hitl_decision` | `bool \| None` | Private — stores the operator's decision |

**Run status state machine:**

```
queued
  └─► running
        ├─► awaiting_approval
        │     ├─► approved ──► (continues running) ──► delivered
        │     └─► rejected
        ├─► delivered
        └─► error
```

**`RunRegistry` public methods:**

| Method | Description |
|---|---|
| `create(run_id, query)` | Creates and stores a new `RunRecord` |
| `get(run_id)` | Returns `RunRecord` or `None` |
| `list_all()` | Returns all records sorted newest-first |
| `update_status(run_id, status, **kwargs)` | Atomic status + field update |
| `append_event(run_id, event_type, data)` | Appends to the SSE event log |
| `register_hitl(run_id, request)` | Sets status to `awaiting_approval`, stores HITL context, returns `threading.Event` |
| `get_hitl_decision(run_id)` | Returns stored `_hitl_decision` |
| `resolve_hitl(run_id, approved)` | Stores decision, calls `event.set()` to unblock pipeline thread |

All mutations are protected by a single `threading.Lock`.

#### `backend/runner.py` — Pipeline Bridge

Bridges the async FastAPI world and the synchronous pipeline.

```python
_executor = ThreadPoolExecutor(max_workers=4)

async def launch_pipeline(run_id, query):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _run_pipeline_sync, run_id, query)
```

`_run_pipeline_sync` is the synchronous function that runs in the thread pool:

1. Inserts the pipeline directory into `sys.path`
2. Sets run status to `"running"` and emits `stage_start` (Stage 1)
3. **Monkey-patches** `pipeline.hitl_gate` to call the web-aware version that passes `event_registry=registry`
4. **Monkey-patches** `Orchestrator._run_agent` to emit `agent_complete` SSE events after each of the three agents finishes
5. **Monkey-patches** `pipeline.invoke_skill` to emit `stage_start` (Stage 2) + `skill_complete` SSE events
6. Calls `Orchestrator(run_id).run_pipeline(query)`
7. Restores all patched methods
8. On success: updates registry to `delivered`, saves `report_{run_id}.md`, emits `pipeline_complete`
9. On exception or rejection: updates registry to `error`/`rejected`, emits `pipeline_error`

The monkey-patching strategy lets the runner observe pipeline internals without modifying `pipeline.py` at all.

#### `backend/main.py` — FastAPI Application

```python
app = FastAPI(title="Market Research Intelligence", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"])
app.include_router(runs_router,    prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(hitl_router,    prefix="/api/v1")
app.include_router(events_router,  prefix="/api/v1")
app.mount("/", StaticFiles(directory="frontend/", html=True))
```

The static file mount at `/` serves `index.html` by default and handles `run.html`. API routes take priority over static files because they are registered first.

`main.py` also adds the pipeline directory to `sys.path` at startup, making all pipeline modules importable from the backend's subprocesses.

---

### API Reference

All endpoints are prefixed with `/api/v1`.

#### `POST /runs`

Start a new pipeline run.

**Request body:**
```json
{ "query": "Tesla electric vehicles Q4 2024" }
```

**Response** (HTTP 202):
```json
{ "run_id": "a1b2c3d4e5f6", "status": "queued" }
```

The pipeline starts immediately in a background thread. Poll `GET /runs/{id}` or subscribe to `GET /runs/{id}/events` to track progress.

#### `GET /runs`

List all runs. Merges in-memory registry (current server session) with historical entries parsed from `pipeline_runs.jsonl`.

**Response:**
```json
[
  {
    "run_id": "a1b2c3d4e5f6",
    "query": "Tesla electric vehicles Q4 2024",
    "status": "delivered",
    "started_at": 1700000000.0,
    "finished_at": 1700000120.0,
    "risk_score": 0.48,
    "hitl_request": null,
    "error": null,
    "event_count": 9
  }
]
```

#### `GET /runs/{run_id}`

Get status of a specific run.

**Response:** same shape as one element of `GET /runs`, including `hitl_request` when awaiting approval.

#### `GET /runs/{run_id}/report`

Retrieve the finished markdown report.

**Response:**
```json
{
  "run_id": "a1b2c3d4e5f6",
  "report_markdown": "# Market Intelligence Report\n..."
}
```

Falls back to reading `report_{run_id}.md` from disk for runs that completed before the current server session.

Returns **HTTP 404** if the run hasn't finished or the file doesn't exist.

#### `POST /runs/{run_id}/approve`

Approve a HITL gate. Only valid when `status == "awaiting_approval"`.

**Response:**
```json
{ "run_id": "a1b2c3d4e5f6", "decision": "approved" }
```

Returns **HTTP 409** if the run is not currently awaiting approval.

#### `POST /runs/{run_id}/reject`

Reject a HITL gate. Same constraints as approve.

**Response:**
```json
{ "run_id": "a1b2c3d4e5f6", "decision": "rejected" }
```

#### `GET /runs/{run_id}/events`

Server-Sent Events stream. Connect with `EventSource` in the browser. Supports `Last-Event-ID` for reconnection without replaying already-received events.

**Event types:**

| Event | When | Payload |
|---|---|---|
| `stage_start` | Before each stage | `{stage: 1\|2\|3, label: "..."}` |
| `agent_complete` | After each of 3 agents | `{agent: "news_agent", elapsed_ms: 1200, cost_usd: 0.012}` |
| `skill_complete` | After each of 2 skills | `{skill: "generate_executive_summary"}` |
| `hitl_required` | When risk > threshold | `{risk_score: 0.82, risk_level: "Critical", headline: "...", reason: "..."}` |
| `pipeline_complete` | Report ready | `{report_path: "...", elapsed_s: 45.2, total_cost_usd: 0.048}` |
| `pipeline_error` | On exception or rejection | `{error: "..."}` or `{reason: "..."}` |
| `terminal` | Stream closing | `{status: "delivered"\|"rejected"\|"error"}` |

---

### Frontend Modules

#### `frontend/index.html` — Home Page

Two sections:

- **Submit panel**: text input + "Run Pipeline" button. On submit, POSTs to `/api/v1/runs`, receives `run_id`, and redirects to `run.html?id={run_id}`.
- **History panel**: table of all runs fetched from `GET /api/v1/runs`, auto-refreshed every 10 seconds. Each row is clickable and navigates to the run detail page.

#### `frontend/run.html` — Run Detail Page

URL: `run.html?id={run_id}`

Four state-driven panels — shown/hidden by JavaScript based on SSE events:

| Panel | Shown when | Hidden when |
|---|---|---|
| Progress tracker | Always visible while running | — |
| HITL approval | `hitl_required` event received | Operator acts or `terminal` fires |
| Report | `pipeline_complete` event received | — |
| Error | `pipeline_error` or `terminal` with error/rejected | — |

#### `frontend/assets/app.js` — Application Logic

**`RunEventStream` class:**
- Wraps the browser's `EventSource` API
- Listens for all named event types and dispatches to handler callbacks
- The browser automatically reconnects on network interruption using the `Last-Event-ID` header

**`api` object:**
- Typed `fetch` wrappers for every REST endpoint
- All methods return Promises resolving to parsed JSON

**`IndexPage` controller:**
- `init()` binds the form submit handler and starts the 10s history refresh timer
- `_loadHistory()` fetches runs and renders the table, including colored status badges

**`RunPage` controller:**
- `init()` reads `?id=` from the URL, connects the SSE stream, starts a 3s status polling loop, and binds button handlers
- SSE handlers update DOM incrementally as events arrive:
  - `stage_start` → activates spinner on the corresponding stage row
  - `agent_complete` → marks the agent chip green; when all 3 done, marks Stage 1 complete
  - `skill_complete` → marks skill chip green; when both done, marks Stage 2 complete
  - `hitl_required` → populates HITL panel with risk data and shows it
  - `pipeline_complete` → fetches report via REST, renders with `marked.parse()`, shows report panel
  - `pipeline_error` / `terminal` → shows error panel with appropriate message

**`escHtml` utility:** sanitizes untrusted strings before inserting into DOM innerHTML.

#### `frontend/assets/styles.css` — Dark Enterprise Theme

CSS custom properties drive the entire color palette:

```css
:root {
  --bg: #0f1117;       /* page background */
  --surface: #1a1d27;  /* card background */
  --border: #2a2d3e;   /* card borders */
  --accent: #4f8ef7;   /* primary blue */
  --green: #22c55e;    /* success / approved */
  --amber: #f59e0b;    /* HITL warning */
  --red: #ef4444;      /* error / rejected */
}
```

No CSS framework — all layout uses flexbox and CSS grid.

---

## Dependencies

### Pipeline (existing)

```
anthropic>=0.40.0       Claude API SDK
python-dotenv>=1.0.0    Load ANTHROPIC_API_KEY from .env
rich>=13.0.0            Terminal output formatting
```

### Backend (new)

Listed in `backend/requirements.txt`:

```
fastapi>=0.111.0        Web framework
uvicorn[standard]>=0.29.0  ASGI server (includes websockets, httptools)
sse-starlette>=1.8.2    Server-Sent Events support for FastAPI
python-multipart>=0.0.9 Required by FastAPI for form parsing
```

### Frontend

```
marked.js (CDN)         Markdown → HTML renderer, loaded from jsdelivr.net
```

No npm, no build step, no bundler required.

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Your Anthropic API key (set in `.env`) |
| `PIPELINE_LOG_FILE` | No | `pipeline_runs.jsonl` (beside pipeline.py) | Override the JSONL log path |

---

## Running the Application

### Prerequisites

```bash
# From the repo root
pip install -r requirements.txt          # pipeline dependencies
pip install -r exercises/06-capstone-pipeline/backend/requirements.txt  # backend
```

Ensure `ANTHROPIC_API_KEY` is set in `exercises/06-capstone-pipeline/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

### Start the Server

```bash
cd exercises/06-capstone-pipeline/backend
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

`--reload` enables hot-reload on file changes (development mode). Remove it for production.

### Access Points

| URL | Description |
|---|---|
| `http://localhost:8000/` | Home page — query form and run history |
| `http://localhost:8000/run.html?id={run_id}` | Detail page for a specific run |
| `http://localhost:8000/api/v1/runs` | REST API (JSON) |
| `http://localhost:8000/docs` | FastAPI auto-generated API docs (Swagger UI) |
| `http://localhost:8000/redoc` | Alternative API docs (ReDoc) |

### CLI Still Works

The original pipeline is unchanged for CLI use:

```bash
cd exercises/06-capstone-pipeline
python pipeline.py "Apple Q4 2024"
```

The HITL gate falls back to `input()` when no `event_registry` is passed.

### Analyze Past Runs

```bash
cd exercises/06-capstone-pipeline
python summarize_run.py
```

Prints a cost/latency summary table of all runs recorded in `pipeline_runs.jsonl`.

---

## HITL Gate — Detailed Flow

The following sequence shows how a high-risk pipeline run is handled when `risk_score > 0.70`:

```
Worker Thread (ThreadPoolExecutor)          Asyncio Event Loop (main thread)
─────────────────────────────────────────   ──────────────────────────────────────

Orchestrator.run_pipeline()
  classify_risk → score = 0.85
  hitl_gate(request, event_registry=registry)
    _web_gate(request, registry)
      event = registry.register_hitl(run_id, request)
        ← sets run.status = "awaiting_approval"
        ← appends "hitl_required" to run.events
        ← returns threading.Event (not yet set)
      event.wait(timeout=3600)              SSE generator polls run.events every 500ms
      [THREAD SUSPENDED]          ───►      yields {event: "hitl_required", data: {...}}
                                            Browser shows approval panel
                                 ◄───      POST /api/v1/runs/{id}/approve
                                            registry.resolve_hitl(run_id, True)
                                              run._hitl_decision = True
                                              run.status = "approved"
                                              run._hitl_event.set()
      [THREAD RESUMES]
      approved = registry.get_hitl_decision(run_id)  → True
      return True
  assemble_report(...)
  registry.update_status("delivered")
  registry.append_event("pipeline_complete")
                                            SSE generator yields "pipeline_complete"
                                            Browser fetches report, renders markdown
```

**Timeout:** If no operator action occurs within 3600 seconds (1 hour), `event.wait()` returns `False` and the gate auto-rejects with status `"error"`.

---

## Validation Checklist

All modules were validated with:

```bash
# Syntax check
python -m py_compile hitl.py observability.py pipeline.py agents.py tools.py skills.py

cd backend
python -m py_compile state.py runner.py main.py
python -m py_compile routes/runs.py routes/reports.py routes/hitl.py routes/events.py

# Deep import validation
python -c "import main; print('OK')"

# JavaScript syntax
node -e "new Function(require('fs').readFileSync('frontend/assets/app.js', 'utf8')); console.log('OK')"
```

**Live smoke test results:**
- `GET /api/v1/runs` → correctly hydrated 2 historical runs from `pipeline_runs.jsonl` ✓
- `POST /api/v1/runs` → returned `{"run_id": "...", "status": "queued"}` HTTP 202 ✓
- `GET /api/v1/runs/{id}` → showed `status: "running"` with `event_count` incrementing ✓
- `GET /` → HTTP 200, `index.html` served ✓
- `GET /run.html` → HTTP 200, `run.html` served ✓

---

## Azure Deployment

### Infrastructure Overview

The application is deployed to **Azure Container Apps** — the only managed Azure service whose HTTP ingress timeout can be configured high enough to support the 1-hour HITL gate. (Azure App Service has a hard 230-second ARR ceiling that cannot be raised.)

```
Azure Resource Group: rg-mri-pipeline-prod
│
├── Azure Container Registry (Basic)   acrmripipelineprod.azurecr.io
│   └── image: mri-pipeline:{git-sha}
│
├── Azure Key Vault                    kv-mri-pipeline-prod
│   └── secret: anthropic-api-key
│
├── Azure Storage Account              stmripipelineprod
│   └── File Share: pipeline-data      ← mounted at /data inside container
│       ├── pipeline_runs.jsonl
│       └── report_*.md
│
├── User-Assigned Managed Identity     id-mri-pipeline-prod
│   ├── AcrPull on ACR                 (image pull without stored credentials)
│   └── Key Vault Secrets User on KV  (secret read without stored credentials)
│
├── Container Apps Environment         cae-mri-pipeline-prod
│
└── Container App                      ca-mri-pipeline-prod
    ├── minReplicas: 1  maxReplicas: 1  ← CRITICAL — see constraints below
    ├── workers: 1                      ← CRITICAL — single RunRegistry
    ├── ingress: HTTP/1.1, external     ← SSE-compatible transport
    ├── volume: /data → File Share      ← persistent JSONL + reports
    └── env:
        ANTHROPIC_API_KEY  ← secretRef (never plaintext)
        DATA_DIR=/data
        PIPELINE_LOG_FILE=/data/pipeline_runs.jsonl
```

### Deployment Constraints

| Constraint | Setting | Consequence if violated |
|---|---|---|
| `minReplicas: 1` | Must be 1 | Scale-to-zero wipes in-memory RunRegistry; active runs are lost |
| `maxReplicas: 1` | Must be 1 | Two replicas = two RunRegistries; approve on replica A cannot unblock thread on replica B |
| `--workers 1` | Set in Dockerfile CMD | Multiple uvicorn workers = separate Python processes = separate RunRegistries |
| SSE heartbeat | Every 500 ms idle | Without heartbeat, Azure ingress idle timer drops SSE connections; browser reconnects but operators lose context during HITL |

### Files Added / Modified for Azure

| File | Purpose |
|---|---|
| `Dockerfile` | Container image — Python 3.12-slim, two-layer caching, `--workers 1` CMD |
| `.dockerignore` | Excludes `.env`, `__pycache__`, runtime JSONL/report files, `infra/` |
| `infra/main.bicep` | All Azure resources in dependency order (ACR → KV → Storage → Identity → Container Apps Env → Container App) |
| `infra/main.bicepparam` | Non-secret parameter values; `anthropicApiKey` passed only at deploy time |
| `.gitlab-ci.yml` | Two-stage CI/CD: build+push Docker image, deploy new Container App revision |
| `backend/runner.py` | Added `import os` + `DATA_DIR = Path(os.getenv("DATA_DIR", PIPELINE_DIR))` |
| `backend/routes/runs.py` | `LOG_FILE` now derived from `DATA_DIR` |
| `backend/routes/reports.py` | Report file lookup now uses `DATA_DIR` |
| `backend/routes/events.py` | SSE heartbeat added to prevent Azure ingress idle timeout |

### One-Time Provisioning

```bash
# 1. Create resource group
az group create --name rg-mri-pipeline-prod --location eastus2

# 2. Deploy all resources via Bicep (pass the API key only here, never store it)
az deployment group create \
  --resource-group rg-mri-pipeline-prod \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters anthropicApiKey="sk-ant-api03-..." \
  --name initial-deploy

# 3. Capture outputs
ACR=$(az deployment group show -g rg-mri-pipeline-prod -n initial-deploy \
      --query "properties.outputs.acrLoginServer.value" -o tsv | cut -d. -f1)
FQDN=$(az deployment group show -g rg-mri-pipeline-prod -n initial-deploy \
       --query "properties.outputs.containerAppFqdn.value" -o tsv)

# 4. Build and push initial image
az acr login --name "$ACR"
docker build -f Dockerfile -t "${ACR}.azurecr.io/mri-pipeline:initial" .
docker push "${ACR}.azurecr.io/mri-pipeline:initial"

# 5. Point the Container App at the initial image
az containerapp update \
  --name ca-mri-pipeline-prod \
  --resource-group rg-mri-pipeline-prod \
  --image "${ACR}.azurecr.io/mri-pipeline:initial"

echo "App live at: https://${FQDN}"
```

### CI/CD (GitLab)

After the one-time provisioning, every push to `main` runs the two-stage GitLab CI/CD pipeline defined in `.gitlab-ci.yml`:

1. **build** — builds the Docker image tagged with `$CI_COMMIT_SHORT_SHA`, pushes to ACR
2. **deploy** — runs `az containerapp update --image ...` to activate the new revision, then smoke-checks `GET /api/v1/runs` for HTTP 200

Required GitLab CI/CD Variables (masked): `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ACR_NAME`, `RESOURCE_GROUP`, `CONTAINER_APP_NAME`, `CONTAINER_APP_FQDN`.

### SSE and HITL in Production

Azure Container Apps enforces an HTTP ingress timeout (default 240 s). During a HITL pause — where the browser SSE stream is held open waiting for operator approval — this timer would normally drop the connection.

The mitigation is a **heartbeat event** emitted every 500 ms when no real pipeline events are pending (`routes/events.py`). This resets the proxy idle timer continuously. If the connection is dropped anyway (network blip, tab refresh), the browser `EventSource` API auto-reconnects and the `Last-Event-ID` replay mechanism resumes from where it left off. The pipeline thread inside the container is unaffected — it is blocked on `threading.Event.wait(timeout=3600)` and does not care about the HTTP layer.
