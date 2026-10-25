from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env", override=False)
BACKEND_DIR = ROOT_DIR / "backend"
APP_DIR = BACKEND_DIR / "app"
STATIC_DIR = APP_DIR / "static"
INVOICE_DIR = BACKEND_DIR / "data" / "invoices"
COMPANY_CONTEXT_PATH = BACKEND_DIR / "data" / "company_context.json"

_db = os.getenv("DATABASE_PATH", "backend/data/agent.db")
DB_PATH = Path(_db)
if not DB_PATH.is_absolute():
    DB_PATH = ROOT_DIR / DB_PATH

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
APP_NAME = "CentrAlign Operator"
MAX_STEPS = 8
MAX_TOOL_ATTEMPTS = 3
APPROVAL_THRESHOLD_INR = 50_000
MAX_APPROVED_INVOICE_INR = 1_000_000
