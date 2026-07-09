from __future__ import annotations

import logging
import re
import sqlite3

from rag.index import ensure_index, get_retriever
from rag.prompts import build_invalid_prompt, build_rag_prompt, build_topic_answer_prompt
from rag.retriever import RetrieverError

from .chat_fallbacks import ChatFallbackPolicy
from .chat_models import ChatOutcome, ChatQuery, RetrievedChunk, RoutingDecision
from .document_service import DocumentService
from .llm_service import LLMService, LLMServiceError


logger = logging.getLogger(__name__)


class RAGService:
    def __init__(
        self,
        llm_service: LLMService,
        document_service: DocumentService,
        fallback_policy: ChatFallbackPolicy,
    ) -> None:
        self.llm_service = llm_service
        self.document_service = document_service
        self.fallback_policy = fallback_policy

    def answer_from_topic(self, topic: str, user_text: str, language: str) -> str | None:
        doc_text = self.document_service.load_text_for_topic(topic)
        if not doc_text:
            return None
        prompt_context = self.document_service.build_topic_prompt_context(doc_text, user_text)
        fallback_text = self.fallback_policy.topic_answer(
            language,
            topic,
            self.document_service.filter_doc_by_query(doc_text, user_text),
        )
        return self.generate_with_fallback(
            build_topic_answer_prompt(language, topic, user_text, prompt_context),
            fallback_text,
        )

    def answer_with_retrieval(self, query: ChatQuery, decision: RoutingDecision) -> ChatOutcome:
        latest_user = query.latest_user_message
        if latest_user is None:
            return ChatOutcome(
                content=self.fallback_policy.invalid(decision.language),
                intent=decision.intent,
                language=decision.language,
            )

        try:
            ensure_index()
            retriever = get_retriever()
            results = retriever.query(
                latest_user.content,
                top_k=query.top_k,
                min_similarity=query.min_similarity,
            )
        except (OSError, RetrieverError, RuntimeError, sqlite3.Error, ValueError) as exc:
            logger.warning("RAG retrieval failed for intent %s: %s", decision.intent.value, exc)
            return ChatOutcome(
                content=self.fallback_policy.service_unavailable(decision.language),
                intent=decision.intent,
                language=decision.language,
                sources=[],
            )

        if not results:
            content = self.generate_with_fallback(
                build_invalid_prompt(
                    decision.language,
                    query.messages,
                    reason="no_relevant_docs",
                ),
                self.fallback_policy.no_docs(decision.language),
            )
            return ChatOutcome(
                content=content,
                intent=decision.intent,
                language=decision.language,
                sources=[],
            )

        fallback_text = self._build_extractive_fallback(
            decision.language,
            latest_user.content,
            results,
        )
        content = self.generate_with_fallback(
            build_rag_prompt(decision.language, query.messages, results),
            fallback_text,
        )
        sources = [
            RetrievedChunk(
                source=result["source"],
                chunk_id=result["chunk_id"],
                text=result["text"],
                score=result["score"],
            )
            for result in results
        ]
        return ChatOutcome(
            content=content,
            intent=decision.intent,
            language=decision.language,
            sources=sources,
        )

    def generate_with_fallback(self, prompt_messages: list[dict], fallback_text: str) -> str:
        try:
            content = self.llm_service.generate(prompt_messages).strip()
            return content or fallback_text
        except LLMServiceError:
            return fallback_text

    def _build_extractive_fallback(
        self,
        language: str,
        query_text: str,
        results: list[dict],
    ) -> str:
        faq_answer = self._extract_direct_answer(query_text, results)
        if faq_answer:
            return faq_answer

        keywords = self.document_service._extract_keywords(query_text)
        candidates: list[tuple[int, float, str]] = []
        seen: set[str] = set()
        normalized_query = self._normalize_sentence(query_text)

        for result in results[:3]:
            text = (result.get("text") or "").strip()
            if not text:
                continue
            normalized_text = re.sub(r"#{2,6}\s*", ". ", text)
            normalized_text = re.sub(r"\s-\s+", ". ", normalized_text)
            sentences = re.split(r"(?<=[.!?])\s+", normalized_text)
            for sentence in sentences:
                cleaned = self._clean_candidate_sentence(sentence)
                if not cleaned or cleaned in seen:
                    continue
                if "?" in cleaned:
                    _, _, tail = cleaned.partition("?")
                    tail = tail.strip()
                    if tail:
                        cleaned = tail
                seen.add(cleaned)
                if self._normalize_sentence(cleaned) == normalized_query:
                    continue
                lowered = cleaned.lower()
                keyword_score = sum(1 for keyword in keywords if keyword in lowered)
                if keyword_score <= 0 and keywords:
                    continue
                candidates.append((keyword_score, len(cleaned), cleaned))

        if candidates:
            candidates.sort(key=lambda item: (-item[0], item[1]))
            return "\n".join(item[2] for item in candidates[:2])
        return self.fallback_policy.no_docs(language)

    def _extract_direct_answer(self, query_text: str, results: list[dict]) -> str:
        lowered_query = (query_text or "").strip().lower()
        if not lowered_query or not lowered_query.endswith("?"):
            return ""

        for result in results[:3]:
            text = (result.get("text") or "").strip()
            if not text:
                continue
            normalized_text = re.sub(r"#{2,6}\s*", ". ", text)
            lowered_text = normalized_text.lower()
            idx = lowered_text.find(lowered_query)
            if idx < 0:
                continue
            tail = normalized_text[idx + len(lowered_query):].strip(" :-\n\t")
            if not tail:
                continue
            parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", tail) if part.strip()]
            if not parts:
                continue
            if not re.search(r"[.!?]$", parts[0]):
                continue
            first = self._clean_candidate_sentence(parts[0])
            if not first:
                continue
            if len(first.split()) < 4 and len(parts) > 1:
                second = self._clean_candidate_sentence(parts[1])
                if second:
                    return f"{first} {second}"
            return first
        return ""

    @staticmethod
    def _clean_candidate_sentence(sentence: str) -> str:
        cleaned = re.sub(r"#+\s*", "", sentence or "")
        cleaned = re.sub(r"\*+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:\n\t")
        bad_fragments = (
            "Document Owner:",
            "Effective Date:",
            "Review Cadence:",
            "Audience Note:",
            "Related Documents:",
            "Frequently Asked Questions",
            "Pacific Beacon Software, Inc.",
        )
        if not cleaned or any(fragment.lower() in cleaned.lower() for fragment in bad_fragments):
            return ""
        bad_starts = (
            "A typical operating example is this",
            "This topic works best when",
            "The company uses structured approvals",
            "Pacific Beacon treats",
        )
        if any(cleaned.startswith(fragment) for fragment in bad_starts):
            return ""
        if cleaned.endswith("?"):
            return ""
        return cleaned

    @staticmethod
    def _normalize_sentence(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
