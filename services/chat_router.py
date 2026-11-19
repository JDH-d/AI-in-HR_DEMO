from __future__ import annotations

import re

from domain.chat import ChatQuery, RoutingDecision
from rag.nlp import (
    Intent,
    detect_intent,
    detect_language,
    detect_topic_selection,
    is_exact_topic_text,
    is_numeric_topic_choice,
)


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
        context_question = None

        if intent == Intent.INVALID and not topic_selection:
            if self._should_use_prior_topic(latest_user.content):
                if self._references_history(latest_user.content):
                    context_question = self._previous_work_question(query)
                if prior_topic or context_question:
                    intent = Intent.WORK

        return RoutingDecision(
            language=language,
            intent=intent,
            topic_selection=topic_selection,
            explicit_topic_choice=explicit_topic_choice,
            prior_topic=prior_topic,
            context_question=context_question,
        )

    @staticmethod
    def _references_history(text: str) -> bool:
        return bool(
            re.search(
                r"\b(it|its|they|them|their|that|those|this|these|both|earlier|previous|above|same)\b"
                r"|^(and|also)\b|\b(tell me more|explain more)\b",
                text.strip(),
                re.IGNORECASE,
            )
        )

    def _previous_work_question(self, query: ChatQuery) -> str | None:
        prior_users = [message for message in query.messages if message.role == "user"][:-1]
        for message in reversed(prior_users):
            if self._is_explicit_topic_choice(message.content):
                # A topic selection is a context boundary; use its existing topic guidance.
                return None
            if detect_intent(message.content) == Intent.WORK:
                return message.content
        return None

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
        return is_numeric_topic_choice(text) or is_exact_topic_text(text)

    @staticmethod
    def _should_use_prior_topic(text: str) -> bool:
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
                )
            )
            or "?" in lowered
        )
