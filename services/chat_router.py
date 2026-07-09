from __future__ import annotations

from rag.nlp import Intent, detect_intent, detect_language, detect_topic_selection

from .chat_models import ChatQuery, RoutingDecision
from .document_service import DocumentService


class ChatRouter:
    def __init__(self, document_service: DocumentService) -> None:
        self.document_service = document_service

    def route(self, query: ChatQuery) -> RoutingDecision:
        latest_user = query.latest_user_message
        first_user = query.first_user_message
        if latest_user is None:
            return RoutingDecision(
                language="en",
                intent=Intent.INVALID,
                topic_selection=None,
                explicit_topic_choice=False,
                prior_topic=None,
            )

        language = detect_language(first_user.content if first_user else latest_user.content)
        topic_selection = detect_topic_selection(latest_user.content)
        intent = detect_intent(latest_user.content)
        explicit_topic_choice = self._is_explicit_topic_choice(latest_user.content)
        prior_topic = self.find_prior_topic(query)

        if intent == Intent.INVALID and not topic_selection and prior_topic:
            if self._should_use_prior_topic(latest_user.content):
                intent = Intent.WORK

        return RoutingDecision(
            language=language,
            intent=intent,
            topic_selection=topic_selection,
            explicit_topic_choice=explicit_topic_choice,
            prior_topic=prior_topic,
        )

    def find_prior_topic(self, query: ChatQuery) -> str | None:
        for message in reversed(query.messages):
            if message.role not in {"user", "assistant"}:
                continue
            if self._is_explicit_topic_choice(message.content):
                topic = detect_topic_selection(message.content)
                if topic:
                    return topic
        return None

    def _is_explicit_topic_choice(self, text: str) -> bool:
        return self.document_service.is_numeric_topic_choice(
            text
        ) or self.document_service.is_exact_topic_text(text)

    @staticmethod
    def _should_use_prior_topic(text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        if any(
            phrase in lowered
            for phrase in ("tell me a joke", "joke", "weather", "movie", "music")
        ):
            return False
        return any(
            lowered.startswith(prefix)
            for prefix in (
                "how ",
                "what ",
                "when ",
                "where ",
                "which ",
                "can ",
                "could ",
                "do ",
                "does ",
                "is ",
                "are ",
                "am ",
                "will ",
                "would ",
                "any ",
                "and ",
                "also ",
            )
        ) or "?" in lowered
