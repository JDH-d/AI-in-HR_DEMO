"""Literal Block Kit primitives, surface limits, action identifiers, and date formatting."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

ASK_QUESTION = "ask_question"


OPEN_CHAT = "open_slack_chat"


OPEN_SLACK_CONVERSATION = "open_slack_conversation"


NEW_PTO = "new_pto"


NEW_SICK_LEAVE = "new_sick_leave"


NEW_REQUEST = "new_request"


HOME_SECTION = "home_section"


SELECT_REQUEST = "select_request"


REQUEST_TYPE_SUBMIT = "request_type_submit"


SHOW_REQUESTS = "show_requests"


SHOW_CONVERSATIONS = "show_conversations"


SHOW_HOME = "show_home"


OPEN_REQUEST = "open_request"


EDIT_REQUEST = "edit_request"


CANCEL_REQUEST = "cancel_request"


OPEN_CONVERSATION = "open_conversation"


CONTINUE_CONVERSATION = "continue_conversation"


DELETE_CONVERSATION = "delete_conversation"


VIEW_SOURCES = "view_sources"


FEEDBACK_HELPFUL = "feedback_helpful"


FEEDBACK_UNHELPFUL = "feedback_unhelpful"


REQUEST_DETAIL_PAGE = "request_detail_page"


CONVERSATION_PAGE = "conversation_page"


REQUEST_SUBMIT = "request_submit"


QUESTION_SUBMIT = "question_submit"


FEEDBACK_SUBMIT = "feedback_submit"


REQUEST_DETAIL = "request_detail"


SOURCES = "sources"


CONVERSATION_DETAIL = "conversation_detail"


EMPLOYEE_HOME = "employee_home"


INPUT_ACTION = "value"


REQUEST_FIELD_CHANGED = "request_field_changed"


HOME_PAGE_SIZE = 8


CONVERSATION_PAGE_SIZE = 6


ACTIVITY_PAGE_SIZE = 8


SOURCE_LIMIT = 20


SOURCE_EXCERPT_LIMIT = 800


TEXT_LIMIT = 2800


ANSWER_TEXT_BLOCKS = 10


COMMENT_MAX_LENGTH = 2000


QUESTION_MAX_LENGTH = 3000


_TYPES = {"pto": "Vacation / PTO", "sick_leave": "Sick leave"}


_STATUSES = {
    "draft": "Draft",
    "in_review": "In review",
    "reported": "Reported",
    "acknowledged": "Acknowledged",
    "approved": "Approved",
    "declined": "Declined",
    "cancelled": "Cancelled",
}


_NAV_ACTIONS = {
    "overview": SHOW_HOME,
    "requests": SHOW_REQUESTS,
    "conversations": SHOW_CONVERSATIONS,
}


def _string(value: object) -> str:
    return "" if value is None else str(value)


def _clipped(value: object, limit: int) -> str:
    """Escape before counting; never split a Slack entity at a text boundary."""
    parts = []
    size = 0
    raw = _string(value)
    for char in raw:
        token = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}.get(char, char)
        if size + len(token) > limit:
            while parts and size + 1 > limit:
                size -= len(parts.pop())
            return "".join(parts) + "…"
        parts.append(token)
        size += len(token)
    return "".join(parts) or "—"


def _plain(value: object, limit: int = TEXT_LIMIT) -> dict:
    return {"type": "plain_text", "text": _clipped(value, limit), "emoji": False}


def _section(value: object) -> dict:
    raw = _string(value)
    if "\n" in raw or "\r" in raw:
        return _rich_text(raw)
    return {"type": "section", "text": _plain(value)}


def _rich_text(value: str) -> dict:
    """Literal text nodes cannot create mentions, links, or Markdown formatting."""
    raw = value.replace("\r\n", "\n").replace("\r", "\n")
    clipped = raw if len(raw) <= TEXT_LIMIT else raw[: TEXT_LIMIT - 1] + "…"
    return {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_section",
                "elements": [{"type": "text", "text": clipped or "—"}],
            }
        ],
    }


def _context(value: object) -> dict:
    return {"type": "context", "elements": [_plain(value)]}


def _header(value: object) -> dict:
    return {"type": "header", "text": _plain(value, 150)}


def _json(value: dict, limit: int = 3000) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > limit:
        raise ValueError("Slack metadata/value is too long; keep identifiers opaque and short.")
    return encoded


def _button(label: str, action: str, value: str | None = None, **kwargs: object) -> dict:
    button = {"type": "button", "text": _plain(label, 75), "action_id": action, **kwargs}
    if value is not None:
        if not isinstance(value, str) or not value or len(value) > 2000:
            raise ValueError("Slack button values must be nonempty strings of at most 2000 chars.")
        button["value"] = value
    return button


def _url_button(label: str, action: str, url: object, **kwargs: object) -> dict | None:
    if (
        not isinstance(url, str)
        or len(url) > 3000
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url)
    ):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme == "slack":
            if parsed.netloc != "app" or parsed.path or "#" in url:
                return None
            params = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
            if set(params) != {"team", "id", "tab"} or any(
                len(values) != 1 for values in params.values()
            ):
                return None
            if (
                not re.fullmatch(r"T[A-Z0-9]+", params["team"][0])
                or not re.fullmatch(r"A[A-Z0-9]+", params["id"][0])
                or params["tab"] != ["messages"]
            ):
                return None
        elif parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
    except ValueError:
        return None
    return _button(label, action, url=url, **kwargs)


def _actions(*buttons: dict) -> dict:
    return {"type": "actions", "elements": list(buttons)}


def _confirm(title: str, text: str, confirm: str) -> dict:
    return {
        "title": _plain(title, 100),
        "text": _plain(text, 300),
        "confirm": _plain(confirm, 30),
        "deny": _plain("Keep it", 30),
        "style": "danger",
    }


def _modal(title: str, callback: str, blocks: list, metadata: dict | None = None) -> dict:
    return {
        "type": "modal",
        "callback_id": callback,
        "title": _plain(title, 24),
        "close": _plain("Close", 24),
        "private_metadata": _json(metadata or {}),
        "blocks": blocks,
    }


def _page(items: list, page: object, size: int) -> tuple[list, int, int]:
    try:
        number = int(page)
    except (TypeError, ValueError, OverflowError):
        number = 0
    pages = max(1, (len(items) + size - 1) // size)
    number = min(max(0, number), pages - 1)
    return items[number * size : (number + 1) * size], number, pages


def _pagination(page: int, pages: int, action: str, metadata: dict) -> list:
    if pages <= 1:
        return []
    blocks = [_context(f"Page {page + 1} of {pages}")]
    # action_id must be unique inside each containing block.
    for label, target in (("Previous", page - 1), ("Next", page + 1)):
        if 0 <= target < pages:
            value = (
                str(target)
                if action in _NAV_ACTIONS.values()
                else _json({**metadata, "page": target}, 2000)
            )
            blocks.append(_actions(_button(label, action, value)))
    return blocks


def _text_sections(value: object, max_blocks: int, notice: str) -> list:
    raw = _string(value) or "No text was saved for this message."
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    budget = max_blocks * TEXT_LIMIT
    blocks = [
        _rich_text(raw[offset : offset + TEXT_LIMIT])
        for offset in range(0, min(len(raw), budget), TEXT_LIMIT)
    ]
    if len(raw) > budget:
        blocks.append(_context(notice))
    return blocks


def _iso(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _date_label(value: object) -> str:
    iso = _iso(value)
    if not iso:
        return _string(value) or "Not set"
    parsed = date.fromisoformat(iso)
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{months[parsed.month - 1]} {parsed.day}, {parsed.year}"


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _date_range(start: object, end: object) -> str:
    if not start and not end:
        return "Choose dates"
    if not end:
        return f"From {_date_label(start)} · Choose last day"
    if not start:
        return f"Until {_date_label(end)} · Choose first day"
    first, last = _iso(start), _iso(end)
    if first and last:
        if first == last:
            return _date_label(first)
        if first[:7] == last[:7]:
            label = _date_label(first)
            return f"{label.split(',')[0]}–{int(last[-2:])}, {first[:4]}"
    return f"{_date_label(start)} – {_date_label(end)}"


def _timestamp_label(value: object) -> str:
    """Readable UTC activity time; naive API timestamps are treated as UTC."""
    raw = _string(value)
    if "T" not in raw and " " not in raw:
        return raw
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        utc = parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return raw
    hour = utc.hour % 12 or 12
    period = "AM" if utc.hour < 12 else "PM"
    return f"{_date_label(utc.date().isoformat())} · {hour}:{utc.minute:02d} {period} UTC"


def _input(
    name: str,
    label: str,
    element: dict,
    optional: bool = False,
    hint: str = "",
    *,
    dynamic: bool = False,
) -> dict:
    block = {
        "type": "input",
        "block_id": name,
        "label": _plain(label, 2000),
        "element": {**element, "action_id": REQUEST_FIELD_CHANGED if dynamic else INPUT_ACTION},
        "optional": optional,
    }
    if hint:
        block["hint"] = _plain(hint, 2000)
    if dynamic:
        block["dispatch_action"] = True
    return block


def _option(label: str, value: str) -> dict:
    if not isinstance(value, str) or not value or len(value) > 150:
        raise ValueError("Slack option values must be nonempty strings of at most 150 chars.")
    return {"text": _plain(label, 75), "value": value}


def _select(options: dict[str, str], initial: object) -> dict:
    values = [_option(label, value) for value, label in options.items()]
    element = {"type": "static_select", "options": values}
    if initial in options:
        element["initial_option"] = next(option for option in values if option["value"] == initial)
    return element


def _datepicker(initial: object) -> dict:
    element = {"type": "datepicker", "placeholder": _plain("Choose a date", 150)}
    if _iso(initial):
        element["initial_date"] = _iso(initial)
    return element


def _checkbox(label: str, selected: bool) -> dict:
    option = _option(label, "true")
    element = {"type": "checkboxes", "options": [option]}
    if selected:
        element["initial_options"] = [option]
    return element


def _text_input(initial: object = "", limit: int = COMMENT_MAX_LENGTH) -> dict:
    element = {"type": "plain_text_input", "multiline": True, "max_length": limit}
    if initial:
        # Input values are editable data, not composition text; do not HTML-escape.
        value = _string(initial)
        if len(value) > limit:
            raise ValueError("Draft text exceeds the input limit; do not silently discard edits.")
        element["initial_value"] = value
    return element
