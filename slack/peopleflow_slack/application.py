"""Employee interface composition, modal navigation and backend request actions.

ConversationController owns chat delivery, RequestNotifications owns synchronization,
and handlers.py owns Slack event routing. All backend access goes through PeopleFlowClient.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock, Thread

from slack_sdk import WebClient

from . import views
from .chat import ConversationController
from .client import APIError, PeopleFlowClient
from .config import Settings
from .notifications import RequestNotifications
from .store import Store

log = logging.getLogger(__name__)


class EmployeeApp:
    def __init__(self, settings: Settings, api: PeopleFlowClient, store: Store, slack: WebClient):
        self.settings, self.api, self.store, self.slack = settings, api, store, slack
        # One employee / one sequenced worker keeps chat, delete, and form actions ordered.
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="peopleflow-actions")
        self.lock = RLock()
        self.stop_event = Event()
        self.poll_thread = None
        self.chat = ConversationController(self)
        self.notifications = RequestNotifications(self)

    def allowed(self, body):
        user = body.get("user") or body.get("user_id") or body.get("event", {}).get("user")
        user_id = user.get("id") if isinstance(user, dict) else user
        team = body.get("team") or body.get("team_id")
        team_id = team.get("id") if isinstance(team, dict) else team
        return user_id == self.settings.employee_user_id and team_id == self.settings.team_id

    def queue(self, function, *args):
        def run():
            try:
                with self.lock:
                    function(*args)
            except Exception as exc:
                # Never log Slack payloads, questions, access tokens, or response bodies.
                log.error("Background action failed: %s", type(exc).__name__)
                if isinstance(exc, APIError):
                    try:
                        self.post(self.error_text(exc))
                    except Exception:
                        log.error("Could not deliver the action error to Slack.")

        return self.worker.submit(run)

    def dm(self):
        cached = self.store.get("dm")
        if cached:
            return cached
        result = self.slack.conversations_open(users=self.settings.employee_user_id)
        channel = result["channel"]["id"]
        self.store.set("dm", channel)
        return channel

    def post(self, text, blocks=None, channel=None, thread_ts=None):
        args = {
            "channel": channel or self.dm(),
            "text": text[:3900],
            "unfurl_links": False,
            "unfurl_media": False,
            "parse": "none",
            "mrkdwn": False,
        }
        if blocks is not None:
            args["blocks"] = blocks
        if thread_ts:
            args["thread_ts"] = thread_ts
        return self.slack.chat_postMessage(**args)

    def update(self, channel, ts, text, blocks):
        return self.slack.chat_update(
            channel=channel, ts=ts, text=text[:3900], blocks=blocks, parse="none"
        )

    def update_durable(self, channel, ts, text, blocks):
        self.store.save_delivery(channel, ts, text, blocks)
        try:
            self.update(channel, ts, text, blocks)
        except Exception:
            log.warning("Message update queued for delivery; backend action will not be repeated.")
            return
        self.store.delivered(channel, ts)

    def flush_deliveries(self):
        return self.notifications.flush_deliveries()

    def home(self, section=None, page=None):
        navigation = self.store.get("home_navigation", {"section": "overview", "page": 0})
        if section is not None and page is None:
            page = 0
        section = section or navigation["section"]
        page = navigation["page"] if page is None else page
        self.store.set("home_navigation", {"section": section, "page": page})
        try:
            requests = self.api.requests()
            conversations = self.api.conversations()
            if section == "conversations":
                conversations = [
                    {**item, "slack_url": self.conversation_link(item["id"])}
                    for item in conversations
                ]
            chat_url = (
                f"slack://app?team={self.settings.team_id}&id={self.settings.app_id}&tab=messages"
                if self.settings.app_id
                else None
            )
            view = views.home_view(
                requests, conversations, section=section, page=page, chat_url=chat_url
            )
        except APIError:
            view = {
                "type": "home",
                "blocks": views.text_blocks(
                    "PeopleFlow is temporarily unavailable. Your saved conversations and requests are kept. Try Refresh shortly."
                )
                + [
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "action_id": "show_home",
                                "text": {"type": "plain_text", "text": "Refresh"},
                            }
                        ],
                    }
                ],
            }
        self.slack.views_publish(user_id=self.settings.employee_user_id, view=view)

    def upgrade_messages(self):
        return self.notifications.upgrade_messages()

    def conversation_link(self, conversation_id):
        key = "conversation_link:" + conversation_id
        cached = self.store.get(key)
        if cached:
            return cached
        entry = self.store.get("conversation_entry:" + conversation_id)
        if not entry:
            entry = self.store.conversation_thread(conversation_id)
        if not entry:
            return None
        try:
            result = self.slack.chat_getPermalink(channel=entry["channel"], message_ts=entry["ts"])
            url = result.get("permalink")
            if isinstance(url, str) and url.startswith("https://"):
                self.store.set(key, url)
                return url
        except Exception:
            log.warning("Conversation link unavailable; saved history remains accessible.")
        return None

    def open_loading(self, trigger, title="PeopleFlow"):
        return self.slack.views_open(trigger_id=trigger, view=views.notice_view(title, "Loading…"))[
            "view"
        ]["id"]

    def show_sources(self, view_id, answer_id):
        try:
            answer = self.chat.saved_answer(answer_id)
            view = (
                views.sources_view(answer["sources"])
                if answer
                else views.notice_view(
                    "Sources unavailable",
                    "This answer is no longer saved. Start a new conversation to ask again.",
                )
            )
        except APIError as exc:
            view = views.notice_view("Unable to load", self.error_text(exc))
        self.slack.views_update(view_id=view_id, view=view)

    def show_detail(self, view_id, kind, value, page=0):
        try:
            if kind == "open_request":
                detail = self.api.request(value)
                detail["page"] = page
                view = views.request_detail_view(detail)
            elif kind == "edit_request":
                request = self.api.request(value)["request"]
                view = (
                    views.request_form(request["type"], request)
                    if request["status"] == "draft"
                    else views.request_detail_view(self.api.request(value))
                )
            elif kind == "open_conversation":
                detail = self.api.conversation(value)
                detail["conversation"]["slack_url"] = self.conversation_link(value)
                detail["page"] = page
                question = ""
                for message in detail.get("messages", []):
                    if message.get("role") == "user":
                        question = message["content"]
                    elif message.get("sources"):
                        source_key = f"history:{value}:{message['id']}"
                        self.store.save_answer(
                            {
                                "question": question,
                                "answer": message["content"],
                                "sources": message["sources"],
                                "conversation_id": value,
                            },
                            source_key,
                        )
                        message["id"] = source_key
                view = views.conversation_view(detail)
            else:
                raise ValueError("Unknown view")
        except APIError as exc:
            view = views.notice_view("Unable to load", self.error_text(exc))
        self.slack.views_update(view_id=view_id, view=view)

    @staticmethod
    def error_text(exc):
        if getattr(exc, "uncertain", False):
            return "The connection ended before PeopleFlow confirmed the result. Check My requests or Recent conversations before trying again; your action may already be saved."
        if getattr(exc, "status", None) == 404:
            return "This item is no longer available. Open your Home tab to refresh the list."
        if getattr(exc, "status", None) == 409:
            return "This request has already changed. Open My requests to see its current status."
        if getattr(exc, "status", None) in {400, 422}:
            return str(getattr(exc, "detail", "Check the form and try again."))[:1800]
        return "PeopleFlow is temporarily unavailable. Your saved data is kept. Please try again shortly."

    def ask(self, text, channel, thread_ts, event_id, new_message=False, conversation_id=None):
        return self.chat.ask(text, channel, thread_ts, event_id, new_message, conversation_id)

    def ask_new(self, text, operation_id, conversation_id=None):
        return self.chat.ask_new(text, operation_id, conversation_id)

    def request_entry(self, view_id):
        """Review the current chat's draft, or choose an absence type without losing a trigger."""
        try:
            answer_id = self.store.get("latest_answer:" + self.dm())
            answer = self.store.answer(answer_id) if answer_id else None
            request_id = (answer or {}).get("request_id")
            if not request_id:
                conversation_id = self.store.get("active_conversation:" + self.dm())
                if conversation_id:
                    request_id = self.store.get("request_for_conversation:" + conversation_id)
            if request_id:
                request = self.api.request(request_id)["request"]
                view = (
                    views.request_form(request["type"], request)
                    if request["status"] == "draft"
                    else views.request_detail_view(self.api.request(request_id))
                )
            else:
                view = views.request_type_view()
        except APIError as exc:
            view = views.notice_view("Unable to load", self.error_text(exc))
        self.slack.views_update(view_id=view_id, view=view)

    def submit_request(self, view_id, payload, draft_id, operation_id):
        if not self.store.claim(operation_id):
            return
        request_id = draft_id
        try:
            if not request_id:
                draft = self.api.create_request(payload)
                request_id = draft["id"]
                self.store.finish(operation_id, "draft_created", {"request_id": request_id})
            request = self.api.submit_request(request_id, payload)["request"]
            self.store.finish(operation_id, payload={"request_id": request_id})
        except APIError as exc:
            self.store.finish(
                operation_id,
                "uncertain" if getattr(exc, "uncertain", False) else "failed",
                {"request_id": request_id},
            )
            message = self.error_text(exc)
            if request_id:
                message += " Your draft is available in My requests."
            self.slack.views_update(
                view_id=view_id, view=views.notice_view("Check your request", message)
            )
            self.home("requests")
            return
        # Delivery is reconciled by polling even if this modal was closed by the employee.
        try:
            label = "Absence reported" if request["type"] == "sick_leave" else "Request submitted"
            self.slack.views_update(
                view_id=view_id,
                view=views.notice_view(
                    label,
                    "Your manager has your availability update. Track it in My requests."
                    if request["type"] == "sick_leave"
                    else "Your request is in review. You’ll receive an update here when your manager decides.",
                ),
            )
        except Exception:
            pass
        self.poll_once()
        self.home()

    def cancel(self, request_id, operation_id, view_id=None):
        if not self.store.claim(operation_id):
            return
        try:
            self.api.cancel_request(request_id)
        except APIError as exc:
            self.store.finish(operation_id, "uncertain" if exc.uncertain else "failed")
            if view_id:
                self.slack.views_update(
                    view_id=view_id,
                    view=views.notice_view("Check your request", self.error_text(exc)),
                )
            self.post(self.error_text(exc))
            return
        self.store.finish(operation_id)
        self.store.set("local_cancel:" + request_id, True)
        if view_id:
            try:
                self.show_detail(view_id, "open_request", request_id)
            except Exception:
                log.warning("Request cancelled; its closed or unavailable modal could not refresh.")
        self.poll_once()
        self.home()

    def rate(self, answer_id, rating, comment=""):
        return self.chat.rate(answer_id, rating, comment)

    def delete(self, conversation_id, operation_id, view_id=None):
        return self.chat.delete(conversation_id, operation_id, view_id)

    def refresh_cards(self, request):
        return self.notifications.refresh_cards(request)

    def poll_once(self):
        return self.notifications.poll_once()

    def start_polling(self):
        def poll():
            while not self.stop_event.wait(self.settings.poll_interval):
                try:
                    self.poll_once()
                except Exception as exc:
                    log.warning(
                        "Sync unavailable; retrying next interval (%s).", type(exc).__name__
                    )

        self.poll_thread = Thread(target=poll, daemon=True, name="peopleflow-sync")
        self.poll_thread.start()

    def close(self):
        self.stop_event.set()
        if self.poll_thread:
            self.poll_thread.join(timeout=self.settings.api_timeout + 5)
        self.worker.shutdown(wait=True)
        self.api.close()
