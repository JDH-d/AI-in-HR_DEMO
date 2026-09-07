"""Employee request summaries, details, status messages, and native request forms."""

from __future__ import annotations

from datetime import date, timedelta

from . import primitives
from .primitives import (
    _STATUSES,
    _TYPES,
    ACTIVITY_PAGE_SIZE,
    CANCEL_REQUEST,
    EDIT_REQUEST,
    OPEN_REQUEST,
    REQUEST_DETAIL,
    REQUEST_DETAIL_PAGE,
    REQUEST_SUBMIT,
    REQUEST_TYPE_SUBMIT,
    _actions,
    _button,
    _checkbox,
    _confirm,
    _context,
    _date_label,
    _date_range,
    _datepicker,
    _header,
    _input,
    _iso,
    _modal,
    _option,
    _page,
    _pagination,
    _plain,
    _section,
    _select,
    _string,
    _text_input,
    _timestamp_label,
)


def _details(request: dict) -> dict:
    value = request.get("details")
    return value if isinstance(value, dict) else {}


def _return_date(request: dict) -> str | None:
    details = _details(request)
    if details.get("expected_return_unknown") is True:
        return None
    if "expected_return_date" in details:
        return _string(details["expected_return_date"]) or None
    # Match requestPresentation.ts for legacy API records without explicit return.
    end = _iso(request.get("end_date"))
    if end:
        try:
            return (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        except OverflowError:
            pass
    return None


def _request_dates(request: dict) -> str:
    if request.get("type") != "sick_leave":
        return _date_range(request.get("start_date"), request.get("end_date"))
    details = _details(request)
    back = (
        "Return date unknown"
        if details.get("expected_return_unknown") is True
        else f"Back {_date_label(_return_date(request))}"
    )
    duration = ""
    if details.get("time_away") == "partial_day":
        hours = details.get("partial_hours")
        duration = f" · {hours} hours" if hours not in (None, "") else " · Part of day"
    return f"{_date_label(request.get('start_date'))}{duration} · {back}"


def _request_summary(request: dict, include_action: bool = False) -> dict:
    kind = request.get("type")
    label = _TYPES.get(kind, "Request")
    status = _STATUSES.get(request.get("status"), "Status unavailable")
    summary = {
        "type": "section",
        # Both tokens are from fixed UI dictionaries, never raw API labels.
        "text": {"type": "mrkdwn", "text": f"*{label}* · {status}", "verbatim": True},
    }
    identity = request.get("id")
    if include_action and identity:
        if kind in _TYPES and request.get("status") == "draft":
            summary["accessory"] = _button(
                "Finish request", EDIT_REQUEST, identity, style="primary"
            )
        else:
            summary["accessory"] = _button("Details", OPEN_REQUEST, identity)
    return summary


def _request_actions(request: dict) -> list:
    identity = request.get("id")
    if not identity:
        return []
    buttons = []
    kind, status = request.get("type"), request.get("status")
    if kind in _TYPES and status == "draft":
        buttons.append(_button("Finish request", EDIT_REQUEST, identity, style="primary"))
    cancellable = (kind == "pto" and status in {"draft", "in_review"}) or (
        kind == "sick_leave" and status in {"draft", "reported"}
    )
    if cancellable:
        buttons.append(
            _button(
                "Cancel request",
                CANCEL_REQUEST,
                identity,
                confirm=_confirm(
                    "Cancel this request?",
                    "This will cancel this request in PeopleFlow. It stays in your request history. "
                    "You can create a new request if your plans change.",
                    "Cancel request",
                ),
                style="danger",
            )
        )
    return [_actions(*buttons)] if buttons else []


def request_blocks(request: dict, include_actions: bool = False, *, show_hint: bool = True) -> list:
    """Read-only chat summary; callers may explicitly opt into a detail action."""
    blocks = [
        _request_summary(request, include_action=include_actions),
        _context(" ".join(_request_dates(request).split())),
    ]
    if show_hint and not include_actions and request.get("status") == "draft":
        blocks.append(_context("Not sent yet. Open Home → My requests to review and send."))
    return blocks


def _decision_note(detail: dict) -> str:
    request = detail.get("request") or {}
    return next(
        (
            _details(event).get("comment")
            for event in reversed(detail.get("events") or [])
            if event.get("to_status") == request.get("status") and _details(event).get("comment")
        ),
        "",
    )


def notification_blocks(detail: dict, *, kind: str = "status") -> list:
    """Compact API detail notification. kind: receipt, status or comment."""
    request = detail.get("request") or {}
    if kind == "receipt":
        return request_blocks(request)
    if kind not in {"status", "comment"}:
        raise ValueError("Notification kind must be receipt, status or comment.")
    comments = detail.get("comments") or []
    latest_comment = comments[-1].get("body") if comments else ""
    if kind == "comment":
        phrase = "New comment on your request."
        note = latest_comment
    else:
        phrase = {
            "draft": "Your request is saved as a draft.",
            "in_review": "Your time off is in review.",
            "approved": "Your time off was approved.",
            "declined": "Your request was declined.",
            "cancelled": "Your request was cancelled.",
            "reported": "Your sick leave was reported.",
            "acknowledged": "Your sick leave was acknowledged.",
        }.get(request.get("status"), "Your request was updated.")
        note = _decision_note(detail)
    blocks = [_section(phrase), _context(" ".join(_request_dates(request).split()))]
    notes = [note] if note else []
    if (
        kind == "status"
        and latest_comment
        and _string(latest_comment).strip() != _string(note).strip()
    ):
        notes.append(latest_comment)
    for note in notes:
        raw = _string(note)
        blocks.append(_section(raw if len(raw) <= 800 else raw[:799] + "…"))
    return blocks


def request_detail_view(detail: dict) -> dict:
    request = detail.get("request") or {}
    events, comments = detail.get("events") or [], detail.get("comments") or []
    blocks = request_blocks(request, include_actions=False, show_hint=False)
    sick = request.get("type") == "sick_leave"
    if request.get("comment"):
        blocks.append(_section(f"{'Team note' if sick else 'Planning note'}\n{request['comment']}"))
    if request.get("status") == "draft" and request.get("validation_errors"):
        blocks.append(
            _section("Before you submit\n" + "\n".join(map(_string, request["validation_errors"])))
        )
    if sick and _details(request).get("extended_or_recurring") is True:
        blocks.append(
            _context(
                "People Ops follow-up flagged. This demo records the flag only; no message is sent to People Ops."
            )
        )
    decision = _decision_note(detail)
    if decision:
        label = {
            "declined": "Reason for decline",
            "acknowledged": "Acknowledgement note",
        }.get(request.get("status"), "Decision note")
        blocks.append(_section(f"{label}\n{decision}"))
    blocks.extend(_request_actions(request))
    blocks.append(_header("Activity"))
    activity = [("event", event) for event in events] + [("comment", note) for note in comments]
    visible, page, pages = _page(activity, detail.get("page", 0), ACTIVITY_PAGE_SIZE)
    for kind, item in visible:
        if kind == "comment":
            text = f"Comment · {item.get('author') or 'Unknown author'}\n{item.get('body') or ''}"
        else:
            label = _STATUSES.get(item.get("to_status"), "Request updated")
            if item.get("to_status") == "reported":
                label = "Sick leave reported"
            elif item.get("to_status") == "acknowledged":
                label = "Manager acknowledged"
            text = f"{label} · {item.get('actor') or 'PeopleFlow'}"
            if _details(item).get("comment"):
                text += f"\n{_details(item)['comment']}"
        if item.get("created_at"):
            text += f"\n{_timestamp_label(item['created_at'])}"
        blocks.append(_section(text))
    if not activity:
        blocks.append(_section("No activity yet."))
    identity = request.get("id")
    if identity:
        blocks.extend(_pagination(page, pages, REQUEST_DETAIL_PAGE, {"request_id": identity}))
    return _modal("Request details", REQUEST_DETAIL, blocks, {"request_id": identity, "page": page})


def request_type_view() -> dict:
    """One entry point for vacation and sick leave using a native Slack picker."""
    options = [
        {
            **_option("Time off", "pto"),
            "description": _plain("Plan vacation or personal time away.", 75),
        },
        {
            **_option("Sick leave", "sick_leave"),
            "description": _plain("Let your manager know you’re unwell.", 75),
        },
    ]
    view = _modal(
        "New request",
        REQUEST_TYPE_SUBMIT,
        [
            _input(
                "request_type", "What do you need?", {"type": "radio_buttons", "options": options}
            ),
            _context("Choose a type, then review the details before anything is sent."),
        ],
    )
    view["submit"] = _plain("Continue", 24)
    view["close"] = _plain("Cancel", 24)
    return view


def request_form(request_type: str = "pto", draft: dict | None = None) -> dict:
    """Fixed-type form; draft.state_values preserves hidden values across rebuilds."""
    draft = draft if draft is not None else {}
    request_type = draft.get("type", request_type)
    if request_type not in _TYPES:
        raise ValueError("Only employee PTO and sick leave forms are supported.")
    sick = request_type == "sick_leave"
    details = _details(draft)
    new = not draft.get("id")
    # Presence, not truthiness, distinguishes a cleared field from a new default.
    expected = (
        details["expected_return_date"]
        if "expected_return_date" in details
        else _return_date({**draft, "details": {**details, "expected_return_unknown": False}})
    )
    state = {
        "start_date": draft.get("start_date", primitives._today_iso() if sick and new else None),
        "end_date": draft.get("end_date"),
        "comment": draft.get("comment"),
        "expected_return_date": expected,
        "expected_return_unknown": details.get(
            "expected_return_unknown", sick and new and not expected
        ),
        "time_away": details.get("time_away", "full_day"),
        "partial_hours": details.get("partial_hours"),
        "extended_or_recurring": details.get("extended_or_recurring", False),
    }
    saved = draft.get("state_values")
    if isinstance(saved, dict):
        state.update({name: saved[name] for name in state if name in saved})
    metadata = {
        "request_type": request_type,
        # The always-visible note comes from view.state.values. Keeping it out of
        # metadata avoids JSON expansion exceeding 3000 chars; never truncate it.
        "state_values": {name: value for name, value in state.items() if name != "comment"},
    }
    if draft.get("id"):
        metadata["draft_id"] = draft["id"]
    blocks = [
        _input(
            "start_date",
            "First day away" if sick else "First day",
            _datepicker(state["start_date"]),
        )
    ]
    if sick:
        blocks.append(
            _input(
                "time_away",
                "Time away",
                _select({"full_day": "Full day", "partial_day": "Part of day"}, state["time_away"]),
                dynamic=True,
            )
        )
        if state["time_away"] == "partial_day":
            hours = {
                "type": "number_input",
                "is_decimal_allowed": True,
                "max_value": "24",
                "min_value": "0",
                "placeholder": _plain("For example: 4", 150),
            }
            if state["partial_hours"] not in (None, ""):
                hours["initial_value"] = _string(state["partial_hours"])
            blocks.append(
                _input(
                    "partial_hours",
                    "Approximate hours",
                    hours,
                    hint="Greater than 0 and up to 24 hours.",
                )
            )
        blocks.append(
            _input(
                "expected_return_unknown",
                "Expected return",
                _checkbox("Return date unknown", state["expected_return_unknown"] is True),
                optional=True,
                dynamic=True,
            )
        )
        if state["expected_return_unknown"] is not True:
            blocks.append(
                _input(
                    "expected_return_date",
                    "Expected back",
                    _datepicker(state["expected_return_date"]),
                )
            )
    else:
        blocks.append(
            _input(
                "end_date",
                "Last day",
                _datepicker(state["end_date"]),
                hint="The last calendar day of your time off.",
            )
        )
    blocks.append(
        _input(
            "comment",
            "Team note" if sick else "Planning note",
            _text_input(state["comment"]),
            optional=sick,
            hint="Availability or handoff context."
            if sick
            else "Timing or handoff context is enough.",
        )
    )
    if sick and state["extended_or_recurring"] is True:
        blocks.append(
            _input(
                "extended_or_recurring",
                "People Ops follow-up",
                _checkbox("This may be extended or recurring", True),
                optional=True,
                hint="This demo records a follow-up flag only. No message is sent to People Ops.",
            )
        )
    blocks.append(
        _context(
            "Goes to your manager for acknowledgement." if sick else "Next step: manager review."
        )
    )
    view = _modal(
        "Report sick leave" if sick else "Request time off", REQUEST_SUBMIT, blocks, metadata
    )
    view.update(
        {
            "submit": _plain("Report absence" if sick else "Send for review", 24),
            "close": _plain("Cancel", 24),
        }
    )
    return view


def workflow_answer_text(request):
    """A live receipt describes its current state, including after manager updates."""
    status = request.get("status")
    sick = request.get("type") == "sick_leave"
    if status == "draft":
        if request.get("validation_errors"):
            return "I’ve started your draft. Add the missing details before sending."
        return (
            "Your absence draft is ready. Review your availability before reporting it."
            if sick
            else "Your time-off draft is ready. Review the dates and note before sending."
        )
    return {
        "in_review": "Your request is with your manager. I’ll keep you updated here.",
        "reported": "Your absence has been reported. Your manager has your availability update.",
        "approved": "Your time off is approved.",
        "acknowledged": "Your manager has acknowledged your absence report.",
        "declined": "Your time-off request was declined. You can review the decision in My requests.",
        "cancelled": "This request has been cancelled.",
    }.get(status, "Here is the latest status of your request.")
