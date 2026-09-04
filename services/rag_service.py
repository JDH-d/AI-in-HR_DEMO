from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from rag.index import KnowledgeIndex
from rag.nlp import Intent
from rag.prompts import build_general_prompt, build_rag_prompt
from rag.retriever import RetrieverError
from rag.text import extract_keywords

from .ai_settings_service import AI_SETTINGS_DEFAULTS, AISettingsService
from .chat_fallbacks import ChatFallbackPolicy
from .chat_models import ChatOutcome, ChatQuery, RetrievedChunk, RoutingDecision
from .llm_service import LLMService, LLMServiceError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedRAGAnswer:
    prompt_messages: list[dict]
    fallback_text: str
    intent: Intent
    language: str
    sources: list[RetrievedChunk]
    outcome_code: str

    def complete(self, content: str) -> ChatOutcome:
        return ChatOutcome(
            content=content,
            intent=self.intent,
            language=self.language,
            sources=self.sources,
            outcome_code=self.outcome_code,
        )


class RAGService:
    def __init__(
        self,
        llm_service: LLMService,
        fallback_policy: ChatFallbackPolicy,
        knowledge_index: KnowledgeIndex,
        ai_settings_service: AISettingsService | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.fallback_policy = fallback_policy
        self.knowledge_index = knowledge_index
        self.ai_settings_service = ai_settings_service

    def answer_with_retrieval(
        self,
        query: ChatQuery,
        decision: RoutingDecision,
        settings: dict[str, bool] | None = None,
        system_prompt: str | None = None,
    ) -> ChatOutcome:
        prepared = self.prepare_answer(
            query,
            decision,
            settings=settings,
            system_prompt=system_prompt,
        )
        if isinstance(prepared, ChatOutcome):
            return prepared
        content = self.generate_with_fallback(
            prepared.prompt_messages,
            prepared.fallback_text,
        )
        return prepared.complete(content)

    def prepare_answer(
        self,
        query: ChatQuery,
        decision: RoutingDecision,
        settings: dict[str, bool] | None = None,
        system_prompt: str | None = None,
    ) -> ChatOutcome | PreparedRAGAnswer:
        active_settings = settings or (
            self.ai_settings_service.get()
            if self.ai_settings_service is not None
            else dict(AI_SETTINGS_DEFAULTS)
        )
        latest_user = query.latest_user_message
        if latest_user is None:
            return ChatOutcome(
                content=self.fallback_policy.invalid(),
                intent=decision.intent,
                language=decision.language,
                outcome_code="unsupported",
            )

        try:
            self.knowledge_index.ensure()
            retriever = self.knowledge_index.get_retriever()
            retrieval_text = query.retrieval_text()
            if (
                decision.intent == Intent.WORK
                and decision.prior_topic
                and not decision.explicit_topic_choice
            ):
                retrieval_text = f"{decision.prior_topic}. {latest_user.content}"
            results = retriever.query(
                retrieval_text,
                top_k=query.top_k,
                min_similarity=query.min_similarity,
            )
        except (OSError, RetrieverError, RuntimeError, ValueError) as exc:
            logger.warning("RAG retrieval failed for intent %s: %s", decision.intent.value, exc)
            return ChatOutcome(
                content=self.fallback_policy.service_unavailable(),
                intent=decision.intent,
                language=decision.language,
                sources=[],
                outcome_code="unavailable",
            )

        if not results:
            if decision.intent == Intent.INVALID:
                return ChatOutcome(
                    content=self.fallback_policy.invalid(),
                    intent=decision.intent,
                    language=decision.language,
                    sources=[],
                    outcome_code="unsupported",
                )
            if not active_settings.get("strict_grounding", True):
                return PreparedRAGAnswer(
                    prompt_messages=build_general_prompt(
                        decision.language,
                        query.messages,
                        system_prompt=system_prompt,
                        settings=active_settings,
                    ),
                    fallback_text=self.fallback_policy.no_docs(),
                    intent=decision.intent,
                    language=decision.language,
                    sources=[],
                    outcome_code="general",
                )
            return ChatOutcome(
                content=self.fallback_policy.no_docs(),
                intent=decision.intent,
                language=decision.language,
                sources=[],
                outcome_code="no_match",
            )

        fallback_text = self._build_extractive_fallback(
            latest_user.content,
            results,
        )
        sources = [
            RetrievedChunk(
                source=result["source"],
                chunk_id=result["chunk_id"],
                title=result["title"],
                section=result["section"],
                category=result["category"],
                version=result["version"],
                excerpt=result["excerpt"],
                score=result["score"],
            )
            for result in results
        ]
        return PreparedRAGAnswer(
            prompt_messages=build_rag_prompt(
                decision.language,
                query.messages,
                results,
                system_prompt=system_prompt,
                settings=active_settings,
            ),
            fallback_text=fallback_text,
            intent=Intent.WORK,
            language=decision.language,
            sources=sources,
            outcome_code="grounded",
        )

    def generate_with_fallback(self, prompt_messages: list[dict], fallback_text: str) -> str:
        try:
            content = self.llm_service.generate(prompt_messages).strip()
            return content or fallback_text
        except LLMServiceError:
            return fallback_text

    def _build_extractive_fallback(
        self,
        query_text: str,
        results: list[dict],
    ) -> str:
        faq_answer = self._extract_direct_answer(query_text, results)
        if faq_answer:
            return faq_answer

        keywords = extract_keywords(query_text)
        candidates: list[tuple[int, int, str]] = []
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
        return self.fallback_policy.no_docs()

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
            tail = normalized_text[idx + len(lowered_query) :].strip(" :-\n\t")
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
        )
        if not cleaned or any(fragment.lower() in cleaned.lower() for fragment in bad_fragments):
            return ""
        if cleaned.endswith("?"):
            return ""
        return cleaned

    @staticmethod
    def _normalize_sentence(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
