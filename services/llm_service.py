from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Optional

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from .openai_client import create_openai_client

logger = logging.getLogger(__name__)


class LLMServiceError(RuntimeError):
    pass


class LLMService:
    def __init__(
        self,
        model: str,
        client_factory: Callable[[], OpenAI] | None = None,
    ) -> None:
        self.model = model
        self.client_factory = client_factory or create_openai_client
        self.client: Optional[OpenAI] = None

    def generate(self, prompt_messages: list[dict]) -> str:
        try:
            response = self._get_client().responses.create(
                model=self.model,
                input=prompt_messages,
                max_output_tokens=512,
                store=False,
            )
            content = (response.output_text or "").strip()
            if not content:
                raise LLMServiceError("OpenAI returned an empty text response")
            return content
        except LLMServiceError:
            raise
        except APITimeoutError as exc:
            logger.warning("OpenAI response timed out model=%s", self.model)
            raise LLMServiceError("OpenAI response timed out") from exc
        except RateLimitError as exc:
            logger.warning("OpenAI rate limit reached model=%s", self.model)
            raise LLMServiceError("OpenAI rate limit reached") from exc
        except APIStatusError as exc:
            logger.warning(
                "OpenAI API status error model=%s status=%s request_id=%s",
                self.model,
                exc.status_code,
                getattr(exc, "request_id", None),
            )
            raise LLMServiceError("OpenAI API returned an error") from exc
        except APIConnectionError as exc:
            logger.warning("OpenAI connection failed model=%s", self.model)
            raise LLMServiceError("OpenAI connection failed") from exc
        except (AttributeError, IndexError, KeyError, OpenAIError, TypeError, ValueError) as exc:
            logger.warning(
                "OpenAI response handling failed model=%s error=%s",
                self.model,
                type(exc).__name__,
            )
            raise LLMServiceError("OpenAI response handling failed") from exc

    def _get_client(self) -> OpenAI:
        if self.client is not None:
            return self.client
        try:
            self.client = self.client_factory()
        except (OpenAIError, OSError, TypeError, ValueError) as exc:
            logger.warning("OpenAI client initialization failed error=%s", type(exc).__name__)
            raise LLMServiceError("OpenAI client is not configured") from exc
        return self.client
