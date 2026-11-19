from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable

from domain.chat import ChatOutcome, ChatQuery, RetrievedChunk, RoutingDecision
from integrations.llm_service import LLMService, LLMServiceError
from rag.index import ensure_index, get_retriever
from rag.nlp import Intent, extract_keywords, strip_greeting
from rag.prompts import build_general_prompt, build_rag_prompt
from rag.retriever import Retriever, RetrieverError
from storage.ai_settings_store import AI_SETTINGS_DEFAULTS, AISettingsStore
from storage.prompt_store import PromptStore

from .chat_fallbacks import ChatFallbackPolicy
from .source_selection_service import SourceSelectionService

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(
        self,
        llm_service: LLMService,
        fallback_policy: ChatFallbackPolicy,
        index_ensurer: Callable[[], None] | None = None,
        retriever_provider: Callable | None = None,
        ai_settings_store: AISettingsStore | None = None,
        prompt_store: PromptStore | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.fallback_policy = fallback_policy
        self.index_ensurer = index_ensurer
        self.retriever_provider = retriever_provider
        self.ai_settings_store = ai_settings_store
        self.prompt_store = prompt_store
        self.source_selection = SourceSelectionService(llm_service)

    def answer_with_retrieval(
        self,
        query: ChatQuery,
        decision: RoutingDecision,
        settings: dict[str, bool] | None = None,
        system_prompt: str | None = None,
    ) -> ChatOutcome:
        if system_prompt is None and self.prompt_store is not None:
            system_prompt = self.prompt_store.get()
        active_settings = settings or (
            self.ai_settings_store.get()
            if self.ai_settings_store is not None
            else dict(AI_SETTINGS_DEFAULTS)
        )
        latest_user = query.latest_user_message
        if latest_user is None:
            return ChatOutcome(
                content=self.fallback_policy.invalid(decision.language),
                intent=decision.intent,
                language=decision.language,
            )

        selection_unavailable = False
        try:
            if self.index_ensurer:
                self.index_ensurer()
            else:
                ensure_index()
            retriever = self.retriever_provider() if self.retriever_provider else get_retriever()
            retrieval_text = strip_greeting(latest_user.content)
            if decision.context_question:
                retrieval_text = f"{decision.context_question}\n{retrieval_text}"
            if (
                not decision.context_question
                and decision.intent == Intent.WORK
                and decision.prior_topic
                and not decision.explicit_topic_choice
            ):
                retrieval_text = f"{decision.prior_topic}. {retrieval_text}"
            results = retriever.query(
                retrieval_text,
                top_k=query.top_k,
                min_similarity=query.min_similarity,
            )
            if not Retriever.is_exact_question(latest_user.content, results):
                candidates = retriever.selection_candidates(retrieval_text)
                # Compound questions need an evidence budget independent of lexical top_k.
                selected = self.source_selection.select(query, candidates, limit=8)
                if selected is not None:
                    results = selected
                elif isinstance(candidates, list) and candidates:
                    selection_unavailable = True
        except (OSError, RetrieverError, RuntimeError, sqlite3.Error, ValueError) as exc:
            logger.warning(
                "RAG retrieval failed intent=%s error_type=%s",
                decision.intent.value,
                type(exc).__name__,
            )
            return ChatOutcome(
                content=self.fallback_policy.service_unavailable(decision.language),
                intent=decision.intent,
                language=decision.language,
                sources=[],
            )

        if not results:
            if decision.intent == Intent.INVALID:
                content = self.fallback_policy.invalid(decision.language)
            elif selection_unavailable:
                content = self.fallback_policy.service_unavailable(decision.language)
            elif not active_settings.get("strict_grounding", True):
                content = self.generate_with_fallback(
                    build_general_prompt(
                        decision.language,
                        query.messages,
                        system_prompt=system_prompt,
                        settings=active_settings,
                    ),
                    self.fallback_policy.no_docs(decision.language),
                )
            else:
                content = self.fallback_policy.no_docs(decision.language)
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
            build_rag_prompt(
                decision.language,
                query.messages,
                results,
                system_prompt=system_prompt,
                settings=active_settings,
            ),
            fallback_text,
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
        return ChatOutcome(
            content=content,
            intent=Intent.WORK,
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

        keywords = extract_keywords(query_text)
        candidates: list[tuple[int, float, str]] = []
        seen: set[str] = set()
        normalized_query = self._normalize_sentence(query_text)

        for result in results[:3]:
            text = (result.get("text") or "").strip()
            if not text:
                continue
            section = result.get("section", "")
            section_score = sum(1 for keyword in keywords if keyword in section.lower())
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
                keyword_score = sum(1 for keyword in keywords if keyword in lowered) + section_score
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
