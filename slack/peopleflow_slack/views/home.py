"""Conversation-first App Home and paginated employee history navigation."""

from __future__ import annotations

from . import primitives
from .primitives import (
    _NAV_ACTIONS,
    _STATUSES,
    _TYPES,
    ASK_QUESTION,
    EMPLOYEE_HOME,
    HOME_PAGE_SIZE,
    HOME_SECTION,
    NEW_REQUEST,
    OPEN_CHAT,
    OPEN_CONVERSATION,
    OPEN_SLACK_CONVERSATION,
    SELECT_REQUEST,
    _actions,
    _button,
    _context,
    _header,
    _iso,
    _json,
    _option,
    _page,
    _pagination,
    _plain,
    _section,
    _select,
    _string,
    _url_button,
)
from .requests import (
    _details,
    _request_dates,
    request_blocks,
)


def home_view(
    requests: list,
    conversations: list,
    section: str = "overview",
    page: int = 0,
    chat_url: str | None = None,
) -> dict:
    """Conversation-first Home with three overview controls and quiet request lists."""
    section = section if section in _NAV_ACTIONS else "overview"
    navigation = _select(
        {"overview": "Overview", "requests": "My requests", "conversations": "Conversations"},
        section,
    )
    navigation.update({"action_id": HOME_SECTION, "placeholder": _plain("Choose a view", 150)})
    blocks = [
        _header("Your HR, in Slack"),
        _section(
            "Ask in Messages about company policies, plan time off or report an absence. "
            "You can keep the conversation going there."
        ),
        _actions(
            _url_button("Open Messages", OPEN_CHAT, chat_url, style="primary")
            or _button("Ask a question", ASK_QUESTION, style="primary"),
            _button("New request", NEW_REQUEST),
        ),
        {"type": "divider"},
        {"type": "section", "text": _plain("Your workspace"), "accessory": navigation},
    ]
    active_page = 0
    if section == "overview":
        blocks.append(_header("My requests"))
        today = primitives._today_iso()
        priorities = {"draft": 0, "in_review": 1, "reported": 1, "approved": 2, "acknowledged": 2}
        active = []
        for record in requests:
            status = record.get("status")
            start = _iso(record.get("start_date"))
            end = _iso(record.get("end_date")) or start
            if status in {"draft", "in_review", "reported"}:
                active.append(record)
            elif (
                status in {"approved", "acknowledged"}
                and start
                and (
                    (end and end >= today)
                    or (
                        record.get("type") == "sick_leave"
                        and _details(record).get("expected_return_unknown") is True
                    )
                )
            ):
                active.append(record)
        active.sort(
            key=lambda item: (priorities[item["status"]], _iso(item.get("start_date")) or "")
        )
        if active:
            groups = (
                ("Drafts to finish", {"draft"}),
                ("Waiting for your manager", {"in_review", "reported"}),
                ("Active & upcoming", {"approved", "acknowledged"}),
            )
            for label, statuses in groups:
                records = [record for record in active[:3] if record.get("status") in statuses]
                if records:
                    lines = [
                        f"{_TYPES.get(record.get('type'), 'Request')} · {_request_dates(record)}"
                        for record in records
                    ]
                    blocks.append(_section(f"{label}\n" + "\n".join(lines)))
            remaining = len(active) - 3
            blocks.append(
                _context(
                    (f"{remaining} more active requests. " if remaining > 0 else "")
                    + "Choose My requests above to finish a draft or see details."
                )
            )
        else:
            blocks.append(
                _section("No active or upcoming requests.\nNeed time away? Just ask in Messages.")
            )
    else:
        blocks.append(_header("My requests" if section == "requests" else "Conversations"))
        records = requests if section == "requests" else conversations
        visible, active_page, pages = _page(records, page, HOME_PAGE_SIZE)
        if not visible:
            blocks.append(
                _section("No requests yet." if section == "requests" else "No conversations yet.")
            )
        for record in visible:
            if section == "requests":
                label = _TYPES.get(record.get("type"), "Request")
                status = _STATUSES.get(record.get("status"), "Status unavailable")
                identity = record.get("id")
                if identity and (not isinstance(identity, str) or len(identity) > 150):
                    # Preserve opaque IDs that cannot fit a static-select value.
                    blocks.extend(request_blocks(record, include_actions=True))
                else:
                    blocks.append(_section(f"{label} · {status}\n{_request_dates(record)}"))
            else:
                row = _section(
                    " ".join(_string(record.get("title") or "Untitled conversation").split())
                )
                if record.get("id"):
                    row["accessory"] = _url_button(
                        "Open conversation", OPEN_SLACK_CONVERSATION, record.get("slack_url")
                    ) or _button("Open conversation", OPEN_CONVERSATION, record["id"])
                blocks.append(row)
        if section == "requests":
            selectable = [
                record
                for record in visible
                if isinstance(record.get("id"), str) and 0 < len(record["id"]) <= 150
            ]
            if selectable:
                options = []
                for record in selectable:
                    option = _option(
                        f"{_TYPES.get(record.get('type'), 'Request')} · {_request_dates(record)}",
                        record["id"],
                    )
                    option["description"] = _plain(
                        _STATUSES.get(record.get("status"), "Status unavailable"), 75
                    )
                    options.append(option)
                blocks.append(
                    _actions(
                        {
                            "type": "static_select",
                            "action_id": SELECT_REQUEST,
                            "placeholder": _plain("Open a request…", 150),
                            "options": options,
                        }
                    )
                )
        blocks.extend(_pagination(active_page, pages, _NAV_ACTIONS[section], {"section": section}))
    return {
        "type": "home",
        "callback_id": EMPLOYEE_HOME,
        "blocks": blocks,
        "private_metadata": _json({"section": section, "page": active_page}),
    }
