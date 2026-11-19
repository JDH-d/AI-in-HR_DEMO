"""Shared configuration defaults, without environment or filesystem side effects."""

PUBLIC_DEFAULTS = {
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "gpt-5-nano-2025-08-07",
    "DEMO_LOGIN_PASSWORD": "",
    "DEMO_AUTH_SECRET": "",
    "DATA_DIR": "data",
}

OPTIONAL_DEFAULTS = {
    "OPENAI_TIMEOUT_SECONDS": "30",
    "OPENAI_MAX_RETRIES": "2",
    "OPENAI_MAX_OUTPUT_TOKENS": "512",
    "EMBEDDING_MODEL": "text-embedding-3-small",
    "DEMO_TOKEN_TTL_SECONDS": "28800",
    "CORS_ORIGINS": (
        "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:5173,http://localhost:5173"
    ),
    "DOCUMENTS_DIR": "documents",
    "LOG_USER_TEXT_MODE": "masked",
}

STORAGE_FILES = {
    "INDEX_PATH": "index.json",
    "INDEX_STATUS_PATH": "index_status.json",
    "LOG_PATH": "chat_logs.jsonl",
    "WORKFLOW_DB": "workflow.db",
    "SYSTEM_PROMPT_PATH": "system_prompt.txt",
    "AI_SETTINGS_PATH": "ai_settings.json",
}


def validate_auth_values(secret: str, password: str) -> None:
    if len(secret) < 32 or secret in {
        "local-demo-secret-change-before-sharing",
        "replace-with-a-long-random-secret",
    }:
        raise ValueError(
            "Set DEMO_AUTH_SECRET to a unique random value of at least 32 characters in .env."
        )
    if not password or password in {"demo-password", "replace-with-a-unique-password"}:
        raise ValueError("Set DEMO_LOGIN_PASSWORD to a unique password in .env.")
