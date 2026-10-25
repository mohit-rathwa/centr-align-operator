from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import INVOICE_DIR

_DATE_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%d/%m/%Y")
_INVOICE_ID = re.compile(r"\bINV-[\d-]+\b", re.IGNORECASE)
_AMOUNT = re.compile(r"(?:INR|Rs\.?|₹)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)
_FIELD = re.compile(r"^(Vendor|Invoice(?:\s+No\.?)?|Invoice Date|Issue(?:d)?(?:\s+Date)?|Payment Due|Due(?:\s+Date)?|Amount(?:\s+Due)?)\s*[:\-]\s*(.+)$", re.IGNORECASE)


def _parse_date(value: str) -> str | None:
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_amount(value: str) -> float | None:
    match = _AMOUNT.search(value) or re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", value)
    if not match:
        return None
    try:
        return round(float(match.group(1).replace(",", "")), 2)
    except ValueError:
        return None


def parse_text_invoice(path: Path) -> dict[str, Any] | None:
    """Deterministic parser for sandbox text invoices. Not a general OCR/PDF claim."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        match = _FIELD.match(line.strip())
        if match:
            fields[match.group(1).casefold()] = match.group(2).strip()

    invoice_number = fields.get("invoice no") or fields.get("invoice") or (_INVOICE_ID.search(raw).group(0).upper() if _INVOICE_ID.search(raw) else None)
    vendor = fields.get("vendor")
    issued = None
    for key in ("invoice date", "issued date", "issued", "issue date"):
        if key in fields:
            issued = _parse_date(fields[key])
            if issued:
                break
    due = None
    for key in ("payment due", "due date", "due"):
        if key in fields:
            due = _parse_date(fields[key])
            if due:
                break
    amount = None
    for key in ("amount due", "amount"):
        if key in fields:
            amount = _parse_amount(fields[key])
            if amount is not None:
                break
    if amount is None:
        amount = _parse_amount(raw)
    if not invoice_number or not vendor or not issued or not due or amount is None:
        return None
    return {
        "invoice_number": invoice_number,
        "vendor": vendor,
        "issued_at": issued,
        "due_date": due,
        "amount_inr": amount,
        "currency": "INR",
        "description": next((line.split(":", 1)[1].strip() for line in raw.splitlines() if line.lower().startswith("description:")), ""),
        "source_file": path.name,
        "source_format": "text",
    }


def list_source_invoices() -> list[dict[str, Any]]:
    invoices: list[dict[str, Any]] = []
    if not INVOICE_DIR.exists():
        return invoices
    for path in sorted(INVOICE_DIR.iterdir()):
        if not path.is_file():
            continue
        data: dict[str, Any] | None = None
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["source_format"] = "json"
                data.setdefault("source_file", path.name)
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        elif path.suffix.lower() == ".txt":
            data = parse_text_invoice(path)
        if not data:
            continue
        data["_path"] = path.name
        invoices.append(data)
    return invoices


def public_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in invoice.items() if not k.startswith("_")}
