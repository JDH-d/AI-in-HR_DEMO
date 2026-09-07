"""Slack conversation delivery over the shared PeopleFlow chat API."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from . import views
from .client import APIError

if TYPE_CHECKING:
    from .application import EmployeeApp

log = logging.getLogger(__name__)


def chat_command(text: str) -> str | None:
    normalized = " ".join(text.casefold().split()).strip(".!? ")
    if normalized in {"new chat", "new conversation", "start over"}:
        return "new"
    if normalized in {"sources", "show sources", "where is this from", "source"}:
        return "sources"
    return None


class ConversationController:
    def __init__(self, app: EmployeeApp):
        self.app = app

    def saved_answer(self, answer_id):
        """A Slack cache must not revive history deleted from the backend."""
        app = self.app
        answer = app.store.answer(answer_id) if answer_id else None
        conversation_id = (answer or {}).get("conversation_id")
        if conversation_id:
            try:
                app.api.conversation(conversation_id)
            except APIError as exc:
                if exc.status != 404:
                    raise
                app.store.forget_conversation(conversation_id)
                return None
        return answer

    def ask(self, text, channel, thread_ts, event_id, new_message=False, conversation_id=None):
        app = self.app
        if not app.store.claim(event_id):
            return
        if not text.strip() or len(text) > 3000:
            app.post(
                "Please send a text question of up to 3,000 characters.",
                channel=channel,
                thread_ts=None if new_message else thread_ts,
            )
            app.store.finish(event_id, "failed")
            return
        existing = app.store.thread(channel, thread_ts) if thread_ts else None
        if existing and existing["deleted"]:
            app.post(
                "This conversation was deleted from PeopleFlow. Send a new message to start again.",
                channel=channel,
                thread_ts=thread_ts,
            )
            app.store.finish(event_id)
            return
        command = chat_command(text)
        if command == "new":
            if new_message:
                app.store.set("active_conversation:" + channel, None)
                app.store.set("latest_answer:" + channel, None)
            elif thread_ts:
                app.store.bind(channel, thread_ts, None)
                app.store.set("latest_answer:" + f"{channel}:{thread_ts}", None)
            app.post(
                "Ready for a new conversation. What can I help with?",
                channel=channel,
                thread_ts=None if new_message else thread_ts,
            )
            app.store.finish(event_id)
            return
        if command == "sources":
            key = channel if new_message else f"{channel}:{thread_ts}"
            answer_id = app.store.get("latest_answer:" + key)
            try:
                answer = self.saved_answer(answer_id)
            except APIError as exc:
                app.store.finish(event_id, "failed")
                app.post(
                    app.error_text(exc),
                    channel=channel,
                    thread_ts=None if new_message else thread_ts,
                )
                return
            sources = (answer or {}).get("sources") or []
            if sources:
                blocks = views.sources_view(sources[:8])["blocks"]
                if len(sources) > 8:
                    blocks += views.text_blocks(
                        "Showing the first 8 sources. The full answer is saved in PeopleFlow."
                    )
                sent = app.post(
                    "Sources for my last answer",
                    blocks,
                    channel,
                    None if new_message else thread_ts,
                )
                conversation = answer.get("conversation_id")
                if conversation:
                    app.store.bind(channel, sent["ts"], conversation)
                    app.store.set("latest_answer:" + f"{channel}:{sent['ts']}", answer_id)
                    if thread_ts:
                        app.store.bind(channel, thread_ts, conversation)
                        app.store.set("latest_answer:" + f"{channel}:{thread_ts}", answer_id)
            else:
                app.post(
                    "There are no saved sources for the last answer in this conversation. "
                    "Ask a company-policy question and I’ll include its sources.",
                    channel=channel,
                    thread_ts=None if new_message else thread_ts,
                )
            app.store.finish(event_id)
            return
        placeholder = app.post(
            "Thinking…",
            views.text_blocks("Thinking…"),
            channel,
            None if new_message else thread_ts,
        )
        response_ts = placeholder["ts"]
        content, complete, last_update = "", None, time.monotonic()
        try:
            conversation_id = existing["conversation_id"] if existing else conversation_id
            if new_message and not conversation_id:
                conversation_id = app.store.get("active_conversation:" + channel)
            for event in app.api.stream_chat(text, conversation_id):
                if event["type"] == "token":
                    content += event["content"]
                elif event["type"] == "replace":
                    content = event["content"]
                elif event["type"] == "complete":
                    complete = event
                elif event["type"] == "error":
                    message = event["message"]
                    missing = message == "The conversation could not be found."
                    raise APIError(404 if missing else 502, message, uncertain=not missing)
                if event["type"] in {"token", "replace"} and time.monotonic() - last_update >= 1.5:
                    try:
                        app.update(
                            channel,
                            response_ts,
                            content,
                            views.text_blocks(content or "Preparing your answer…"),
                        )
                    except Exception:
                        pass  # A failed preview must not interrupt/persist a partial API exchange.
                    last_update = time.monotonic()
            if complete is None:
                raise APIError(503, "The answer was not confirmed.", uncertain=True)
            request = complete.get("workflow_request")
            if request:
                content = views.workflow_answer_text(request)
            root_ts = response_ts if new_message else thread_ts
            if thread_ts:
                app.store.bind(channel, thread_ts, complete["conversation_id"])
            if new_message:
                app.store.bind(channel, response_ts, complete["conversation_id"])
                app.store.set("active_conversation:" + channel, complete["conversation_id"])
            if request:
                app.store.set(
                    "request_for_conversation:" + complete["conversation_id"], request["id"]
                )
            if not app.store.get("conversation_entry:" + complete["conversation_id"]):
                app.store.set(
                    "conversation_entry:" + complete["conversation_id"],
                    {"channel": channel, "ts": root_ts},
                )
            answer_id = app.store.save_answer(
                {
                    "question": text,
                    "answer": content,
                    "sources": complete.get("sources") or [],
                    "conversation_id": complete["conversation_id"],
                    "channel": channel,
                    "ts": response_ts,
                    "thread_ts": root_ts,
                    "request_id": (complete.get("workflow_request") or {}).get("id"),
                    "workflow_request": complete.get("workflow_request"),
                    "question_context": text if thread_ts is None else "",
                }
            )
            app.store.set("latest_answer:" + f"{channel}:{root_ts}", answer_id)
            if thread_ts:
                app.store.set("latest_answer:" + f"{channel}:{thread_ts}", answer_id)
            if new_message:
                app.store.set("latest_answer:" + channel, answer_id)
            request = complete.get("workflow_request")
            if request:
                app.store.track_card(request["id"], channel, response_ts, answer_id)
            # Persistence is complete before attempting the final Slack render.
            app.store.finish(event_id, payload={"answer_id": answer_id})
            app.update_durable(
                channel,
                response_ts,
                content,
                views.answer_blocks(
                    content,
                    complete.get("sources") or [],
                    request,
                    question=text if thread_ts is None else "",
                ),
            )
            app.home()
        except APIError as exc:
            if exc.status == 404 and conversation_id:
                app.store.forget_conversation(conversation_id)
            app.store.finish(
                event_id, "uncertain" if getattr(exc, "uncertain", False) else "failed"
            )
            app.update_durable(
                channel, response_ts, app.error_text(exc), views.text_blocks(app.error_text(exc))
            )
        except Exception:
            log.error(
                "Slack could not render a completed answer; conversation is retained in PeopleFlow."
            )
            raise

    def ask_new(self, text, operation_id, conversation_id=None):
        # Claim the entry point before creating a root message; ask owns its backend sub-operation.
        app = self.app
        if not app.store.claim(operation_id):
            return
        try:
            if conversation_id:
                app.api.conversation(conversation_id)
            elif chat_command(text) != "sources":
                app.store.set("active_conversation:" + app.dm(), None)
                app.store.set("latest_answer:" + app.dm(), None)
            app.ask(text, app.dm(), None, operation_id + ":chat", True, conversation_id)
        except APIError as exc:
            app.store.finish(operation_id, "uncertain" if exc.uncertain else "failed")
            app.post(app.error_text(exc))
            return
        app.store.finish(operation_id)

    def rate(self, answer_id, rating, comment=""):
        app = self.app
        operation_id = "feedback:" + answer_id
        answer = self.saved_answer(answer_id)
        if not answer or not app.store.claim(operation_id, retry_failed=True):
            return
        try:
            app.api.feedback(answer["question"], answer["answer"], rating, comment)
            app.store.finish(operation_id)
            if answer.get("ts"):
                request = None
                if answer.get("request_id"):
                    snapshot = app.store.snapshot(answer["request_id"])
                    request = snapshot["request"] if snapshot else answer.get("workflow_request")
                app.update_durable(
                    answer["channel"],
                    answer["ts"],
                    views.workflow_answer_text(request) if request else answer["answer"],
                    views.answer_blocks(
                        views.workflow_answer_text(request) if request else answer["answer"],
                        answer["sources"],
                        request,
                        feedback_saved=True,
                        question=answer.get("question_context", ""),
                    ),
                )
        except APIError as exc:
            app.store.finish(
                operation_id, "uncertain" if getattr(exc, "uncertain", False) else "failed"
            )
            app.post(app.error_text(exc), channel=answer["channel"], thread_ts=answer["thread_ts"])

    def delete(self, conversation_id, operation_id, view_id=None):
        app = self.app
        if not app.store.claim(operation_id):
            return
        try:
            app.api.delete_conversation(conversation_id)
        except APIError as exc:
            app.store.finish(operation_id, "uncertain" if exc.uncertain else "failed")
            app.post(app.error_text(exc))
            return
        app.store.forget_conversation(conversation_id)
        channel = app.store.get("dm")
        if channel and app.store.get("active_conversation:" + channel) == conversation_id:
            app.store.set("active_conversation:" + channel, None)
            app.store.set("latest_answer:" + channel, None)
        app.store.finish(operation_id)
        if view_id:
            try:
                app.slack.views_update(
                    view_id=view_id,
                    view=views.notice_view(
                        "Conversation deleted",
                        "Conversation deleted from PeopleFlow. Its Slack messages and your requests remain.",
                    ),
                )
            except Exception:
                log.warning(
                    "Conversation deleted; its closed or unavailable modal could not refresh."
                )
        app.home("conversations")
        app.post(
            "Conversation deleted from PeopleFlow. Its Slack messages and your requests remain."
        )
