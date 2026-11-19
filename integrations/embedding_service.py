import logging
from collections.abc import Callable

from openai import APIStatusError, OpenAI, OpenAIError

from core import settings
from integrations.openai_client import create_openai_client

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    pass


class EmbeddingService:
    def __init__(
        self,
        model: str = settings.EMBEDDING_MODEL,
        client_factory: Callable[[], OpenAI] | None = None,
        batch_size: int = settings.EMBEDDING_BATCH_SIZE,
    ):
        self.model = model
        self.client_factory = client_factory or create_openai_client
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            client = self.client_factory()
            vectors: list[list[float]] = []
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                response = client.embeddings.create(model=self.model, input=batch)
                vectors.extend(
                    item.embedding for item in sorted(response.data, key=lambda item: item.index)
                )
            if len(vectors) != len(texts):
                raise ValueError("Embedding response count did not match input count")
            return vectors
        except APIStatusError as exc:
            logger.warning(
                "OpenAI embedding API error model=%s status=%s code=%s request_id=%s",
                self.model,
                exc.status_code,
                exc.code,
                exc.request_id,
            )
            raise EmbeddingError(f"Embedding generation failed: {type(exc).__name__}") from exc
        except (OpenAIError, OSError, AttributeError, TypeError, ValueError) as exc:
            raise EmbeddingError(f"Embedding generation failed: {type(exc).__name__}") from exc
