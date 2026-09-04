from __future__ import annotations

import os

from openai import OpenAI, OpenAIError

from core import settings


def create_openai_client() -> OpenAI:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key or api_key == "your_openai_api_key":
        raise OpenAIError("OPENAI_API_KEY is not configured")
    return OpenAI(
        api_key=api_key,
        timeout=settings.OPENAI_TIMEOUT_SECONDS,
        max_retries=settings.OPENAI_MAX_RETRIES,
    )
