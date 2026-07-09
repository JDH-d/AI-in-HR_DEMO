from __future__ import annotations

import json
import math
import os
import re
from typing import Dict, List

from openai import OpenAI, OpenAIError


class RetrieverError(RuntimeError):
    pass


class Retriever:
    def __init__(self, items: List[Dict]):
        self.items = items

    @classmethod
    def load(cls, path: str) -> "Retriever":
        try:
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            items = []
        return cls(items)

    def query(self, text: str, top_k: int = 4, min_similarity: float = 0.25) -> List[Dict]:
        if not self.items:
            return []

        query_embedding: List[float] | None = None
        try:
            embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            client = OpenAI()
            query_embedding = client.embeddings.create(
                model=embedding_model,
                input=[text],
            ).data[0].embedding
        except (IndexError, OpenAIError, OSError, TypeError, ValueError) as exc:
            query_embedding = None

        scored: List[Dict] = []
        for item in self.items:
            if query_embedding is not None and item.get("embedding"):
                score = _cosine_similarity(query_embedding, item.get("embedding", []))
            else:
                score = _lexical_similarity(text, item)
            if score >= min_similarity:
                scored.append(
                    {
                        "source": item["source"],
                        "chunk_id": item["chunk_id"],
                        "text": item["text"],
                        "score": score,
                    }
                )
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _lexical_similarity(query: str, item: Dict) -> float:
    query_terms = _normalize_terms(query)
    if not query_terms:
        return 0.0

    text_terms = set(_normalize_terms(item.get("text", "")))
    source_terms = set(_normalize_terms(item.get("source", "")))
    overlap = sum(1 for term in query_terms if term in text_terms)
    source_overlap = sum(1 for term in query_terms if term in source_terms)
    score = overlap / len(query_terms)
    if source_overlap:
        score += 0.12 * (source_overlap / len(query_terms))

    lowered_query = (query or "").strip().lower()
    lowered_text = (item.get("text", "") or "").lower()
    if lowered_query and lowered_query in lowered_text:
        score += 0.15

    return min(score, 1.0)


def _normalize_terms(text: str) -> List[str]:
    raw_terms = re.findall(r"[a-z0-9]+(?:[/-][a-z0-9]+)?", (text or "").lower())
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
        "with",
        "you",
        "your",
    }
    normalized: List[str] = []
    for term in raw_terms:
        if term in stop_words:
            continue
        if term.endswith("ies") and len(term) > 4:
            term = term[:-3] + "y"
        elif term.endswith("s") and len(term) > 4:
            term = term[:-1]
        normalized.append(term)
    return normalized
