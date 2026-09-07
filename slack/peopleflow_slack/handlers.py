"""Slack event routing and prompt acknowledgements; backend work runs on the shared worker."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from slack_bolt import App
from slack_sdk.errors import SlackApiError

from . import views
from .forms import field_value, merge_request_form_state, request_payload
from .inbox import DurableInbox

if TYPE_CHECKING:
    from .application import EmployeeApp


def create_bolt_app(service: EmployeeApp, *, verify=True) -> App:
    app = App(client=service.slack, token_verification_enabled=verify)
    app.use(DurableInbox(service))

    @app.event("app_home_opened")
    def on_home(body):
        if service.allowed(body) and body["event"].get("tab") == "home":
            service.queue(service.home, "overview")
            service.queue(service.upgrade_messages)

    @app.event("message")
    def on_message(body):
        event = body["event"]
        if (
            not service.allowed(body)
            or event.get("bot_id")
            or event.get("subtype") not in {None, "file_share"}
            or event.get("channel_type") != "im"
        ):
            return
        if event.get("files"):
            service.queue(
                service.post,
                "Please send your question as text. File uploads are not read by PeopleFlow in Slack.",
                None,
                event["channel"],
                event.get("thread_ts") or event["ts"],
            )
            return
        text = (event.get("text") or "").strip()
        if text:
            service.queue(
                service.ask,
                text,
                event["channel"],
                event.get("thread_ts") or event["ts"],
                body["event_id"],
                not bool(event.get("thread_ts")),
            )

    @app.shortcut("ask_peopleflow")
    def on_shortcut(ack, body):
        ack()
        if service.allowed(body):
            service.slack.views_open(trigger_id=body["trigger_id"], view=views.question_view())

    @app.command("/peopleflow")
    def on_command(ack, body):
        ack()
        if not service.allowed(body):
            return
        text = (body.get("text") or "").strip()
        if text.lower() in {"", "new"}:
            service.slack.views_open(trigger_id=body["trigger_id"], view=views.question_view())
        elif text.lower() in {"home", "requests", "help"}:
            service.queue(service.home, "requests" if text.lower() == "requests" else "overview")
            service.queue(
                service.post, "Open PeopleFlow’s Home tab for your workspace.", views.help_blocks()
            )
        elif text.lower() == "request":
            view_id = service.open_loading(body["trigger_id"], "Your request")
            service.queue(service.request_entry, view_id)
        elif text.lower() == "sources":
            service.queue(service.ask_new, "sources", "command:" + body["trigger_id"])
        else:
            service.queue(service.ask_new, text, "command:" + body["trigger_id"])

    @app.action(re.compile(".*"))
    def on_action(ack, body):
        ack()
        if not service.allowed(body):
            return
        action = body["actions"][0]
        kind, value = action["action_id"], action.get("value", "")
        if kind in {"home_section", "select_request"}:
            value = (action.get("selected_option") or {}).get("value", "")
        operation_id = f"action:{kind}:{action.get('action_ts', body.get('trigger_id', ''))}"
        if kind == "new_request":
            service.slack.views_open(trigger_id=body["trigger_id"], view=views.request_type_view())
        elif kind == "home_section":
            if value in {"overview", "requests", "conversations"}:
                service.queue(service.home, value, 0)
        elif kind == "select_request":
            if value:
                view_id = service.open_loading(body["trigger_id"], "Your request")
                service.queue(service.show_detail, view_id, "edit_request", value)
        elif kind in {"ask_question", "new_pto", "new_sick_leave"}:
            view = (
                views.question_view()
                if kind == "ask_question"
                else views.request_form("pto" if kind == "new_pto" else "sick_leave")
            )
            service.slack.views_open(trigger_id=body["trigger_id"], view=view)
        elif kind in {"show_home", "show_requests", "show_conversations"}:
            section = {
                "show_home": "overview",
                "show_requests": "requests",
                "show_conversations": "conversations",
            }[kind]
            try:
                navigation = (
                    json.loads(value) if value.startswith("{") else {"page": int(value or 0)}
                )
                page = int(navigation.get("page", 0))
            except (ValueError, TypeError):
                page = 0
            service.queue(service.home, section, page)
        elif kind in {"request_detail_page", "conversation_page"}:
            navigation = json.loads(value)
            is_request = kind == "request_detail_page"
            resource = navigation["request_id" if is_request else "conversation_id"]
            service.queue(
                service.show_detail,
                body["view"]["id"],
                "open_request" if is_request else "open_conversation",
                resource,
                int(navigation.get("page", 0)),
            )
        elif kind == "request_field_changed":
            current = body.get("view", {})
            if current.get("callback_id") != "request_submit" or action.get("block_id") not in {
                "time_away",
                "expected_return_unknown",
            }:
                return
            metadata = json.loads(current.get("private_metadata") or "{}")
            request_type = metadata.get("request_type", "sick_leave")
            values = dict(current.get("state", {}).get("values", {}))
            values[action["block_id"]] = {kind: action}
            draft = merge_request_form_state(values, request_type, metadata)
            try:
                service.slack.views_update(
                    view_id=current["id"],
                    hash=current.get("hash"),
                    view=views.request_form(request_type, draft),
                )
            except SlackApiError as exc:
                if exc.response.get("error") != "hash_conflict":
                    raise
        elif kind == "value" and action.get("block_id") == "type":
            current = body["view"]
            metadata = json.loads(current.get("private_metadata") or "{}")
            values = current.get("state", {}).get("values", {})
            draft = merge_request_form_state(values, action["selected_option"]["value"], metadata)
            service.slack.views_update(
                view_id=current["id"],
                hash=current.get("hash"),
                view=views.request_form(draft["type"], draft),
            )
        elif kind in {"open_request", "edit_request", "open_conversation"}:
            if body.get("view", {}).get("type") == "modal":
                view_id = body["view"]["id"]
                service.slack.views_update(
                    view_id=view_id, view=views.notice_view("PeopleFlow", "Loading…")
                )
            else:
                view_id = service.open_loading(body["trigger_id"])
            service.queue(service.show_detail, view_id, kind, value)
        elif kind == "view_sources":
            view = views.notice_view("Sources", "Loading…")
            if body.get("view", {}).get("type") == "modal":
                opened = service.slack.views_push(trigger_id=body["trigger_id"], view=view)
            else:
                opened = service.slack.views_open(trigger_id=body["trigger_id"], view=view)
            service.queue(service.show_sources, opened["view"]["id"], value)
        elif kind == "feedback_unhelpful":
            service.slack.views_open(trigger_id=body["trigger_id"], view=views.feedback_view(value))
        elif kind == "feedback_helpful":
            service.queue(service.rate, value, 5)
        elif kind == "cancel_request":
            modal_id = (
                body.get("view", {}).get("id")
                if body.get("view", {}).get("type") == "modal"
                else None
            )
            service.queue(service.cancel, value, operation_id, modal_id)
        elif kind == "continue_conversation":
            view = views.question_view()
            view["private_metadata"] = json.dumps({"conversation_id": value})
            view["title"]["text"] = "Continue conversation"
            if body.get("view", {}).get("type") == "modal":
                service.slack.views_update(view_id=body["view"]["id"], view=view)
            else:
                service.slack.views_open(trigger_id=body["trigger_id"], view=view)
        elif kind == "delete_conversation":
            modal_id = (
                body.get("view", {}).get("id")
                if body.get("view", {}).get("type") == "modal"
                else None
            )
            service.queue(service.delete, value, operation_id, modal_id)

    @app.view(re.compile(".*"))
    def on_view(ack, body):
        if not service.allowed(body):
            ack(response_action="clear")
            return
        view = body["view"]
        callback = view["callback_id"]
        values = view.get("state", {}).get("values", {})
        try:
            metadata = json.loads(view.get("private_metadata") or "{}")
        except ValueError:
            metadata = {}
        if callback == "request_type_submit":
            request_type = field_value(values, "request_type")
            if request_type not in {"pto", "sick_leave"}:
                ack(response_action="errors", errors={"request_type": "Choose a request type."})
                return
            ack(response_action="update", view=views.request_form(request_type))
        elif callback == "request_submit":
            request_type = metadata.get("request_type", "pto")
            payload, errors = request_payload(values, request_type)
            if errors:
                ack(response_action="errors", errors=errors)
                return
            ack(
                response_action="update",
                view=views.notice_view(
                    "Sending your request",
                    "Saving your request… You can close this window; the result will appear in My requests.",
                ),
            )
            service.queue(
                service.submit_request,
                view["id"],
                payload,
                metadata.get("draft_id"),
                "submit:" + view["id"],
            )
        elif callback == "question_submit":
            text = (field_value(values, "question") or "").strip()
            if not text:
                ack(response_action="errors", errors={"question": "Enter a question."})
                return
            ack()
            service.queue(
                service.ask_new, text, "question:" + view["id"], metadata.get("conversation_id")
            )
        elif callback == "feedback_submit":
            ack()
            answer_id = metadata.get("answer_id", "")
            service.queue(
                service.rate, answer_id, 1, (field_value(values, "comment") or "").strip()
            )
        else:
            ack()

    return app
