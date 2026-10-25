# CentrAlign Operator — AI Employee Proof of Concept

> **Founding Engineer submission prototype:** a bounded autonomous company operator that turns a natural-language invoice task into a persistent, policy-checked, verified accounts-payable record.

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB) ![FastAPI](https://img.shields.io/badge/API-FastAPI-009688) ![State](https://img.shields.io/badge/state-SQLite-003B57) ![Tests](https://img.shields.io/badge/tests-automated-success)

## Why this prototype

CentrAlign's prompt asks for a system that can understand an outcome, plan actions, use tools, observe results, recover, ask for approval, and verify completion. This prototype focuses on one workflow where those claims can be tested instead of simulated:

**Find the latest supplier invoice → extract fields → apply company policy → request approval when required → write to an AP ledger → read it back and verify.**

The sample invoice files are local JSON documents. The ledger, company policy memory, run state, approval decisions, and event timeline are persistent SQLite records. The UI shows what the agent actually did and what evidence supports its result.

## What is implemented

- Natural-language task entry and a typed workflow plan.
- Optional LLM-assisted intent/vendor extraction through an OpenAI-compatible endpoint; works locally with no API key using a deterministic fallback.
- An allowlisted tool registry; the model cannot add arbitrary tools or invoke shell/URL execution.
- Observation-driven bounded agent loop with explicit preconditions and stop states.
- Source invoice search, field extraction, vendor-policy validation, amount/date checks, and duplicate detection.
- Persistent human approval gate at **₹50,000** before a payable is written.
- Idempotent ledger writes backed by a database uniqueness constraint.
- Retry policy for transient tool errors, with an optional one-click fault-injection demo.
- Read-after-write verification of source invoice, vendor, amount, due date, and ledger status.
- Persistent run state and audit events; queued/running work can be recovered when the service restarts.
- Responsive UI, recent runs, company policy view, source workspace, AP ledger evidence, and interactive API docs.
- Tests for normal completion, transient retry, approval, rejection, duplicate protection, ambiguity, and unsupported tasks.

## How it maps to the evaluation criteria

| Area | Concrete proof in this repo |
|---|---|
| **Autonomy** | One goal triggers plan creation and an observation-driven next-action loop; ambiguous tasks pause rather than guess. |
| **Execution** | The tools read local source documents and write an actual record to the SQLite AP ledger. |
| **Reliability** | Bounded retry budget, fault-injection demo, restart recovery, unique source-invoice key, and atomic write boundary. |
| **Verification** | Read-after-write checks compare five fields; success is gated on all checks passing. |
| **Generalization** | Tool/runtime contracts are separated from invoice fixtures and company policy, while the workflow boundary stays explicit. |
| **Engineering / product judgment** | Persistent runs and audit events, least-privilege tool registry, pre-write approval, and honest scope limits. |

The **first four** are the central autonomy/execution/reliability/verification proof points. The broader discussion of generalization, architecture, security, and production scaling is in the technical walkthrough.

## Run locally

**Requirements:** Python 3.10+ (3.12 recommended). No Node installation, database server, or API key is required.

```bash
# from this repository directory
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir backend --reload
```

Open **http://127.0.0.1:8000** for the demo UI, or **http://127.0.0.1:8000/docs** for the API. The database is created automatically at `backend/data/agent.db`; delete that file only when you intentionally want to reset demo history and ledger data.

### Optional LLM planner

Copy `.env.example` to `.env`, add an API key for an OpenAI-compatible chat-completions endpoint, and set the model name appropriate for your provider. Then restart the service. Without a key, the local planner recognizes the demo vendors and still executes the same guarded runtime. With a key, the model is used only to parse supported intent and select a vendor from company policy; it does **not** directly execute tools or authorize writes.

> Keep `.env` private. The project uses only synthetic examples and should not be pointed at real accounts or company data.

### Run tests

```bash
pytest -q backend/tests
```

### Run with Docker

```bash
cp .env.example .env       # optional; works without an API key
# Windows PowerShell: Copy-Item .env.example .env
docker compose up --build
```

Open http://localhost:8000. Docker persists the SQLite database in a named volume.

## Try the three core demos

### 1. Normal autonomous completion

Use this task:

> Find the latest invoice from Acme Office Supplies, extract the amount and due date, enter it into our AP system, and tell me once it is verified.

Expected: search selects `INV-2026-104`, required fields are extracted, company policy is checked, a payable is written, and all read-after-write checks pass.

### 2. Approval and resumption

Use:

> Find the latest invoice from Northstar Components, record it in accounts payable, and show me the verified ledger entry.

Expected: `INV-2026-105` is extracted and validated. At ₹1,28,400, it crosses the ₹50,000 threshold. The runtime pauses **before mutation**, shows the amount and rationale, and waits for a human decision. Approving resumes the same run; declining leaves the ledger unchanged.

### 3. Failure recovery

Turn on **Inject one temporary tool failure** and run the normal Acme task.

Expected: the first tool call fails once, an explicit retry event appears, the bounded retry succeeds, and the task is still verified. This is a controlled test hook, not a real external-service fault.

For duplicate safety, run the Acme task a second time. The unique source-invoice constraint and pre-write check prevent a second payable and the existing record is verified instead.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the runtime diagram, endpoint contract, data model, safety invariants, trade-offs, and production evolution path.

Core modules:

| Module | Responsibility |
|---|---|
| `backend/app/main.py` | FastAPI endpoints, worker lifecycle, approval API |
| `backend/app/planner.py` | Goal interpretation, optional LLM extraction, offline fallback |
| `backend/app/runtime.py` | Bounded goal-plan-execute-observe-adapt-verify loop, retries, approval pause |
| `backend/app/tools.py` | Allowlisted invoice and ledger tools; field/policy checks |
| `backend/app/database.py` | Persistent run state, audit events, company memory, idempotent ledger writes |
| `backend/app/static/index.html` | Self-contained responsive dashboard and live execution trace |
| `backend/tests/test_agent.py` | Behavior-level checks for core safety/reliability paths |

## Engineering decisions / limitations

**Deliberate boundary:** this is not a general-purpose computer-use agent. It runs one workflow end-to-end with real local file reads and persistent ledger mutations. That is narrower than arbitrary browser/desktop use, but easier to inspect, evaluate, and trust.

**Local worker:** the in-process async worker and SQLite are deadline-friendly choices. SQLite, local JSON source documents, and the local approval UI are not multi-tenant production infrastructure. A production build would move execution to a durable workflow engine or broker-backed queue, use Postgres with migrations, isolate tenants, use managed secrets/OAuth connector grants, and add observability, quotas, retention controls, and connector-specific sandboxing.

**Invoice parser:** current source documents are structured JSON, so extraction is deterministic. Supporting arbitrary PDF/image invoices would need a parser/OCR adapter, confidence values, and mandatory review when fields are uncertain. The prototype should not claim that arbitrary document understanding is solved.

**Browser/computer tools:** not included yet. The tool registry is the intended extension point; a browser tool should be sandboxed, have narrow permissions, expose observations, and preserve approval and verification contracts.

**No real business side effects:** the ledger is synthetic. Approval buttons affect only this demo database.

## What I'd build next

1. Replace the in-process worker with durable workflow execution, lease/heartbeat handling, cancellation, and recovery tests.
2. Add a connector interface with per-tenant capabilities and scoped OAuth grants; ship a sandbox browser adapter before permitting live writes.
3. Ingest PDFs with confidence-aware extraction, provenance spans, and mandatory human review for low-confidence fields.
4. Build an evaluation suite with task success, wrong-vendor rate, policy-bypass rate, duplicate-write rate, recovery rate, and verification false-positive rate.
5. Add tenant-aware RBAC, signed approval records, encrypted artifacts, rate limits, cost budgets, tracing, metrics, and audit retention.

## Submission checklist

- [x] GitHub-ready source tree and dependency list
- [x] Reproducible local setup and Docker option
- [x] Architecture, technical decisions, assumptions, and known limitations
- [x] Working UI/API with persistent state and evidence
- [x] Automated tests for key reliability and safety paths
- [ ] Push to your GitHub and replace the README with the public repository URL if needed
- [ ] Record a 2–3 minute demo using `demo/DEMO_SCRIPT.md`
- [ ] Verify the current submission deadline and submit the repository/video link in the form

---

**Positioning for the technical walkthrough:** emphasize the separation between probabilistic goal parsing and deterministic execution controls; show the approval gate before the write, the injected retry, the idempotency check, and the read-after-write verification. Explain which parts are a prototype and the concrete steps required to productionize them.
