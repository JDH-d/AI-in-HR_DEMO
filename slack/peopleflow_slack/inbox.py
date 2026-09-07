"""Persist accepted employee actions before ACK; recover only unstarted work.

Slack envelopes, tokens, response URLs, view blocks and authorization data are
never stored. Pending rows retain only the arguments needed by the existing
controller; their contents are cleared when the action reaches a terminal state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from slack_bolt.middleware import Middleware
from slack_bolt.response import BoltResponse

from .forms import field_value, request_payload

log = logging.getLogger(__name__)


class InvalidAction(ValueError):
    pass


def _text(value, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise InvalidAction("Invalid action field.")
    return value


def _optional_id(value):
    return None if value is None else _text(value)


def _object(value):
    if not isinstance(value, dict):
        raise InvalidAction("Invalid action object.")
    return value


@dataclass(frozen=True)
class IncomingAction:
    receipt_id: str
    operation_id: str
    kind: str
    payload: dict


def normalize_action(body, service):
    """Mirror mutation routing and operation IDs, without retaining a Slack body."""
    body = _object(body)
    if not service.allowed(body):
        return None
    scope = {"team_id": service.settings.team_id, "user_id": service.settings.employee_user_id}

    def action(kind, operation_id, payload, receipt_id=None):
        return IncomingAction(receipt_id or operation_id, operation_id, kind, {**scope, **payload})

    if body.get("type") == "event_callback":
        event = _object(body.get("event"))
        if (
            event.get("type") != "message"
            or event.get("channel_type") != "im"
            or event.get("bot_id")
            or event.get("subtype")
            or event.get("files")
        ):
            return None
        text = _text(event.get("text", ""), empty=True).strip()
        if not text:
            return None
        return action(
            "ask",
            _text(body.get("event_id")),
            {
                "text": text,
                "channel": _text(event.get("channel")),
                "thread_ts": _text(event.get("thread_ts") or event.get("ts")),
                "new_message": not bool(event.get("thread_ts")),
            },
        )

    if body.get("command") == "/peopleflow":
        text = _text(body.get("text", ""), empty=True).strip()
        if text.lower() in {"", "new", "home", "requests", "request", "help"}:
            return None
        # The trigger is only the existing controller's operation identifier;
        # recovery does not use it to open an expired modal.
        return action(
            "ask_new",
            "command:" + _text(body.get("trigger_id")),
            {
                "text": text,
                "conversation_id": None,
            },
        )

    if body.get("type") == "block_actions":
        items = body.get("actions")
        if not isinstance(items, list) or not items:
            raise InvalidAction("Invalid action list.")
        item = _object(items[0])
        kind = item.get("action_id")
        if kind not in {"feedback_helpful", "cancel_request", "delete_conversation"}:
            return None
        value = _text(item.get("value"))
        nonce = _text(item.get("action_ts", body.get("trigger_id", "")))
        receipt_id = f"action:{kind}:{nonce}"
        if kind == "feedback_helpful":
            return action(
                "rate",
                "feedback:" + value,
                {
                    "answer_id": value,
                    "rating": 5,
                    "comment": "",
                },
                receipt_id,
            )
        view = _object(body.get("view", {}))
        view_id = _optional_id(view.get("id")) if view.get("type") == "modal" else None
        if kind == "cancel_request":
            return action("cancel", receipt_id, {"request_id": value, "view_id": view_id})
        return action("delete", receipt_id, {"conversation_id": value, "view_id": view_id})

    if body.get("type") != "view_submission":
        return None
    view = _object(body.get("view"))
    callback = view.get("callback_id")
    if callback not in {"request_submit", "question_submit", "feedback_submit"}:
        return None
    view_id = _text(view.get("id"))
    values = _object(_object(view.get("state", {})).get("values", {}))
    try:
        metadata = json.loads(view.get("private_metadata") or "{}")
    except ValueError:
        # Dropping corrupt metadata would lose draft_id and turn an edit into a new request.
        raise InvalidAction("Invalid action metadata.") from None
    metadata = _object(metadata)
    if callback == "request_submit":
        payload, errors = request_payload(values, metadata.get("request_type", "pto"))
        if errors:
            return None  # The existing listener returns inline form errors.
        return action(
            "submit_request",
            "submit:" + view_id,
            {
                "view_id": view_id,
                "fields": payload,
                "draft_id": _optional_id(metadata.get("draft_id")),
            },
        )
    if callback == "question_submit":
        text = _text(field_value(values, "question") or "", empty=True).strip()
        if not text:
            return None
        return action(
            "ask_new",
            "question:" + view_id,
            {
                "text": text,
                "conversation_id": _optional_id(metadata.get("conversation_id")),
            },
        )
    answer_id = _text(metadata.get("answer_id"))
    return action(
        "rate",
        "feedback:" + answer_id,
        {
            "answer_id": answer_id,
            "rating": 1,
            "comment": _text(field_value(values, "comment") or "", empty=True).strip(),
        },
        "feedback-view:" + view_id,
    )


class DurableInbox(Middleware):
    def __init__(self, service):
        self.service = service

    def process(self, *, req, resp, next):
        try:
            action = normalize_action(req.body, self.service)
            if action is not None:
                self.service.store.receive_inbox(
                    action.receipt_id, action.operation_id, action.kind, action.payload
                )
        except (InvalidAction, TypeError, KeyError, AttributeError, ValueError):
            return BoltResponse(status=400, body="")
        except Exception:
            # Returning non-200 keeps Socket Mode from acknowledging this envelope.
            # Never allow Bolt's default exception logger to stringify the body.
            log.error("Incoming action could not be saved; its delivery was not acknowledged.")
            return BoltResponse(status=503, body="")
        # Keep normal listener ACKs (including form updates). The store's claim
        # gate deduplicates mutations even when Slack delivers the envelope twice.
        return next()


def _replay_arguments(item, service):
    payload = _object(item["payload"])
    if (
        payload.get("team_id") != service.settings.team_id
        or payload.get("user_id") != service.settings.employee_user_id
    ):
        raise InvalidAction("Saved action belongs to another employee installation.")
    operation_id = _text(item["operation_id"])
    kind = item["kind"]
    if kind == "ask":
        return service.ask, (
            _text(payload.get("text")),
            _text(payload.get("channel")),
            _optional_id(payload.get("thread_ts")),
            operation_id,
            payload.get("new_message", False) is True,
        )
    if kind == "ask_new":
        return service.ask_new, (
            _text(payload.get("text")),
            operation_id,
            _optional_id(payload.get("conversation_id")),
        )
    if kind == "submit_request":
        fields = _object(payload.get("fields"))
        if fields.get("type") not in {"pto", "sick_leave"}:
            raise InvalidAction("Invalid request type.")
        return service.submit_request, (
            _text(payload.get("view_id")),
            fields,
            _optional_id(payload.get("draft_id")),
            operation_id,
        )
    if kind == "rate":
        rating = payload.get("rating")
        if type(rating) is not int or rating not in {1, 5}:
            raise InvalidAction("Invalid feedback rating.")
        return service.rate, (
            _text(payload.get("answer_id")),
            rating,
            _text(payload.get("comment"), empty=True),
        )
    if kind == "cancel":
        return service.cancel, (
            _text(payload.get("request_id")),
            operation_id,
            _optional_id(payload.get("view_id")),
        )
    if kind == "delete":
        return service.delete, (
            _text(payload.get("conversation_id")),
            operation_id,
            _optional_id(payload.get("view_id")),
        )
    raise InvalidAction("Unknown saved action.")


def recover_inbox(service):
    """Run once under the process lock, before Socket Mode or polling starts."""
    pending = service.store.recover_inbox()
    for item in pending:
        try:
            function, args = _replay_arguments(item, service)
        except (InvalidAction, TypeError, KeyError, AttributeError, ValueError):
            service.store.settle_inbox(item["id"], uncertain=True)
            log.warning("A saved action could not be recovered safely; it was not repeated.")
            continue
        # Use the same sequential worker as live listeners. No new scheduler or
        # re-dispatch of expired Slack triggers is involved.
        service.queue(function, *args).result()
        service.store.settle_inbox(item["id"])
