from __future__ import annotations

from openai import OpenAI

from core import settings


def create_openai_client() -> OpenAI:
    return OpenAI(
        timeout=settings.OPENAI_TIMEOUT_SECONDS,
        max_retries=settings.OPENAI_MAX_RETRIES,
    )
