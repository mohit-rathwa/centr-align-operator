from __future__ import annotations

from datetime import date
from typing import Any

from . import database
from .config import MAX_APPROVED_INVOICE_INR
from .connectors import ToolContext, ToolSpec, registry
from .documents import list_source_invoices, public_invoice

__all__ = [
    "ToolError",
    "TransientToolError",
    "TOOL_DESCRIPTIONS",
    "execute_tool",
    "list_source_invoices",
    "public_invoice",
    "update_customer_phone",
]


class ToolError(RuntimeError):
    """Non-retryable tool failure, such as invalid state or a policy violation."""


class TransientToolError(RuntimeError):
    """Retryable transport/tool failure."""


def _search_invoices(state: dict[str, Any]) -> dict[str, Any]:
    query = str(state.get("plan", {}).get("vendor_query") or "").strip().casefold()
    invoices = list_source_invoices()
    if query:
        canonical = (database.resolve_vendor(query) or query).casefold()
        query_words = set(canonical.replace("-", " ").split())
        matches = []
        for invoice in invoices:
            vendor = str(invoice.get("vendor", "")).casefold()
            vendor_words = set(vendor.replace("-", " ").split())
            if canonical in vendor or vendor in canonical or (query_words and query_words.issubset(vendor_words)):
                matches.append(invoice)
        invoices = matches
    # No vendor match is a meaningful observation; never silently pick a different supplier.
    if not invoices:
        return {"found": False, "candidates": [], "query": query or None, "reason": "No invoice matched the requested vendor."}

    invoices.sort(key=lambda x: (str(x.get("issued_at", "")), str(x.get("invoice_number", ""))), reverse=True)
    if not query and len({x.get("vendor") for x in invoices}) > 1:
        return {
            "found": False,
            "ambiguous": True,
            "query": None,
            "candidates": [
                {"invoice_number": x.get("invoice_number"), "vendor": x.get("vendor"), "issued_at": x.get("issued_at")}
                for x in invoices[:5]
            ],
            "reason": "The request does not name a vendor and several suppliers have invoices. Please choose one.",
        }
    selected = invoices[0]
    return {
        "found": True,
        "selected_invoice_id": selected.get("invoice_number"),
        "candidate_count": len(invoices),
        "selected": {
            "invoice_number": selected.get("invoice_number"),
            "vendor": selected.get("vendor"),
            "issued_at": selected.get("issued_at"),
            "source_file": selected.get("source_file", selected.get("_path")),
            "source_format": selected.get("source_format", "json"),
        },
        "candidates": [
            {"invoice_number": x.get("invoice_number"), "vendor": x.get("vendor"), "issued_at": x.get("issued_at")}
            for x in invoices[:5]
        ],
    }


def _load_selected_invoice(state: dict[str, Any]) -> dict[str, Any]:
    search = state.get("search_result") or {}
    selected_id = search.get("selected_invoice_id")
    if not selected_id:
        raise ToolError("No invoice has been selected. Search must succeed before this tool can run.")
    for invoice in list_source_invoices():
        if invoice.get("invoice_number") == selected_id:
            return invoice
    raise ToolError("The selected source invoice disappeared from the workspace.")


def _extract_invoice(state: dict[str, Any]) -> dict[str, Any]:
    invoice = _load_selected_invoice(state)
    required = ["invoice_number", "vendor", "issued_at", "due_date", "amount_inr"]
    missing = [key for key in required if invoice.get(key) in (None, "")]
    if missing:
        return {"ok": False, "missing_fields": missing, "source_file": invoice.get("source_file")}
    try:
        issue_date = date.fromisoformat(str(invoice["issued_at"]))
        due_date = date.fromisoformat(str(invoice["due_date"]))
        amount = float(invoice["amount_inr"])
    except (TypeError, ValueError) as exc:
        raise ToolError(f"Invoice contains a malformed date or amount: {exc}") from exc
    if amount < 0:
        raise ToolError("Invoice amount cannot be negative.")
    extracted = {
        "invoice_number": str(invoice["invoice_number"]).strip(),
        "vendor": str(invoice["vendor"]).strip(),
        "issued_at": issue_date.isoformat(),
        "due_date": due_date.isoformat(),
        "amount_inr": round(amount, 2),
        "currency": str(invoice.get("currency", "INR")),
        "description": str(invoice.get("description", "")),
        "source_file": str(invoice.get("source_file", invoice.get("_path", ""))),
        "source_format": str(invoice.get("source_format", "json")),
    }
    return {"ok": True, "invoice": extracted, "fields_extracted": len(required)}


def _validate_invoice(state: dict[str, Any]) -> dict[str, Any]:
    extraction = state.get("extract_result") or {}
    if not extraction.get("ok") or not extraction.get("invoice"):
        return {"valid": False, "issues": ["Source invoice could not be extracted; refusing to write."], "duplicate": False}
    invoice = extraction["invoice"]
    policy = database.get_policy().get("accounts_payable", {})
    allowed_vendors = {str(x).casefold() for x in policy.get("allowed_vendors", [])}
    issues: list[str] = []
    if invoice["vendor"].casefold() not in allowed_vendors:
        issues.append("Vendor is not present in the company's approved vendor memory.")
    amount = float(invoice["amount_inr"])
    if amount <= 0:
        issues.append("Invoice amount must be greater than zero.")
    max_amount = float(policy.get("maximum_single_invoice_inr", MAX_APPROVED_INVOICE_INR))
    if amount > max_amount:
        issues.append(f"Invoice exceeds the company hard limit of ₹{max_amount:,.0f}.")
    if invoice["due_date"] < invoice["issued_at"]:
        issues.append("Due date is earlier than invoice issue date.")
    duplicate = database.get_payable_for_invoice(invoice["invoice_number"])
    return {
        "valid": not issues,
        "issues": issues,
        "duplicate": bool(duplicate),
        "existing_payable": duplicate,
        "approval_required": amount >= float(policy.get("approval_threshold_inr", 50_000)),
        "approval_threshold_inr": float(policy.get("approval_threshold_inr", 50_000)),
        "checks": ["required fields", "date ordering", "positive amount", "maximum amount", "vendor allowlist", "duplicate lookup"],
    }


def _create_payable(run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    validation = state.get("validation_result") or {}
    extraction = state.get("extract_result") or {}
    if not validation.get("valid") or not extraction.get("invoice"):
        raise ToolError("Refusing ledger write: invoice has not passed validation.")
    invoice = extraction["invoice"]
    existing = database.get_payable_for_invoice(invoice["invoice_number"])
    if existing:
        return {"created": False, "duplicate_prevented": True, "payable": existing}
    if validation.get("approval_required") and not state.get("approval_granted"):
        return {
            "requires_approval": True,
            "approval": {
                "vendor": invoice["vendor"],
                "invoice_number": invoice["invoice_number"],
                "amount_inr": invoice["amount_inr"],
                "due_date": invoice["due_date"],
                "reason": f"Amount meets or exceeds the ₹{validation['approval_threshold_inr']:,.0f} company approval threshold.",
            },
        }
    payable, created = database.create_payable_record(run_id, invoice)
    return {"created": created, "duplicate_prevented": not created, "payable": payable}


def _verify_payable(state: dict[str, Any]) -> dict[str, Any]:
    extraction = state.get("extract_result") or {}
    invoice = extraction.get("invoice") or {}
    if not invoice:
        raise ToolError("Cannot verify without an extracted source invoice.")
    payable = database.get_payable_for_invoice(invoice.get("invoice_number", ""))
    if not payable:
        return {"verified": False, "mismatches": ["No payable record was found after the write attempt."], "evidence": None}
    checks = {
        "source_invoice_id": payable["source_invoice_id"] == invoice["invoice_number"],
        "vendor": payable["vendor"] == invoice["vendor"],
        "amount_inr": abs(float(payable["amount_inr"]) - float(invoice["amount_inr"])) < 0.01,
        "due_date": payable["due_date"] == invoice["due_date"],
        "status": payable["status"] == "pending",
    }
    mismatches = [key for key, passed in checks.items() if not passed]
    return {
        "verified": not mismatches,
        "checks": checks,
        "mismatches": mismatches,
        "evidence": payable,
        "verification_method": "read-after-write comparison against the persisted sandbox ledger",
    }


def _read_file(state: dict[str, Any]) -> dict[str, Any]:
    from pathlib import Path
    from .config import ROOT_DIR
    target = state.get("target_filepath") or "contact.txt"
    p = Path(target)
    if not p.is_absolute():
        p = ROOT_DIR / p
    if not p.exists():
        raise ToolError(f"File not found: {target}")
    return {"ok": True, "filepath": str(target), "content": p.read_text(encoding="utf-8").strip()}


def update_customer_phone(vendor: str = "Acme Office Supplies", phone: str = "+1-555-0142") -> dict[str, Any]:
    return {
        "ok": True,
        "vendor": str(vendor or "Acme Office Supplies").strip(),
        "new_phone": str(phone or "+1-555-0142").strip(),
        "message": "Phone updated in mock CRM",
        "verified": True,
    }


def _update_customer_phone_handler(ctx: ToolContext) -> dict[str, Any]:
    state = ctx.state
    vendor = "Acme Office Supplies"
    phone = "+1-555-0142"

    file_content = state.get("file_content", {}).get("content", "")
    if file_content and "Phone:" in file_content:
        parts = file_content.split("Phone:")
        v = parts[0].replace("—", "").replace("-", "").strip()
        p = parts[1].strip()
        if v:
            vendor = v
        if p:
            phone = p

    return update_customer_phone(vendor=vendor, phone=phone)


def _register_tools() -> None:
    if registry.names():
        return
    registry.add(ToolSpec("search_invoices", "Search the read-only sandbox invoice workspace.", "search_result", "files", lambda ctx: _search_invoices(ctx.state)))
    registry.add(ToolSpec("extract_invoice", "Extract typed fields from a JSON or text source invoice.", "extract_result", "files", lambda ctx: _extract_invoice(ctx.state)))
    registry.add(ToolSpec("validate_invoice", "Validate required fields, supplier allowlist, amount limits, and duplicate status.", "validation_result", "policy", lambda ctx: _validate_invoice(ctx.state)))
    registry.add(ToolSpec("create_payable", "Write one payable into the sandbox ledger subject to approval policy.", "payable_result", "ledger", lambda ctx: _create_payable(ctx.run_id, ctx.state)))
    registry.add(ToolSpec("verify_payable", "Read the payable back and compare values against the source invoice.", "verification_result", "ledger", lambda ctx: _verify_payable(ctx.state)))
    registry.add(ToolSpec("read_file", "Read text content of a file given by target_filepath.", "file_content", "files", lambda ctx: _read_file(ctx.state)))
    registry.add(ToolSpec("update_customer_phone", "Update customer phone number in the mock CRM given vendor and phone.", "crm_result", "crm", _update_customer_phone_handler))


_register_tools()
TOOL_DESCRIPTIONS = registry.descriptions()


async def execute_tool(
    name: str,
    *,
    run_id: str,
    goal: str,
    state: dict[str, Any],
    simulate_failure: bool = False,
) -> dict[str, Any]:
    """Execute one allowlisted action. No arbitrary code, shell, or URL tool exists."""
    spec = registry.get(name)
    if spec is None:
        raise ToolError(f"Tool is not allowlisted: {name}")

    if simulate_failure and not state.get("demo_transient_failure_used"):
        state["demo_transient_failure_used"] = True
        raise TransientToolError("Demo fault injection: temporary file-service timeout.")

    return spec.handler(ToolContext(run_id=run_id, goal=goal, state=state, simulate_failure=simulate_failure))
