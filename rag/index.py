from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from openai import OpenAI, OpenAIError

from core import settings
from services.document_reader import load_documents

from .retriever import Retriever
from .text import chunk_text


DOCUMENTS_DIR = settings.DOCUMENTS_DIR
INDEX_PATH = settings.INDEX_PATH
EMBEDDING_MODEL = settings.EMBEDDING_MODEL

_retriever: Optional[Retriever] = None
logger = logging.getLogger(__name__)


def ensure_index() -> None:
    global _retriever
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

    if INDEX_PATH.exists():
        try:
            with INDEX_PATH.open("r", encoding="utf-8") as f:
                items = json.load(f)
            if items:
                return
        except (json.JSONDecodeError, OSError):
            pass

        # Rebuild empty or unreadable index when documents exist.
        docs = load_documents(DOCUMENTS_DIR)
        if docs:
            logger.warning("Rebuilding RAG index after empty or unreadable index file: %s", INDEX_PATH)
            build_index()
        else:
            _write_index([])
            _retriever = None
            logger.info("RAG index initialized empty because no readable documents were found in %s", DOCUMENTS_DIR)
        return

    build_index()


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever.load(str(INDEX_PATH))
    return _retriever


def build_index() -> None:
    global _retriever
    docs = load_documents(DOCUMENTS_DIR)
    if not docs:
        _write_index([])
        _retriever = None
        logger.info("RAG index initialized empty because no readable documents were found in %s", DOCUMENTS_DIR)
        return

    client = OpenAI()
    chunks: List[Dict] = []
    for doc in docs:
        doc_chunks = chunk_text(doc["text"])
        for i, chunk in enumerate(doc_chunks):
            chunks.append(
                {
                    "source": doc["source"],
                    "chunk_id": i,
                    "text": chunk,
                }
            )

    if not chunks:
        _write_index([])
        return

    try:
        embeddings = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[c["text"] for c in chunks],
        )
    except (OpenAIError, OSError, TypeError, ValueError) as exc:
        logger.warning(
            "Failed to build vector index with model %s; falling back to lexical-only index: %s",
            EMBEDDING_MODEL,
            exc,
        )
        embeddings = None

    if embeddings is not None:
        for i, item in enumerate(embeddings.data):
            chunks[i]["embedding"] = item.embedding

    _write_index(chunks)
    _retriever = None


def rebuild_index() -> None:
    global _retriever
    build_index()
    _retriever = None


def _write_index(items: List[Dict]) -> None:
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=True)
