from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .config import DB_PATH, COMPANY_CONTEXT_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def init_db() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                plan_json TEXT,
                state_json TEXT NOT NULL DEFAULT '{}',
                summary TEXT,
                error TEXT,
                pending_approval_json TEXT,
                approval_decision TEXT,
                approval_note TEXT,
                simulate_failure INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                attempt INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id, id);
            CREATE TABLE IF NOT EXISTS payables (
                id TEXT PRIMARY KEY,
                source_invoice_id TEXT NOT NULL UNIQUE,
                invoice_number TEXT NOT NULL,
                vendor TEXT NOT NULL,
                amount_inr REAL NOT NULL,
                due_date TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by_run TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS company_memory (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outcome_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                run_id TEXT,
                kind TEXT NOT NULL,
                vendor TEXT,
                invoice_number TEXT,
                detail TEXT NOT NULL DEFAULT ''
            );
            """
        )
        context = json.loads(COMPANY_CONTEXT_PATH.read_text(encoding="utf-8"))
        exists = con.execute("SELECT 1 FROM company_memory WHERE key = 'accounts_payable_policy'").fetchone()
        if not exists:
            con.execute(
                "INSERT INTO company_memory(key, value_json, updated_at) VALUES (?, ?, ?)",
                ("accounts_payable_policy", json.dumps(context, ensure_ascii=False), utc_now()),
            )
        alias_row = con.execute("SELECT 1 FROM company_memory WHERE key = 'vendor_aliases'").fetchone()
        if not alias_row:
            con.execute(
                "INSERT INTO company_memory(key, value_json, updated_at) VALUES (?, ?, ?)",
                ("vendor_aliases", json.dumps(context.get("vendor_aliases", {}), ensure_ascii=False), utc_now()),
            )
        con.commit()


def create_run(run_id: str, goal: str, simulate_failure: bool) -> None:
    now = utc_now()
    with connect() as con:
        con.execute(
            """INSERT INTO runs(id, goal, status, created_at, updated_at, state_json, simulate_failure)
               VALUES (?, ?, 'queued', ?, ?, '{}', ?)""",
            (run_id, goal, now, now, int(simulate_failure)),
        )
        con.commit()


def get_run_row(run_id: str) -> sqlite3.Row | None:
    with connect() as con:
        return con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()


def update_run(run_id: str, **fields: Any) -> None:
    allowed = {
        "status", "plan_json", "state_json", "summary", "error",
        "pending_approval_json", "approval_decision", "approval_note"
    }
    if not fields or any(key not in allowed for key in fields):
        raise ValueError("Unsupported run field update")
    values = dict(fields)
    if "plan_json" in values and not isinstance(values["plan_json"], str):
        values["plan_json"] = json.dumps(values["plan_json"], ensure_ascii=False)
    if "state_json" in values and not isinstance(values["state_json"], str):
        values["state_json"] = json.dumps(values["state_json"], ensure_ascii=False)
    if "pending_approval_json" in values and values["pending_approval_json"] is not None and not isinstance(values["pending_approval_json"], str):
        values["pending_approval_json"] = json.dumps(values["pending_approval_json"], ensure_ascii=False)
    values["updated_at"] = utc_now()
    clause = ", ".join(f"{key} = ?" for key in values)
    with connect() as con:
        con.execute(f"UPDATE runs SET {clause} WHERE id = ?", (*values.values(), run_id))
        con.commit()


def add_event(run_id: str, kind: str, title: str, detail: str = "", attempt: int | None = None) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO run_events(run_id, created_at, kind, title, detail, attempt) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, utc_now(), kind, title, detail, attempt),
        )
        con.commit()


def get_run(run_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        events = con.execute(
            "SELECT id, created_at, kind, title, detail, attempt FROM run_events WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
    data = dict(row)
    data["plan"] = json.loads(data.pop("plan_json")) if data.get("plan_json") else None
    data["state"] = json.loads(data.pop("state_json") or "{}")
    data["pending_approval"] = json.loads(data.pop("pending_approval_json")) if data.get("pending_approval_json") else None
    data.pop("approval_decision", None)
    data.pop("approval_note", None)
    data.pop("simulate_failure", None)
    data["events"] = [dict(event) for event in events]
    return data


def list_runs(limit: int = 12) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [item for row in rows if (item := get_run(row["id"])) is not None]


def get_policy() -> dict[str, Any]:
    with connect() as con:
        row = con.execute("SELECT value_json FROM company_memory WHERE key = 'accounts_payable_policy'").fetchone()
    if not row:
        return json.loads(COMPANY_CONTEXT_PATH.read_text(encoding="utf-8"))
    return json.loads(row["value_json"])


def get_aliases() -> dict[str, str]:
    with connect() as con:
        row = con.execute("SELECT value_json FROM company_memory WHERE key = 'vendor_aliases'").fetchone()
    if not row:
        return {}
    data = json.loads(row["value_json"] or "{}")
    return {str(key).casefold(): str(value) for key, value in data.items() if key and value}


def allowed_vendors() -> list[str]:
    return [str(item) for item in get_policy().get("accounts_payable", {}).get("allowed_vendors", [])]


def resolve_vendor(text: str | None) -> str | None:
    """Map free text onto an allowlisted vendor using names and persisted aliases."""
    if not text:
        return None
    lowered = text.strip().casefold()
    if not lowered:
        return None
    vendors = allowed_vendors()
    for vendor in vendors:
        if vendor.casefold() == lowered or vendor.casefold() in lowered:
            return vendor
    aliases = get_aliases()
    # Prefer longer aliases so "blue oak" wins over "blue".
    for alias, vendor in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if not alias:
            continue
        if alias == lowered or re.search(rf"\b{re.escape(alias)}\b", lowered):
            canonical = next((item for item in vendors if item.casefold() == vendor.casefold()), None)
            if canonical:
                return canonical
    words = set(re.findall(r"[a-z0-9]+", lowered))
    for vendor in vendors:
        vendor_words = re.findall(r"[a-z0-9]+", vendor.casefold())
        if vendor_words and vendor_words[0] in words:
            return vendor
    return None


def learn_vendor_alias(alias: str, vendor: str) -> bool:
    canonical = next((item for item in allowed_vendors() if item.casefold() == vendor.casefold()), None)
    cleaned = " ".join(alias.strip().casefold().split())
    if (
        not canonical
        or not cleaned
        or cleaned == canonical.casefold()
        or len(cleaned) > 24
        or len(cleaned.split()) > 3
    ):
        return False
    aliases = get_aliases()
    if aliases.get(cleaned) == canonical:
        return False
    aliases[cleaned] = canonical
    with connect() as con:
        con.execute(
            "INSERT INTO company_memory(key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            ("vendor_aliases", json.dumps(aliases, ensure_ascii=False), utc_now()),
        )
        con.commit()
    return True


def record_outcome(run_id: str | None, kind: str, detail: str, vendor: str | None = None, invoice_number: str | None = None) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO outcome_memory(created_at, run_id, kind, vendor, invoice_number, detail)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (utc_now(), run_id, kind, vendor, invoice_number, detail),
        )
        con.commit()


def list_outcomes(limit: int = 12) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT created_at, run_id, kind, vendor, invoice_number, detail FROM outcome_memory ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_memory() -> dict[str, Any]:
    policy = get_policy()
    policy["vendor_aliases"] = get_aliases()
    policy["recent_outcomes"] = list_outcomes()
    return policy


def list_payables() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT * FROM payables ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def get_payable_for_invoice(invoice_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM payables WHERE source_invoice_id = ?", (invoice_id,)).fetchone()
    return dict(row) if row else None


def create_payable_record(run_id: str, invoice: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Atomically create one payable per source invoice, even under concurrent runs."""
    with connect() as con:
        # Serialize competing writers before checking the unique business key.
        con.execute("BEGIN IMMEDIATE")
        existing_row = con.execute(
            "SELECT * FROM payables WHERE source_invoice_id = ?",
            (invoice["invoice_number"],),
        ).fetchone()
        if existing_row:
            existing = dict(existing_row)
            con.commit()
            return existing, False

        payable_id = f"AP-{invoice['invoice_number'].replace('-', '')}"
        con.execute(
            """INSERT INTO payables(id, source_invoice_id, invoice_number, vendor, amount_inr, due_date, status, created_at, created_by_run)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (payable_id, invoice["invoice_number"], invoice["invoice_number"], invoice["vendor"],
             float(invoice["amount_inr"]), invoice["due_date"], utc_now(), run_id),
        )
        record_row = con.execute(
            "SELECT * FROM payables WHERE source_invoice_id = ?",
            (invoice["invoice_number"],),
        ).fetchone()
        if not record_row:
            con.rollback()
            raise RuntimeError("Payable write returned without a readable record")
        record = dict(record_row)
        con.commit()
        return record, True


def recover_interrupted_runs() -> list[str]:
    """Requeue active jobs after a process restart; the runner is idempotent at the write boundary."""
    with connect() as con:
        rows = con.execute("SELECT id, status FROM runs WHERE status IN ('queued', 'running', 'awaiting_approval')").fetchall()
        ids = [row["id"] for row in rows]
        now = utc_now()
        for row in rows:
            con.execute("UPDATE runs SET status = 'queued', updated_at = ? WHERE id = ?", (now, row["id"]))
        con.commit()
    return ids
