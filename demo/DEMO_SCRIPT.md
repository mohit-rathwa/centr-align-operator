# 2–3 minute live demo script

## Before recording

1. Start the service and open `/` and `/docs` in two tabs.
2. Clear the database only if you want a clean first-run recording; otherwise keep history to show persistence.
3. Use the local planner first so there are no API-key/network dependencies.

## Walkthrough

**0:00–0:20 — State the product bet**

“CentrAlign is asking for an AI employee that finishes an outcome, not a chatbot that suggests steps. I chose a narrow workflow with a real write boundary and a verification oracle: invoice intake into a sandbox AP ledger.”

**0:20–0:55 — Show normal completion**

Run the Acme Office Supplies task. Follow the trace: planner, search, extraction, policy validation, ledger write, read-after-write checks. Open `/api/ledger` or the evidence card to show the stored record.

**0:55–1:35 — Show human-in-the-loop**

Run the Northstar Components task. Explain that ₹1,28,400 is above the persisted ₹50,000 threshold. Point out that the process pauses before mutation. Decline first if you want to prove no write occurs, then rerun and approve to show the same workflow resuming and verifying.

**1:35–2:05 — Show reliability**

Enable the transient failure toggle and run the Acme task. Point out the retry event and the attempt number. Run it once more to demonstrate duplicate prevention and verification of the existing record.

**2:05–2:35 — Explain architecture**

“An optional LLM can help parse intent, but cannot register a tool or authorize a write. A fixed tool registry and state machine enforce the order, preconditions, retry budget, approval gate, idempotency, and verification. If I had more time, I’d replace the in-process worker with durable workflow execution, then add sandboxed browser connectors and confidence-aware PDF parsing.”

## Be precise during Q&A

- Say **optional LLM-assisted task parsing**, not that every decision is made by an LLM.
- Say **structured JSON demo documents**, not arbitrary PDF understanding.
- Say **sandbox ledger mutation**, not production finance-system integration.
- Describe SQLite/in-process execution as a prototype decision and explain the production migration path.
- Show the source code for the policy gate and unique constraint if asked how duplicate writes and approvals are enforced.
