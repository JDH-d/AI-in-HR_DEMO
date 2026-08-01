from __future__ import annotations

import logging
from typing import Any

from api.schemas import ChatRequest, ChatResponse, Message

from .chat_service import ChatService

logger = logging.getLogger(__name__)

SLACK_HR_COMMAND = "/hr"
SLACK_HR_USAGE_MESSAGE = "Ask an HR question after /hr. Example: /hr When are salaries paid?"
SLACK_HR_ERROR_MESSAGE = "PeopleFlow could not answer that question right now. Please try again."


class SlackHRCommandService:
    """Translate a Slack slash command into the existing Web chat service."""

    def __init__(self, chat_service: ChatService) -> None:
        self.chat_service = chat_service

    def handle_command(self, ack, command: dict, respond, **_: Any) -> None:
        ack()
        question = str(command.get("text") or "").strip()
        if not question:
            respond(
                text=SLACK_HR_USAGE_MESSAGE,
                response_type="ephemeral",
            )
            return

        slack_user_id = str(command.get("user_id") or "unknown").strip() or "unknown"
        try:
            response = self.chat_service.handle_chat(
                ChatRequest(
                    messages=[Message(role="user", content=question)],
                ),
                created_by=f"slack:{slack_user_id}",
                allow_workflow=False,
            )
        except Exception as exc:
            logger.warning(
                "Slack HR command could not be answered (%s).",
                type(exc).__name__,
            )
            respond(
                text=SLACK_HR_ERROR_MESSAGE,
                response_type="ephemeral",
            )
            return

        respond(
            response_type="in_channel",
            **self._build_response(question, response),
        )

    @staticmethod
    def _build_response(question: str, response: ChatResponse) -> dict[str, Any]:
        answer = response.message.content.strip()
        escaped_question = SlackHRCommandService._escape_mrkdwn(question)
        quoted_question = escaped_question.replace("\n", "\n> ")
        source_groups = SlackHRCommandService._group_sources(response)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Question*\n> {quoted_question}",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Answer*\n{answer}",
                },
            },
        ]
        fallback_parts = [
            f"Question: {escaped_question}",
            f"Answer: {answer}",
        ]

        if source_groups:
            source_block_lines = ["*Sources*"]
            fallback_source_lines = ["Sources:"]
            for title, sections in source_groups:
                escaped_title = SlackHRCommandService._escape_mrkdwn(title)
                source_block_lines.append(f"*{escaped_title}*")
                fallback_source_lines.append(escaped_title)
                for section in sections:
                    escaped_section = SlackHRCommandService._escape_mrkdwn(section)
                    source_block_lines.append(f"• {escaped_section}")
                    fallback_source_lines.append(f"- {escaped_section}")
            blocks.extend(
                [
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "\n".join(source_block_lines),
                        },
                    },
                ]
            )
            fallback_parts.append("\n".join(fallback_source_lines))

        return {
            "text": "\n\n".join(fallback_parts),
            "blocks": blocks,
        }

    @staticmethod
    def _group_sources(response: ChatResponse) -> list[tuple[str, list[str]]]:
        grouped: dict[str, list[str]] = {}
        for source in response.sources or []:
            title = source.title.strip() or "Internal document"
            section = source.section.strip()
            sections = grouped.setdefault(title, [])
            if section and section not in sections:
                sections.append(section)
        return list(grouped.items())

    @staticmethod
    def _escape_mrkdwn(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
