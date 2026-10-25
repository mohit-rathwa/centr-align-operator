from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import database
from .config import APP_NAME, STATIC_DIR
from .connectors import registry
from .runtime import AgentRuntime, ClarificationError
from .schemas import ApprovalRequest, ClarificationRequest, CreateRunRequest
from .tools import list_source_invoices, public_invoice

runtime = AgentRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    await runtime.resume_queued()
    yield


app = FastAPI(
    title=APP_NAME,
    description="A bounded autonomous company operator prototype for invoice-to-AP work.",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    policy = database.get_policy()
    return {
        "ok": True,
        "service": APP_NAME,
        "planner": runtime.planner.provider,
        "workflow": "invoice-to-accounts-payable",
        "approval_threshold_inr": policy.get("accounts_payable", {}).get("approval_threshold_inr"),
        "max_single_invoice_inr": policy.get("accounts_payable", {}).get("maximum_single_invoice_inr"),
        "connectors": sorted({item["connector"] for item in registry.public_catalog()}),
        "tools": [item["name"] for item in registry.public_catalog()],
    }


@app.get("/api/memory")
async def company_memory() -> dict:
    """Return policy, vendor aliases, and recent outcomes the runtime uses."""
    return database.get_memory()


@app.get("/api/connectors")
async def connectors() -> dict:
    return {"tools": registry.public_catalog()}


@app.get("/api/invoices")
async def invoices() -> list[dict]:
    return [public_invoice(invoice) for invoice in list_source_invoices()]


@app.get("/api/ledger")
async def ledger() -> list[dict]:
    return database.list_payables()


@app.get("/api/runs")
async def runs() -> list[dict]:
    return database.list_runs(limit=15)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    result = database.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@app.post("/api/runs", status_code=202)
async def create_run(request: CreateRunRequest) -> dict:
    run_id = str(uuid4())
    database.create_run(run_id, request.goal, request.simulate_transient_failure)
    database.add_event(run_id, "system", "Task accepted", "Run and initial state persisted before execution starts.")
    runtime.launch(run_id)
    result = database.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Could not initialize run")
    return result


@app.post("/api/runs/{run_id}/approval")
async def decide_approval(run_id: str, request: ApprovalRequest) -> dict:
    row = database.get_run_row(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"Run is {row['status']}; it is not waiting for approval.")
    if row["approval_decision"] in {"approved", "rejected"}:
        raise HTTPException(status_code=409, detail="An approval decision has already been recorded.")
    note = request.note.strip() or ("Approved by demo reviewer." if request.decision == "approved" else "Declined by demo reviewer.")
    database.update_run(run_id, approval_decision=request.decision, approval_note=note)
    database.add_event(run_id, "approval_decision", f"Human marked request {request.decision}", note)
    # If a process restart ended the in-memory coroutine, the persisted state is resumable.
    runtime.launch(run_id)
    result = database.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Could not read run after approval")
    return result


@app.post("/api/runs/{run_id}/input")
async def provide_input(run_id: str, request: ClarificationRequest) -> dict:
    row = database.get_run_row(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        runtime.apply_user_input(run_id, request.message)
    except ClarificationError as exc:
        detail = str(exc)
        code = 404 if detail == "Run not found" else 409 if "not waiting" in detail else 400
        raise HTTPException(status_code=code, detail=detail) from exc
    result = database.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Could not read run after clarification")
    return result
