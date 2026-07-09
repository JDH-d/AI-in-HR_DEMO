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

DOCUMENTS_DIR = _resolve_path(os.getenv("DOCUMENTS_DIR", "documents"))
INDEX_PATH = _resolve_path(os.getenv("INDEX_PATH", "data/index.json"))
LOG_PATH = _resolve_path(os.getenv("LOG_PATH", "data/chat_logs.jsonl"))
WORKFLOW_DB = _resolve_path(os.getenv("WORKFLOW_DB", "data/workflow.db"))
SYSTEM_PROMPT_PATH = _resolve_path(os.getenv("SYSTEM_PROMPT_PATH", "data/system_prompt.txt"))

ADMIN_TOKEN = (os.getenv("ADMIN_TOKEN") or os.getenv("ADMIN_PASSWORD") or "").strip()
LOG_USER_TEXT_MODE = (os.getenv("LOG_USER_TEXT_MODE", "masked") or "masked").strip().lower()

SUPPORTED_DOC_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
