from __future__ import annotations

import asyncio
from typing import Any

from botbuilder.core import ActivityHandler, MessageFactory, TurnContext
from botbuilder.schema import ChannelAccount
from fastapi import HTTPException

from api.schemas import ChatRequest, Message
from services.chat_service import ChatService

from .formatting import format_chat_response, normalize_teams_text
from .history import TeamsConversationHistory


class TeamsPersonalChatBot(ActivityHandler):
    def __init__(
        self,
        chat_service: ChatService,
        history: TeamsConversationHistory,
        max_context_messages: int = 12,
        max_source_count: int = 3,
    ) -> None:
        self.chat_service = chat_service
        self.history = history
        self.max_context_messages = max_context_messages
        self.max_source_count = max_source_count

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        if not self._is_personal_chat(turn_context):
            await turn_context.send_activity(
                MessageFactory.text(
                    "This bot is configured for one-on-one chat. Open the bot directly and send your question there."
                )
            )
            return

        text = self._activity_text(turn_context)
        conversation_key = self._conversation_key(turn_context)
        if not text:
            await turn_context.send_activity(MessageFactory.text(self._help_text()))
            return

        if text.lower() in {"clear", "/clear", "reset"}:
            self.history.clear(conversation_key)
            await turn_context.send_activity(MessageFactory.text("Conversation history cleared."))
            return

        response = await self._respond(conversation_key, self._user_id(turn_context), text)
        await turn_context.send_activity(MessageFactory.text(response))

    async def on_members_added_activity(
        self,
        members_added: list[ChannelAccount],
        turn_context: TurnContext,
    ) -> None:
        if not self._is_personal_chat(turn_context):
            return

        recipient_id = getattr(turn_context.activity.recipient, "id", None)
        for member in members_added:
            if getattr(member, "id", None) != recipient_id:
                await turn_context.send_activity(MessageFactory.text(self._help_text()))

    async def _respond(self, conversation_key: str, user_id: str, text: str) -> str:
        history = self.history.load(conversation_key, self.max_context_messages - 1)
        request = ChatRequest(messages=history + [Message(role="user", content=text)])
        try:
            response = await asyncio.to_thread(
                self.chat_service.handle_chat,
                request,
                user_id,
            )
        except HTTPException as exc:
            detail = str(exc.detail or "The assistant could not process this message.")
            return f"Service error ({exc.status_code}): {detail}"

        self.history.append_turn(
            conversation_key,
            text,
            response.message.content,
        )
        return format_chat_response(response, max_sources=self.max_source_count)

    @staticmethod
    def _activity_text(turn_context: TurnContext) -> str:
        try:
            text = TurnContext.remove_recipient_mention(turn_context.activity)
        except Exception:
            text = turn_context.activity.text
        return normalize_teams_text(text)

    @staticmethod
    def _is_personal_chat(turn_context: TurnContext) -> bool:
        conversation = turn_context.activity.conversation
        conversation_type = getattr(conversation, "conversation_type", None)
        return conversation_type in {None, "", "personal"}

    @staticmethod
    def _conversation_key(turn_context: TurnContext) -> str:
        activity = turn_context.activity
        tenant_id = TeamsPersonalChatBot._tenant_id(activity.channel_data)
        conversation_id = getattr(activity.conversation, "id", None) or "unknown-conversation"
        user_id = TeamsPersonalChatBot._user_id(turn_context)
        return f"{tenant_id}:{conversation_id}:{user_id}"

    @staticmethod
    def _tenant_id(channel_data: Any) -> str:
        if isinstance(channel_data, dict):
            tenant = channel_data.get("tenant") or {}
            if isinstance(tenant, dict) and tenant.get("id"):
                return str(tenant["id"])
        return "unknown-tenant"

    @staticmethod
    def _user_id(turn_context: TurnContext) -> str:
        from_account = turn_context.activity.from_property
        aad_object_id = getattr(from_account, "aad_object_id", None)
        if aad_object_id:
            return str(aad_object_id)
        user_id = getattr(from_account, "id", None)
        return str(user_id or "anonymous")

    @staticmethod
    def _help_text() -> str:
        return (
            "Ask a question about the company documents and I will answer using the available knowledge base. "
            "Send `clear` to reset this chat history."
        )

