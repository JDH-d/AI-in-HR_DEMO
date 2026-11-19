from __future__ import annotations

import logging
import uuid
from dataclasses import asdict

from domain.chat import ChatQuery, ChatTurn
from domain.errors import ConversationError
from services.auth_service import DemoIdentity
from services.chat_service import ChatService
from storage.conversation_store import ConversationStore

logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(self, store: ConversationStore, chat: ChatService, lease_seconds: float = 180):
        self.store, self.chat, self.lease_seconds = store, chat, lease_seconds

    def record_user(self, identity: DemoIdentity):
        self.store.save_user(identity.public_dict())

    @staticmethod
    def _require_employee(identity: DemoIdentity) -> None:
        if identity.role != "employee":
            raise ConversationError("forbidden", "Chat is available only to Employees.")

    def create(
        self,
        identity: DemoIdentity,
        conversation_id: str | None = None,
        title: str = "New conversation",
    ):
        self._require_employee(identity)
        self.record_user(identity)
        return self.store.create(
            identity.id, conversation_id or str(uuid.uuid4()), self.title(title)
        )

    def list(self, identity: DemoIdentity, query: str = "", limit: int = 50, offset: int = 0):
        self._require_employee(identity)
        return self.store.list(
            identity.id, query.strip()[:200], min(max(limit, 1), 100), max(offset, 0)
        )

    def get(self, identity: DemoIdentity, conversation_id: str):
        self._require_employee(identity)
        return self.store.get(conversation_id, identity.id)

    def rename(self, identity: DemoIdentity, conversation_id: str, title: str):
        self._require_employee(identity)
        return self.store.rename(conversation_id, identity.id, self.title(title))

    def delete(self, identity: DemoIdentity, conversation_id: str):
        self._require_employee(identity)
        self.store.delete(conversation_id, identity.id)

    @staticmethod
    def title(value: str) -> str:
        value = value.strip()
        if not value or len(value) > 120:
            raise ConversationError("invalid", "Title must contain 1 to 120 characters.")
        return value

    def send(
        self,
        identity: DemoIdentity,
        conversation_id: str,
        content: str,
        turn_id: str,
        *,
        top_k=4,
        min_similarity=0.25,
    ):
        self._require_employee(identity)
        content = content.strip()
        if not content or len(content) > 16000:
            raise ConversationError("invalid", "Message must contain 1 to 16000 characters.")
        turn = self.store.begin_turn(
            conversation_id, identity.id, turn_id, content, self.lease_seconds
        )
        if not turn["cached"]:
            try:
                outcome = self.chat.respond(
                    ChatQuery(
                        [ChatTurn(m["role"], m["content"]) for m in turn["history"]],
                        top_k,
                        min_similarity,
                    ),
                    created_by=identity.id,
                    allow_workflow=identity.role == "employee",
                )
                self.store.finish_turn(
                    conversation_id,
                    turn_id,
                    outcome.content,
                    {
                        "sources": [asdict(source) for source in outcome.sources],
                        "workflow": outcome.workflow_request,
                        "intent": outcome.intent.value,
                        "language": outcome.language,
                        "question": content,
                    },
                    attempt_id=turn["attempt_id"],
                )
            except Exception:
                logger.error(
                    "Conversation response failed: conversation=%s turn=%s",
                    conversation_id,
                    turn_id,
                )
                self.store.finish_turn(
                    conversation_id,
                    turn_id,
                    "The assistant could not reply. Your message is saved; retry when the service is available.",
                    {},
                    attempt_id=turn["attempt_id"],
                    failed=True,
                )
                raise ConversationError(
                    "unavailable", "Your message is saved, but the reply failed. Please retry."
                ) from None
        detail = self.get(identity, conversation_id)
        pair = [m for m in detail["messages"] if m["turn_id"] == turn_id]
        if pair[1]["status"] != "complete":
            raise ConversationError(
                "conflict", "This reply was interrupted or superseded. Reload the conversation."
            )
        return {"conversation": detail["conversation"], "user_message": pair[0], "message": pair[1]}
