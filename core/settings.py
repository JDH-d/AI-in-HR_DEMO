from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _get_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _get_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07").strip()
OPENAI_TIMEOUT_SECONDS = _get_float("OPENAI_TIMEOUT_SECONDS", 30.0, 1.0, 300.0)
OPENAI_MAX_RETRIES = _get_int("OPENAI_MAX_RETRIES", 2, 0, 5)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
DEMO_AUTH_SECRET = os.getenv(
    "DEMO_AUTH_SECRET",
    "local-demo-secret-change-before-sharing",
).strip()
DEMO_LOGIN_PASSWORD = os.getenv("DEMO_LOGIN_PASSWORD", "demo-password").strip()
DEMO_TOKEN_TTL_SECONDS = _get_int("DEMO_TOKEN_TTL_SECONDS", 28800, 300, 86400)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

DOCUMENTS_DIR = _resolve_path(os.getenv("DOCUMENTS_DIR", "documents"))
INDEX_PATH = _resolve_path(os.getenv("INDEX_PATH", "data/index.json"))
INDEX_STATUS_PATH = _resolve_path(os.getenv("INDEX_STATUS_PATH", "data/index_status.json"))
LOG_PATH = _resolve_path(os.getenv("LOG_PATH", "data/chat_logs.jsonl"))
WORKFLOW_DB = _resolve_path(os.getenv("WORKFLOW_DB", "data/workflow.db"))
SYSTEM_PROMPT_PATH = _resolve_path(os.getenv("SYSTEM_PROMPT_PATH", "data/system_prompt.txt"))
AI_SETTINGS_PATH = _resolve_path(os.getenv("AI_SETTINGS_PATH", "data/ai_settings.json"))

LOG_USER_TEXT_MODE = (os.getenv("LOG_USER_TEXT_MODE", "masked") or "masked").strip().lower()

SUPPORTED_DOC_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
