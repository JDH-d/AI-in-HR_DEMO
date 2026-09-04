from __future__ import annotations

from rag.nlp import (
    Intent,
    detect_intent,
    detect_language,
    detect_topic_selection,
    is_explicit_topic_choice,
)

from .chat_models import ChatQuery, RoutingDecision


class ChatRouter:
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
        previous_user = query.previous_user_message
        previous_was_work = bool(
            previous_user and detect_intent(previous_user.content) == Intent.WORK
        )

        if intent == Intent.INVALID and not topic_selection and (prior_topic or previous_was_work):
            if self._should_continue_conversation(latest_user.content):
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
        return is_explicit_topic_choice(text)

    @staticmethod
    def _should_continue_conversation(text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        if any(
            phrase in lowered for phrase in ("tell me a joke", "joke", "weather", "movie", "music")
        ):
            return False
        return (
            any(
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
                    "tell me more",
                    "explain ",
                )
            )
            or "?" in lowered
        )
