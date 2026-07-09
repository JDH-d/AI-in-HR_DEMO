from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from rag.nlp import Intent


@dataclass(frozen=True)
class ChatTurn:
    role: str
    content: str


@dataclass(frozen=True)
class RetrievedChunk:
    source: str
    chunk_id: int
    text: str
    score: float


@dataclass(frozen=True)
class ChatQuery:
    messages: list[ChatTurn]
    top_k: int = 4
    min_similarity: float = 0.25

    @property
    def latest_user_message(self) -> Optional[ChatTurn]:
        return next((message for message in reversed(self.messages) if message.role == "user"), None)

    @property
    def first_user_message(self) -> Optional[ChatTurn]:
        return next((message for message in self.messages if message.role == "user"), None)


@dataclass(frozen=True)
class RoutingDecision:
    language: str
    intent: Intent
    topic_selection: Optional[str]
    explicit_topic_choice: bool
    prior_topic: Optional[str]


@dataclass
class ChatOutcome:
    content: str
    intent: Intent
    language: str
    sources: list[RetrievedChunk] = field(default_factory=list)
