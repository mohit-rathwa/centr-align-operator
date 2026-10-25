# Founding Engineer technical walkthrough

Use this as speaking notes, not as a script to memorize word-for-word. Stay precise about what runs today and what is a production next step.

## 60–90 second project explanation

“I treated the prompt as a reliability and execution problem, not just an LLM prompting problem. I picked invoice intake because I could make the complete business outcome observable: the operator has to find the right source invoice, apply company rules, create a record, and prove the record matches the source.

The FastAPI layer persists the run first. A planner converts the natural-language task into a typed, bounded workflow. The runtime chooses each next action from the latest observation, and only calls an allowlisted tool. The tool layer reads the local source files, extracts fields, checks the vendor list, amount/date constraints and duplicates, and writes to a SQLite AP ledger. Invoices above ₹50,000 pause before the write. After creating a record, the runtime reads it back and compares the source ID, vendor, amount, due date, and status; success is impossible unless those checks pass.

I also added a transient-failure hook to demonstrate bounded retries and an idempotent write boundary to handle repeated tasks. I deliberately kept the workflow narrow instead of faking support for arbitrary desktop apps. In production I’d replace the local worker with durable workflow execution, then add sandboxed connectors, tenant isolation, scoped permissions, and confidence-aware document extraction.”

## JD evaluation map

| JD evaluation area | What this prototype demonstrates | What to show live |
|---|---|---|
| Autonomy | Goal interpretation and next-action selection based on observed state | A task that only states the desired outcome, not each click |
| Execution | Reads source data and persists a real ledger mutation in SQLite | Open the resulting ledger record/API response |
| Reliability | Bounded retries, failure audit events, restart recovery, idempotency | Inject one transient failure; rerun the same invoice |
| Verification | Read-after-write comparison over five fields | Expand the verification evidence card |
| Generalization | Workflow logic is separated from invoice fixtures and company policy | Show new sample suppliers being data/config, not a new code path |
| Engineering quality | Typed API contracts, isolated tool registry, durable run/event records, uniqueness constraint, automated tests | Open `runtime.py`, `tools.py`, `database.py`, then run `pytest` |
| Product thinking | Ambiguity stops for clarification; policy-sensitive writes stop for approval; no false success | Use a no-vendor task and a high-value invoice |
| Technical understanding | Explicit trust boundaries and production evolution path | Explain why planning is probabilistic but permissioning/verification are deterministic |

## Why I prefer the Founding Engineer role

“I’m most interested in owning the system end to end: deciding what the runtime guarantees, shaping the tool and connector contracts, implementing the execution path, and testing failure cases—not only wiring an LLM into an interface. This prototype is my attempt to show architecture choices and their trade-offs in running code. I’m also comfortable saying where the demo stops and what I’d harden next.”

Do not present this as professional production-agent experience. Present it as an independently built prototype and a clear way you reason about a production system.

## Likely technical questions

### Why not let the LLM choose and execute every tool call?

Because model output is probabilistic and user content can be adversarial. The model may help interpret intent; it does not get arbitrary tool access, cannot alter the runtime's approval threshold, and cannot certify its own success. The runtime owns preconditions, action order, write policy, retry limits, and verification.

### What is actually autonomous if the workflow is bounded?

The system receives an outcome rather than detailed steps, selects the source from company context, derives the next action from previous tool observations, stops on ambiguity/policy failures, retries transient faults, waits for approval, and verifies the resulting record. It is autonomous inside a well-defined permission boundary rather than claiming unrestricted autonomy.

### How do you prevent duplicate writes across retries or concurrent runs?

The runtime checks for an existing source invoice before writing. The database has a unique constraint on `source_invoice_id`, and the write path takes an immediate SQLite transaction before checking and inserting. If a run crashes after the insert but before it records the tool result, a resumed run finds the existing record and verifies it instead of creating another.

### What happens if the process restarts during a run?

Run state and events are persisted. On startup, queued, running, and approval-waiting tasks are made resumable. The next action is derived from saved observations. The ledger write is idempotent, which handles the critical crash window around a successful write. This simple implementation is still a local single-process worker; production should use durable workflow orchestration, leases/heartbeats, and explicit cancellation semantics.

### Why approval before the write rather than after?

The approval gate is on the mutation boundary. The high-value invoice stays out of the ledger until a persisted human decision is received. The model cannot approve itself. In this demo, the approval UI is not authenticated because it is sandbox-only; production would require an authenticated approver, role checks, a signed audit decision, and separation of requester/approver where appropriate.

### How would you add browser or desktop tools?

Use an explicit connector/tool interface with typed inputs and outputs, least-privilege credentials, per-tenant capability grants, timeouts, action budgets, and an observation contract. Run computer-use agents in isolated workers. Treat webpage text as untrusted input, pause before irreversible actions, save artifacts/screenshots as evidence, and verify application state after the action. Do not expose arbitrary shell or unrestricted network access to the planning model.

### How would you support PDFs and scanned invoices?

Add a parser adapter that returns typed fields with confidence and provenance: source page/bounding box or text span for each extracted value. Validate totals, currency and due dates. Route low-confidence or contradictory fields to human review. The current prototype uses structured JSON fixtures and should not be described as arbitrary-PDF understanding.

### What would you measure?

Task completion rate, wrong-vendor selection rate, missing-field detection, policy-bypass rate, duplicate-write rate, false verification rate, recovery rate after injected faults, approval turnaround, latency and model/tool cost. A high task-completion metric alone is not enough if the agent sometimes writes to the wrong supplier.

### Why SQLite and an in-process worker?

They keep the deadline prototype reproducible with one command while still demonstrating persistent state, audit events, unique constraints and restart handling. They are intentionally not multi-tenant production infrastructure. I would retain the tool/runtime contracts and migrate the storage/queue layer to Postgres plus a durable workflow engine.

## Files worth opening during Q&A

- `backend/app/planner.py`: trust boundary between the user's goal, optional LLM extraction, and approved supplier memory.
- `backend/app/runtime.py`: state machine, retry loop, step budget, approval pause, evidence-backed completion condition.
- `backend/app/tools.py`: preconditions and actual tool behavior.
- `backend/app/database.py`: persistent event state and atomic idempotent write boundary.
- `backend/tests/test_agent.py`: behavior-focused regression tests.
- `docs/ARCHITECTURE.md`: diagram, API contract, data model, trade-offs, production plan.
