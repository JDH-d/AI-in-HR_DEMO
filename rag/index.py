from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

from core import settings
from core.files import atomic_write_json
from services.document_reader import DocumentRecord, load_documents
from services.openai_client import create_openai_client

from .retriever import Retriever
from .text import chunk_document

INDEX_SCHEMA_VERSION = 3
EMBEDDING_BATCH_SIZE = 64
EMBEDDING_RETRY_SECONDS = 300

logger = logging.getLogger(__name__)


class KnowledgeIndex:
    """Owns one knowledge index and its in-process retriever cache."""

    def __init__(
        self,
        documents_dir: Path,
        index_path: Path,
        embedding_model: str,
        *,
        client_factory: Callable[[], OpenAI] | None = None,
        embedding_retry_seconds: int = EMBEDDING_RETRY_SECONDS,
    ) -> None:
        self.documents_dir = documents_dir
        self.index_path = index_path
        self.embedding_model = embedding_model
        self.client_factory = client_factory or create_openai_client
        self.embedding_retry_seconds = embedding_retry_seconds
        self._retriever: Retriever | None = None

    def ensure(self) -> None:
        documents = load_documents(self.documents_dir, strict=True)
        fingerprint = documents_fingerprint(documents)
        if self._is_current_payload(self._read_payload(), fingerprint):
            return

        logger.info(
            "Rebuilding RAG index schema=%s documents=%s",
            INDEX_SCHEMA_VERSION,
            len(documents),
        )
        self.build(documents)

    def get_retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever.load(
                str(self.index_path),
                client_factory=self.client_factory,
                embedding_model=self.embedding_model,
            )
        return self._retriever

    def build(self, documents: list[DocumentRecord] | None = None) -> dict[str, Any]:
        active_documents = (
            documents if documents is not None else load_documents(self.documents_dir, strict=True)
        )
        items = build_index_items(
            active_documents,
            embedding_model=self.embedding_model,
            client_factory=self.client_factory,
        )
        mode = "embedding" if items and _valid_index_items(items, "embedding") else "lexical"
        if mode == "lexical":
            for item in items:
                item.pop("embedding", None)
        payload = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "embedding_model": self.embedding_model,
            "documents_fingerprint": documents_fingerprint(active_documents),
            "mode": mode,
            "embedding_retry_at": (
                None
                if mode == "embedding" or not items
                else time.time() + self.embedding_retry_seconds
            ),
            "items": items,
        }
        atomic_write_json(self.index_path, payload)
        self._retriever = None
        return payload

    def rebuild(self) -> dict[str, Any]:
        return self.build()

    def invalidate(self) -> None:
        """Discard the in-process view after an index file is restored externally."""

        self._retriever = None

    def _read_payload(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return payload if isinstance(payload, dict) else None

    def _is_current_payload(
        self,
        payload: dict[str, Any] | None,
        fingerprint: str,
    ) -> bool:
        if not payload:
            return False
        items = payload.get("items")
        mode = payload.get("mode")
        metadata_is_current = (
            payload.get("schema_version") == INDEX_SCHEMA_VERSION
            and payload.get("embedding_model") == self.embedding_model
            and payload.get("documents_fingerprint") == fingerprint
            and mode in {"embedding", "lexical"}
            and isinstance(items, list)
        )
        if not metadata_is_current:
            return False
        if not _valid_index_items(items, mode):
            return False
        if mode != "lexical" or not items:
            return True
        try:
            retry_at = float(payload.get("embedding_retry_at") or 0)
        except (TypeError, ValueError):
            return False
        return retry_at > time.time()


def _valid_index_items(items: list[object], mode: object) -> bool:
    string_fields = ("source", "document_id", "title", "category", "version", "section", "text")
    embedding_size: int | None = None
    for item in items:
        if not isinstance(item, dict):
            return False
        if any(not isinstance(item.get(field), str) for field in string_fields):
            return False
        if not isinstance(item.get("chunk_id"), int):
            return False
        if mode == "embedding":
            embedding = item.get("embedding")
            if (
                not isinstance(embedding, list)
                or not embedding
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in embedding
                )
            ):
                return False
            if embedding_size is None:
                embedding_size = len(embedding)
            elif len(embedding) != embedding_size:
                return False
        elif "embedding" in item:
            return False
    return bool(items) or mode == "lexical"


def build_index_items(
    documents: list[DocumentRecord],
    include_embeddings: bool = True,
    *,
    embedding_model: str = settings.EMBEDDING_MODEL,
    client_factory: Callable[[], OpenAI] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_content: set[str] = set()
    for document in documents:
        for chunk_id, chunk in enumerate(chunk_document(document["text"])):
            normalized = " ".join(chunk["text"].lower().split())
            content_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if content_key in seen_content:
                continue
            seen_content.add(content_key)
            items.append(
                {
                    "source": document["source"],
                    "document_id": document["document_id"],
                    "title": document["title"],
                    "category": document["category"],
                    "version": document["version"],
                    "section": chunk["section"],
                    "chunk_id": chunk_id,
                    "text": chunk["text"],
                }
            )

    if include_embeddings and items:
        _add_embeddings(
            items,
            embedding_model=embedding_model,
            client_factory=client_factory or create_openai_client,
        )
    return items


def documents_fingerprint(documents: list[DocumentRecord]) -> str:
    records = [
        {
            "source": document["source"],
            "content_hash": document["content_hash"],
            "title": document["title"],
            "category": document["category"],
            "version": document["version"],
        }
        for document in documents
    ]
    serialized = json.dumps(records, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _add_embeddings(
    items: list[dict[str, Any]],
    *,
    embedding_model: str,
    client_factory: Callable[[], OpenAI],
) -> bool:
    try:
        client = client_factory()
        embeddings: list[list[float]] = []
        for start in range(0, len(items), EMBEDDING_BATCH_SIZE):
            batch = items[start : start + EMBEDDING_BATCH_SIZE]
            response = client.embeddings.create(
                model=embedding_model,
                input=[item["text"] for item in batch],
            )
            embeddings.extend(item.embedding for item in response.data)
        if len(embeddings) != len(items):
            raise ValueError("Embedding response count did not match indexed chunk count")
        for item, embedding in zip(items, embeddings):
            item["embedding"] = embedding
        return True
    except (OpenAIError, OSError, TypeError, ValueError) as exc:
        for item in items:
            item.pop("embedding", None)
        logger.warning(
            "Embedding index build failed model=%s error=%s; using lexical index",
            embedding_model,
            type(exc).__name__,
        )
        return False
