from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig")

BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _get_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _get_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()
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
CONVERSATION_DB = _resolve_path(os.getenv("CONVERSATION_DB", "data/conversations.db"))
AI_SETTINGS_PATH = _resolve_path(os.getenv("AI_SETTINGS_PATH", "data/ai_settings.json"))
LEGACY_SYSTEM_PROMPT_PATH = BASE_DIR / "data" / "system_prompt.txt"

LOG_USER_TEXT_MODE = (os.getenv("LOG_USER_TEXT_MODE", "masked") or "masked").strip().lower()
if LOG_USER_TEXT_MODE not in {"raw", "masked", "off"}:
    raise RuntimeError("LOG_USER_TEXT_MODE must be raw, masked, or off")

SUPPORTED_DOC_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def configuration_warnings() -> list[str]:
    warnings: list[str] = []
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key or api_key == "your_openai_api_key":
        warnings.append("OpenAI is not configured; deterministic fallbacks will be used.")
    if DEMO_AUTH_SECRET == "local-demo-secret-change-before-sharing":
        warnings.append("Demo authentication uses the local default secret.")
    if DEMO_LOGIN_PASSWORD == "demo-password":
        warnings.append("Demo authentication uses the default password.")
    return warnings
