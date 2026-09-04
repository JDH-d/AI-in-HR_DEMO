from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable
from typing import Any

from openai import OpenAI, OpenAIError

from core import settings
from services.openai_client import create_openai_client

logger = logging.getLogger(__name__)


class RetrieverError(RuntimeError):
    pass


class Retriever:
    def __init__(
        self,
        items: list[dict[str, Any]],
        client_factory: Callable[[], OpenAI] | None = None,
        embedding_model: str = settings.EMBEDDING_MODEL,
    ) -> None:
        self.items = items
        self.client_factory = client_factory or create_openai_client
        self.embedding_model = embedding_model
        self._client: OpenAI | None = None

    @classmethod
    def load(
        cls,
        path: str,
        *,
        client_factory: Callable[[], OpenAI] | None = None,
        embedding_model: str = settings.EMBEDDING_MODEL,
    ) -> "Retriever":
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            raise RetrieverError(f"Unable to load retrieval index: {type(exc).__name__}") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise RetrieverError("Retrieval index has an unsupported schema")
        return cls(
            payload["items"],
            client_factory=client_factory,
            embedding_model=embedding_model,
        )

    def query(
        self,
        text: str,
        top_k: int = 4,
        min_similarity: float = 0.25,
        use_embeddings: bool = True,
    ) -> list[dict[str, Any]]:
        if not self.items:
            return []

        query_embedding = self._query_embedding(text) if use_embeddings else None
        scored: list[dict[str, Any]] = []
        for item in self.items:
            lexical_score = _lexical_similarity(text, item)
            semantic_score: float | None = None
            if query_embedding is not None and item.get("embedding"):
                semantic_score = _cosine_similarity(query_embedding, item["embedding"])
                if lexical_score == 0.0 and semantic_score < 0.48:
                    continue
                score = 0.72 * semantic_score + 0.28 * lexical_score
            else:
                score = lexical_score

            if score < min_similarity:
                continue
            section = item.get("section", "Document overview")
            section_prefix = section if section.endswith((".", "?", "!")) else f"{section}."
            scored.append(
                {
                    "source": item["source"],
                    "document_id": item.get("document_id", ""),
                    "title": item.get("title") or item["source"],
                    "category": item.get("category", "General"),
                    "version": item.get("version", "unversioned"),
                    "section": section,
                    "chunk_id": item["chunk_id"],
                    "text": item["text"],
                    "excerpt": build_relevant_excerpt(
                        f"{section_prefix} {item['text']}",
                        text,
                    ),
                    "score": score,
                    "semantic_score": semantic_score,
                    "lexical_score": lexical_score,
                }
            )

        scored.sort(key=lambda result: result["score"], reverse=True)
        return _deduplicate_results(scored, top_k)

    def _query_embedding(self, text: str) -> list[float] | None:
        if not any(item.get("embedding") for item in self.items):
            return None
        try:
            response = self._get_client().embeddings.create(
                model=self.embedding_model,
                input=[text],
            )
            return response.data[0].embedding
        except (IndexError, OpenAIError, OSError, TypeError, ValueError) as exc:
            logger.warning(
                "Query embedding failed model=%s error=%s; using lexical retrieval",
                self.embedding_model,
                type(exc).__name__,
            )
            return None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = self.client_factory()
        return self._client


def build_relevant_excerpt(text: str, query: str, max_chars: int = 360) -> str:
    cleaned = re.sub(r"\s+", " ", re.sub(r"#{1,6}\s*", "", text or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned

    sentences = [
        sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", cleaned) if sentence.strip()
    ]
    if not sentences:
        return cleaned[: max_chars - 3].rstrip() + "..."

    query_terms = set(_normalize_terms(query))
    best_index = max(
        range(len(sentences)),
        key=lambda index: len(query_terms.intersection(_normalize_terms(sentences[index]))),
    )
    selected = [sentences[best_index]]
    if sentences[best_index].endswith("?") and best_index + 1 < len(sentences):
        selected.append(sentences[best_index + 1])
    elif best_index > 0 and sentences[best_index - 1].endswith("?"):
        selected.insert(0, sentences[best_index - 1])
    elif best_index + 1 < len(sentences):
        selected.append(sentences[best_index + 1])

    excerpt = " ".join(selected)
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[: max_chars - 3].rstrip() + "..."


def _deduplicate_results(
    scored: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_sections: set[tuple[str, str]] = set()
    seen_term_sets: list[set[str]] = []
    semantic_cutoff = 0.0
    if scored and scored[0].get("semantic_score") is not None:
        semantic_cutoff = scored[0]["score"] * 0.75
    for result in scored:
        if result["score"] < semantic_cutoff:
            continue
        document_key = result.get("document_id") or result["source"]
        section_key = (
            document_key,
            result.get("section", "").lower(),
        )
        if section_key in seen_sections:
            continue

        terms = set(_normalize_terms(result["text"]))
        if any(_jaccard_similarity(terms, seen) >= 0.9 for seen in seen_term_sets):
            continue

        selected.append(result)
        seen_sections.add(section_key)
        seen_term_sets.append(terms)
        if len(selected) >= top_k:
            break
    return selected


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _lexical_similarity(query: str, item: dict[str, Any]) -> float:
    query_terms = _normalize_terms(query)
    if not query_terms:
        return 0.0

    query_set = set(query_terms)
    section_terms = set(_normalize_terms(item.get("section", "")))
    body_terms = set(_normalize_terms(item.get("text", "")))
    document_terms = set(_normalize_terms(f"{item.get('title', '')} {item.get('category', '')}"))
    section_overlap = len(query_set.intersection(section_terms)) / len(query_set)
    body_overlap = len(query_set.intersection(body_terms)) / len(query_set)
    document_overlap = len(query_set.intersection(document_terms)) / len(query_set)
    score = 0.55 * section_overlap + 0.4 * body_overlap + 0.05 * document_overlap

    lowered_query = (query or "").strip().lower()
    searchable_text = f"{item.get('section', '')} {item.get('text', '')}".lower()
    if lowered_query and lowered_query in searchable_text:
        score += 0.15
    return min(score, 1.0)


def _normalize_terms(text: str) -> list[str]:
    raw_terms = re.findall(r"[a-z0-9]+", (text or "").lower())
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "should",
        "the",
        "their",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
        "you",
        "your",
    }
    normalized: list[str] = []
    synonyms = {
        "app": "application",
        "decide": "decide",
        "determine": "decide",
        "hire": "employee",
    }
    for term in raw_terms:
        if term in stop_words:
            continue
        if term.endswith("ies") and len(term) > 4:
            term = term[:-3] + "y"
        elif term.endswith("ing") and len(term) > 5:
            term = term[:-3]
        elif term.endswith("ed") and len(term) > 4:
            term = term[:-2]
        elif term.endswith("s") and len(term) > 4:
            term = term[:-1]
        normalized.append(synonyms.get(term, term))
    return normalized


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))
