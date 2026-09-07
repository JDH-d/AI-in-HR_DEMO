"""Reconcile backend request changes with Slack receipts and durable delivery."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from slack_sdk.errors import SlackApiError

from . import views
from .client import APIError

if TYPE_CHECKING:
    from .application import EmployeeApp

log = logging.getLogger(__name__)

# These messages cannot become editable on a later retry. Keep syncing other receipts.
UNEDITABLE_MESSAGE_ERRORS = {
    "message_not_found",
    "channel_not_found",
    "edit_window_closed",
    "cant_update_message",
}


class RequestNotifications:
    def __init__(self, app: EmployeeApp):
        self.app = app

    def flush_deliveries(self):
        app = self.app
        for item in app.store.deliveries():
            try:
                app.update(item["channel"], item["ts"], item["text"], item["blocks"])
                app.store.delivered(item["channel"], item["ts"])
            except SlackApiError as exc:
                if exc.response.get("error") in UNEDITABLE_MESSAGE_ERRORS:
                    app.store.delivered(item["channel"], item["ts"])
                else:
                    log.warning("Message update still waiting for Slack.")
            except Exception:
                log.warning("Message update still waiting for Slack.")

    def upgrade_messages(self):
        """Quietly refresh our saved messages once; never recreate missing Slack history."""
        app = self.app
        if app.store.get("presentation_version", 0) >= 2:
            return
        for answer_id, answer in app.store.saved_answers():
            checkpoint = "presentation_v2:" + answer_id
            if app.store.get(checkpoint, False):
                continue
            request = answer.get("workflow_request")
            if answer.get("request_id"):
                try:
                    request = app.api.request(answer["request_id"])["request"]
                except APIError as exc:
                    if exc.status != 404:
                        raise
                    request = None
            try:
                text = views.workflow_answer_text(request) if request else answer["answer"]
                app.update(
                    answer["channel"],
                    answer["ts"],
                    text,
                    views.answer_blocks(
                        text,
                        answer.get("sources"),
                        request,
                        question=answer.get("question_context", ""),
                    ),
                )
            except SlackApiError as exc:
                if exc.response.get("error") not in UNEDITABLE_MESSAGE_ERRORS:
                    raise
            app.store.set(checkpoint, True)
        for request in app.api.requests():
            app.refresh_cards(request)
        app.store.set("presentation_version", 2)

    def refresh_cards(self, request):
        app = self.app
        for card in app.store.cards(request["id"]):
            answer = app.store.answer(card["answer_id"]) if card["answer_id"] else None
            blocks = (
                views.answer_blocks(
                    views.workflow_answer_text(request),
                    answer["sources"],
                    request,
                    feedback_saved=(app.store.operation("feedback:" + card["answer_id"]) or {}).get(
                        "state"
                    )
                    == "complete",
                    question=answer.get("question_context", ""),
                )
                if answer
                else views.request_blocks(request)
            )
            try:
                app.update(
                    card["channel"],
                    card["ts"],
                    f"{request['type_label']}: {request['status']}",
                    blocks,
                )
                app.store.delivered(card["channel"], card["ts"])
            except SlackApiError as exc:
                if exc.response.get("error") in UNEDITABLE_MESSAGE_ERRORS:
                    app.store.remove_card(card["channel"], card["ts"])
                    app.store.delivered(card["channel"], card["ts"])
                else:
                    raise

    def poll_once(self):
        app = self.app
        with app.lock:
            app.flush_deliveries()
            initialized = app.store.get("initialized", False)
            requests = app.api.requests()
            changed = False
            for request in requests:
                detail = app.api.request(request["id"])
                request = detail["request"]
                old = app.store.snapshot(request["id"])
                if old == detail:
                    continue
                changed = True
                notification = None
                kind = None
                previous_status = (old or {}).get("request", {}).get("status")
                if request["status"] in {"in_review", "reported"}:
                    if previous_status != request["status"] and not app.store.cards(request["id"]):
                        kind = "receipt"
                elif request["status"] in {"approved", "declined", "acknowledged", "cancelled"}:
                    if previous_status != request["status"]:
                        kind = "status"
                if request["status"] == "cancelled" and app.store.get(
                    "local_cancel:" + request["id"], False
                ):
                    kind = None
                # A new manager note is useful; other metadata edits need no extra DM.
                old_comment_ids = {item.get("id") for item in (old or {}).get("comments", [])}
                new_comments = [
                    item
                    for item in detail.get("comments", [])
                    if item.get("id") not in old_comment_ids
                ]
                if not kind and old and new_comments:
                    kind = "comment"
                if initialized and request["status"] != "draft" and kind:
                    events = detail.get("events", [])
                    last_id = events[-1].get("id", "") if events else ""
                    digest = hashlib.sha256(
                        json.dumps(detail, sort_keys=True).encode()
                    ).hexdigest()[:20]
                    key = f"{request['id']}:{last_id}:{digest}"
                    notification = (
                        key,
                        {
                            "request_id": request["id"],
                            "detail": detail,
                            "kind": kind,
                            "new_comments": new_comments,
                        },
                    )
                app.refresh_cards(request)
                app.store.remember_request(detail, notification)
            app.store.set("initialized", True)
            for notice in app.store.pending_notifications():
                detail = notice["detail"]
                kind = notice.get("kind", "status")
                if kind == "receipt":
                    request_id = detail["request"]["id"]
                    if app.store.cards(request_id):
                        app.store.notification_state(notice["id"], "superseded")
                        continue
                    # A queued receipt is current state, unlike a dated decision notice.
                    detail = app.store.snapshot(request_id) or detail
                request = detail["request"]
                # Notifications are a dated event; only receipts are live request cards.
                visible_detail = {
                    **detail,
                    "comments": notice.get("new_comments", detail.get("comments", [])),
                }
                blocks = views.notification_blocks(visible_detail, kind=kind)
                # Opening the DM cannot have sent a notification. Leave it pending if this fails.
                channel = app.dm()
                # Save 'sending' first. On an ambiguous transport error do not risk duplicate DMs.
                app.store.notification_state(notice["id"], "sending")
                try:
                    sent = app.post("Request update: " + request["status"], blocks, channel)
                except SlackApiError:
                    app.store.notification_state(notice["id"], "pending")
                    raise
                except Exception:
                    app.store.notification_state(notice["id"], "uncertain")
                    log.error(
                        "Notification delivery unconfirmed; current state remains available in Home."
                    )
                    continue
                if kind == "receipt":
                    app.store.track_card(request["id"], sent["channel"], sent["ts"])
                app.store.notification_state(notice["id"], "sent")
            if changed and initialized:
                app.home()
