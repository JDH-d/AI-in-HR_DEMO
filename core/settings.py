from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from core.configuration import (
    OPTIONAL_DEFAULTS,
    PUBLIC_DEFAULTS,
    STORAGE_FILES,
    validate_auth_values,
)

BASE_DIR = Path(__file__).resolve().parent.parent
if os.getenv("PYTHON_DOTENV_DISABLED") != "1":
    load_dotenv(BASE_DIR / ".env", interpolate=False)
    load_dotenv(BASE_DIR / ".env.integrations", interpolate=False)


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


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "").strip() or PUBLIC_DEFAULTS["OPENAI_MODEL"]
OPENAI_TIMEOUT_SECONDS = _get_float(
    "OPENAI_TIMEOUT_SECONDS", float(OPTIONAL_DEFAULTS["OPENAI_TIMEOUT_SECONDS"]), 1.0, 300.0
)
OPENAI_MAX_RETRIES = _get_int(
    "OPENAI_MAX_RETRIES", int(OPTIONAL_DEFAULTS["OPENAI_MAX_RETRIES"]), 0, 5
)
OPENAI_MAX_OUTPUT_TOKENS = _get_int(
    "OPENAI_MAX_OUTPUT_TOKENS", int(OPTIONAL_DEFAULTS["OPENAI_MAX_OUTPUT_TOKENS"]), 64, 32768
)
EMBEDDING_BATCH_SIZE = 64
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or OPTIONAL_DEFAULTS["EMBEDDING_MODEL"]
DEMO_AUTH_SECRET = os.getenv("DEMO_AUTH_SECRET", "").strip()
DEMO_LOGIN_PASSWORD = os.getenv("DEMO_LOGIN_PASSWORD", "").strip()
DEMO_TOKEN_TTL_SECONDS = _get_int(
    "DEMO_TOKEN_TTL_SECONDS", int(OPTIONAL_DEFAULTS["DEMO_TOKEN_TTL_SECONDS"]), 300, 86400
)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        OPTIONAL_DEFAULTS["CORS_ORIGINS"],
    ).split(",")
    if origin.strip()
]

DOCUMENTS_DIR = _resolve_path(os.getenv("DOCUMENTS_DIR") or OPTIONAL_DEFAULTS["DOCUMENTS_DIR"])
DATA_DIR = _resolve_path(os.getenv("DATA_DIR") or PUBLIC_DEFAULTS["DATA_DIR"])


def _storage_path(name: str) -> Path:
    override = os.getenv(name)
    return _resolve_path(override) if override else DATA_DIR / STORAGE_FILES[name]


INDEX_PATH = _storage_path("INDEX_PATH")
INDEX_STATUS_PATH = _storage_path("INDEX_STATUS_PATH")
LOG_PATH = _storage_path("LOG_PATH")
WORKFLOW_DB = _storage_path("WORKFLOW_DB")
SYSTEM_PROMPT_PATH = _storage_path("SYSTEM_PROMPT_PATH")
AI_SETTINGS_PATH = _storage_path("AI_SETTINGS_PATH")

# Optional bot setup belongs in .env.integrations; .env still has five variables.
# Legacy channel webhooks are intentionally not used for personal delivery.
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "").strip()
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "").strip()
SLACK_TEAM_ID = os.getenv("SLACK_TEAM_ID", "").strip()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY", "").strip()
DISCORD_APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID", "").strip()
DISCORD_CONNECTION_MODE = os.getenv("DISCORD_CONNECTION_MODE", "gateway").strip().lower()
APP_PUBLIC_URL = os.getenv(
    "APP_PUBLIC_URL", os.getenv("APP_LAUNCH_URL", "http://127.0.0.1:5173")
).strip()

LOG_USER_TEXT_MODE = (
    (os.getenv("LOG_USER_TEXT_MODE") or OPTIONAL_DEFAULTS["LOG_USER_TEXT_MODE"]).strip().lower()
)

SUPPORTED_DOC_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def validate_auth_settings() -> None:
    validate_auth_values(DEMO_AUTH_SECRET, DEMO_LOGIN_PASSWORD)
