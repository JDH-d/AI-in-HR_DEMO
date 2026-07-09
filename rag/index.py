from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from openai import OpenAIError

from core import settings
from services.document_reader import DocumentRecord, load_documents
from services.openai_client import create_openai_client

from .retriever import Retriever
from .text import chunk_document

DOCUMENTS_DIR = settings.DOCUMENTS_DIR
INDEX_PATH = settings.INDEX_PATH
EMBEDDING_MODEL = settings.EMBEDDING_MODEL
INDEX_SCHEMA_VERSION = 2
EMBEDDING_BATCH_SIZE = 64

_retriever: Optional[Retriever] = None
logger = logging.getLogger(__name__)


def ensure_index() -> None:
    global _retriever
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    documents = load_documents(DOCUMENTS_DIR)
    fingerprint = documents_fingerprint(documents)
    payload = _read_index_payload()

    if _is_current_payload(payload, fingerprint):
        return

    logger.info(
        "Rebuilding RAG index schema=%s documents=%s",
        INDEX_SCHEMA_VERSION,
        len(documents),
    )
    build_index(documents=documents)
    _retriever = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever.load(str(INDEX_PATH))
    return _retriever


def build_index(documents: list[DocumentRecord] | None = None) -> None:
    global _retriever
    documents = documents if documents is not None else load_documents(DOCUMENTS_DIR)
    items = build_index_items(documents)
    payload = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "embedding_model": EMBEDDING_MODEL,
        "documents_fingerprint": documents_fingerprint(documents),
        "items": items,
    }
    _write_index(payload)
    _retriever = None


def build_index_items(
    documents: list[DocumentRecord],
    include_embeddings: bool = True,
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
        _add_embeddings(items)
    return items


def rebuild_index() -> None:
    build_index()


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


def _add_embeddings(items: list[dict[str, Any]]) -> None:
    try:
        client = create_openai_client()
        embeddings: list[list[float]] = []
        for start in range(0, len(items), EMBEDDING_BATCH_SIZE):
            batch = items[start : start + EMBEDDING_BATCH_SIZE]
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=[item["text"] for item in batch],
            )
            embeddings.extend(item.embedding for item in response.data)
        if len(embeddings) != len(items):
            raise ValueError("Embedding response count did not match indexed chunk count")
        for item, embedding in zip(items, embeddings):
            item["embedding"] = embedding
    except (OpenAIError, OSError, TypeError, ValueError) as exc:
        for item in items:
            item.pop("embedding", None)
        logger.warning(
            "Embedding index build failed model=%s error=%s; using lexical index",
            EMBEDDING_MODEL,
            type(exc).__name__,
        )


def _read_index_payload() -> dict[str, Any] | None:
    try:
        with INDEX_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_current_payload(payload: dict[str, Any] | None, fingerprint: str) -> bool:
    if not payload:
        return False
    return (
        payload.get("schema_version") == INDEX_SCHEMA_VERSION
        and payload.get("embedding_model") == EMBEDDING_MODEL
        and payload.get("documents_fingerprint") == fingerprint
        and isinstance(payload.get("items"), list)
    )


def _write_index(payload: dict[str, Any]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = INDEX_PATH.with_suffix(f"{INDEX_PATH.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True)
    temp_path.replace(INDEX_PATH)
