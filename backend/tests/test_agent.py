from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from app import database
from app import planner as planner_module
from app.runtime import AgentRuntime


# ----------------------------------------------------------------------------- fake LLM
def tool(name: str, reason: str = "") -> dict:
    return {"action": "tool", "tool": name, "reason": reason}


def finish(status: str, summary: str = "") -> dict:
    return {"action": "finish", "status": status, "summary": summary}


class FakeLLM:
    """Deterministic stand-in for the decision model: replays a scripted sequence of JSON decisions.

    It records every prompt it was given. If the runtime asks for more decisions than were scripted,
    it answers `finish failed` so the test fails fast with a readable summary instead of looping.
    """

    def __init__(self, script: list[dict | str]) -> None:
        self._script = list(script)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._script:
            return json.dumps(finish("failed", "FakeLLM script exhausted: runtime asked for more decisions than the test scripted."))
        item = self._script.pop(0)
        return item if isinstance(item, str) else json.dumps(item)


# A sensible model's decisions for the invoice->AP task. The tools themselves still enforce policy.
HAPPY_PATH = [
    tool("search_invoices"),
    tool("extract_invoice"),
    tool("validate_invoice"),
    tool("create_payable"),
    tool("verify_payable"),
    finish("completed", "Invoice entered and verified."),
]
# High-value invoices: the first create_payable pauses for approval, the model calls it again once approved.
APPROVAL_PATH = [
    tool("search_invoices"),
    tool("extract_invoice"),
    tool("validate_invoice"),
    tool("create_payable"),
    tool("create_payable"),
    tool("verify_payable"),
    finish("completed", "Invoice approved, entered and verified."),
]
# A model that stops safely when the search is ambiguous.
STOP_AMBIGUOUS = [tool("search_invoices"), finish("needs_input", "Several suppliers match; please choose one vendor.")]


# ----------------------------------------------------------------------------- fixtures / helpers
@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "agent-test.db")
    # No network in tests: the planner then uses its offline path (no real LLM call for intake).
    monkeypatch.setattr(planner_module, "OPENAI_API_KEY", "")
    database.init_db()


def create_run(goal: str, simulate_failure: bool = False) -> str:
    run_id = str(uuid4())
    database.create_run(run_id, goal, simulate_failure)
    database.add_event(run_id, "system", "Test task accepted", "Test setup")
    return run_id


def make_runtime(script: list[dict | str]) -> tuple[AgentRuntime, FakeLLM]:
    llm = FakeLLM(script)
    return AgentRuntime(llm=llm), llm


def run_agent(run_id: str, script: list[dict | str]) -> FakeLLM:
    runtime, llm = make_runtime(script)
    asyncio.run(runtime._execute(run_id))
    return llm


# ----------------------------------------------------------------------------- end-state tests
def test_normal_invoice_completes_and_verifies():
    run_id = create_run("Find the latest invoice from Acme Office Supplies, enter it in AP, and verify the record.")
    llm = run_agent(run_id, HAPPY_PATH)
    run = database.get_run(run_id)
    assert run["status"] == "completed"
    assert run["state"]["verification_result"]["verified"] is True
    assert run["state"]["verification_result"]["checks"] == {
        "source_invoice_id": True,
        "vendor": True,
        "amount_inr": True,
        "due_date": True,
        "status": True,
    }
    assert len(database.list_payables()) == 1
    assert "Goal:" in llm.prompts[0] and "search_invoices" in llm.prompts[0]  # the model was shown the goal and the tool catalog


def test_transient_failure_is_retried_and_audited():
    run_id = create_run(
        "Find the latest invoice from Acme Office Supplies and add it to AP, then verify it.",
        simulate_failure=True,
    )
    run_agent(run_id, HAPPY_PATH)
    run = database.get_run(run_id)
    assert run["status"] == "completed"
    assert any(event["kind"] == "retry" for event in run["events"])
    assert any(event["kind"] == "success" for event in run["events"])


def test_high_value_invoice_pauses_until_approval_then_completes():
    async def scenario():
        run_id = create_run("Find the latest invoice from Northstar Components and record it in AP.")
        runtime, _llm = make_runtime(APPROVAL_PATH)
        task = asyncio.create_task(runtime._execute(run_id))
        for _ in range(100):
            row = database.get_run_row(run_id)
            if row["status"] == "awaiting_approval":
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("Run did not pause for approval")
        assert database.list_payables() == []
        database.update_run(run_id, approval_decision="approved", approval_note="Test approval")
        await asyncio.wait_for(task, timeout=5)
        run = database.get_run(run_id)
        assert run["status"] == "completed"
        assert any(event["kind"] == "approval" for event in run["events"])
        assert len(database.list_payables()) == 1

    asyncio.run(scenario())


def test_rejected_approval_never_writes_to_ledger():
    async def scenario():
        run_id = create_run("Find the latest invoice from Northstar Components and record it in AP.")
        runtime, _llm = make_runtime(APPROVAL_PATH)
        task = asyncio.create_task(runtime._execute(run_id))
        for _ in range(100):
            row = database.get_run_row(run_id)
            if row["status"] == "awaiting_approval":
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("Run did not pause for approval")
        database.update_run(run_id, approval_decision="rejected", approval_note="Not approved in test")
        await asyncio.wait_for(task, timeout=5)
        run = database.get_run(run_id)
        assert run["status"] == "blocked"
        assert database.list_payables() == []

    asyncio.run(scenario())


def test_duplicate_invoice_is_idempotent():
    goal = "Find the latest invoice from Acme Office Supplies and create a verified AP record."
    run_agent(create_run(goal), HAPPY_PATH)
    second = create_run(goal)
    run_agent(second, HAPPY_PATH)
    run = database.get_run(second)
    assert run["status"] == "completed"
    # End state: the ledger still holds exactly one record, and the tool reported it prevented a second write.
    assert run["state"]["payable_result"]["duplicate_prevented"] is True
    assert len(database.list_payables()) == 1


def test_ambiguous_request_asks_for_input_instead_of_guessing():
    run_id = create_run("Process the newest invoice and add it to accounts payable.")
    run_agent(run_id, STOP_AMBIGUOUS)
    run = database.get_run(run_id)
    assert run["status"] == "needs_input"
    assert run["state"]["search_result"]["found"] is False  # asserted on the real tool output, not on model prose
    assert run["state"]["search_result"]["ambiguous"] is True
    assert "payable_result" not in run["state"]
    assert database.list_payables() == []


def test_unsupported_task_does_not_call_tools_or_write():
    run_id = create_run("Open my laptop and send a message to the whole company.")
    # The LLM loop evaluates the task and decides it cannot be fulfilled safely with available tools
    llm = run_agent(run_id, [finish("needs_input", "Task unsupported with available AP/file tools.")])
    run = database.get_run(run_id)
    assert run["status"] == "needs_input"
    assert len(llm.prompts) == 1
    assert database.list_payables() == []


def test_generic_vendor_word_does_not_select_a_supplier():
    run_id = create_run("Find the latest supplies invoice and add it to accounts payable.")
    run_agent(run_id, STOP_AMBIGUOUS)
    run = database.get_run(run_id)
    assert run["status"] == "needs_input"
    assert run["state"]["search_result"]["found"] is False
    assert database.list_payables() == []


# ----------------------------------------------------------------------------- ReAct-specific behavior
def test_tool_error_is_fed_back_and_the_model_recovers():
    run_id = create_run("Find the latest invoice from Acme Office Supplies and add it to AP, then verify it.")
    run_agent(run_id, [tool("extract_invoice", "jumping ahead")] + HAPPY_PATH)
    run = database.get_run(run_id)
    first = run["state"]["history"][0]
    assert first["tool"] == "extract_invoice" and "No invoice has been selected" in first["error"]
    assert run["status"] == "completed"
    assert len(database.list_payables()) == 1


def test_model_cannot_complete_without_a_passing_verification():
    run_id = create_run("Find the latest invoice from Acme Office Supplies and add it to AP, then verify it.")
    run_agent(run_id, [finish("completed", "all done!"), tool("search_invoices"), finish("needs_input", "stopping")])
    run = database.get_run(run_id)
    assert "no passing verification" in run["state"]["history"][0]["error"]
    assert run["status"] == "needs_input"
    assert database.list_payables() == []


# ----------------------------------------------------------------------------- unchanged infrastructure tests
def test_atomic_write_boundary_handles_concurrent_duplicate_requests():
    from concurrent.futures import ThreadPoolExecutor

    invoice = {
        "invoice_number": "CONCURRENCY-001",
        "vendor": "Acme Office Supplies",
        "amount_inr": 42.0,
        "due_date": "2026-12-01",
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda idx: database.create_payable_record(f"run-{idx}", invoice), range(8)))
    assert sum(1 for _record, created in results if created) == 1
    assert len(database.list_payables()) == 1
    assert len({record["id"] for record, _created in results}) == 1


def test_startup_recovery_requeues_interrupted_approval_run():
    run_id = create_run("Find the latest invoice from Northstar Components and record it in AP.")
    database.update_run(
        run_id,
        status="awaiting_approval",
        state_json={"search_result": {"found": True}},
        pending_approval_json={"invoice_number": "INV-2026-105", "amount_inr": 128400},
    )
    recovered = database.recover_interrupted_runs()
    assert run_id in recovered
    assert database.get_run_row(run_id)["status"] == "queued"
