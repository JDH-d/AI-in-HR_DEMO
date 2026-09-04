from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rag.nlp import Intent


@dataclass(frozen=True)
class ChatTurn:
    role: Literal["user", "assistant", "system"]
    content: str


@dataclass(frozen=True)
class RetrievedChunk:
    source: str
    chunk_id: int
    title: str
    section: str
    category: str
    version: str
    excerpt: str
    score: float


@dataclass(frozen=True)
class ChatQuery:
    messages: list[ChatTurn]
    top_k: int = 4
    min_similarity: float = 0.25

    @property
    def latest_user_message(self) -> ChatTurn | None:
        return next(
            (message for message in reversed(self.messages) if message.role == "user"), None
        )

    @property
    def first_user_message(self) -> ChatTurn | None:
        return next((message for message in self.messages if message.role == "user"), None)

    @property
    def previous_user_message(self) -> ChatTurn | None:
        user_messages = [message for message in self.messages if message.role == "user"]
        return user_messages[-2] if len(user_messages) >= 2 else None

    def retrieval_text(self) -> str:
        latest = self.latest_user_message
        if latest is None:
            return ""
        previous = self.previous_user_message
        normalized = " ".join(latest.content.lower().split()).strip(" ?.!\")'")
        follows_context = len(normalized.split()) <= 9 and (
            normalized
            in {
                "tell me more",
                "can you explain",
                "could you explain",
                "can you elaborate",
                "what about that",
                "how does that work",
            }
            or any(
                token in normalized.split()
                for token in {"it", "that", "this", "they", "them", "those"}
            )
        )
        if previous is not None and follows_context:
            return f"{previous.content}\nFollow-up: {latest.content}"
        return latest.content


@dataclass(frozen=True)
class RoutingDecision:
    language: str
    intent: Intent
    topic_selection: str | None
    explicit_topic_choice: bool
    prior_topic: str | None


@dataclass
class ChatOutcome:
    content: str
    intent: Intent
    language: str
    sources: list[RetrievedChunk] = field(default_factory=list)
    workflow_request: dict | None = None
    outcome_code: str = "guided"


@dataclass(frozen=True)
class ChatStreamUpdate:
    kind: Literal["token", "replace", "complete"]
    content: str = ""
    outcome: ChatOutcome | None = None
