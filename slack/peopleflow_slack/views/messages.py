"""Chat answers, source excerpts, saved conversations, and focused message modals."""

from __future__ import annotations

from .primitives import (
    ANSWER_TEXT_BLOCKS,
    CONTINUE_CONVERSATION,
    CONVERSATION_DETAIL,
    CONVERSATION_PAGE,
    CONVERSATION_PAGE_SIZE,
    DELETE_CONVERSATION,
    FEEDBACK_SUBMIT,
    OPEN_REQUEST,
    OPEN_SLACK_CONVERSATION,
    QUESTION_MAX_LENGTH,
    QUESTION_SUBMIT,
    SOURCE_EXCERPT_LIMIT,
    SOURCE_LIMIT,
    SOURCES,
    VIEW_SOURCES,
    _actions,
    _button,
    _confirm,
    _context,
    _header,
    _input,
    _modal,
    _page,
    _pagination,
    _plain,
    _section,
    _string,
    _text_input,
    _text_sections,
    _timestamp_label,
    _url_button,
)
from .requests import (
    request_blocks,
)


def _conversation_actions(conversation: dict) -> list:
    identity = conversation.get("id")
    if not identity:
        return []
    return [
        _actions(
            _url_button(
                "Open in Slack",
                OPEN_SLACK_CONVERSATION,
                conversation.get("slack_url"),
                style="primary",
            )
            or _button("Continue conversation", CONTINUE_CONVERSATION, identity, style="primary"),
            _button(
                "Delete chat",
                DELETE_CONVERSATION,
                identity,
                style="danger",
                confirm=_confirm(
                    "Delete this chat?",
                    "Delete this conversation and its messages from your PeopleFlow history? "
                    "This cannot be undone. Existing Slack messages will remain. "
                    "Your requests will stay in PeopleFlow.",
                    "Delete chat",
                ),
            ),
        )
    ]


def answer_blocks(
    text: str,
    sources: list | None = None,
    request: dict | None = None,
    *,
    feedback_saved: bool = False,
    question: str = "",
) -> list:
    """Quiet, literal answer text with compact source titles and no controls."""
    blocks = []
    if question:
        question_context = " ".join(question.split())
        blocks.append(
            {"type": "context", "elements": [_plain(f"You asked: {question_context}", 400)]}
        )
    blocks.extend(
        _text_sections(
            text or "No answer was returned. Please try your question again.",
            ANSWER_TEXT_BLOCKS,
            "This answer is shortened for Slack. You can read the full answer in PeopleFlow.",
        )
    )
    if request:
        blocks.extend([{"type": "divider"}, *request_blocks(request)])
    titles = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        title = " ".join(
            _string(source.get("title") or source.get("source") or "Company policy").split()
        )
        if title not in titles:
            titles.append(title)
    if titles:
        summary = " · ".join(
            title if len(title) <= 150 else title[:149] + "…" for title in titles[:3]
        )
        if len(titles) > 3:
            summary += f" · +{len(titles) - 3} more"
        blocks.append({"type": "context", "elements": [_plain(f"Sources: {summary}", 600)]})
    if feedback_saved:
        blocks.append(_context("Feedback saved"))
    return blocks


def sources_view(sources: list) -> dict:
    blocks = []
    for source in sources[:SOURCE_LIMIT]:
        blocks.append(_header(source.get("title") or source.get("source") or "Untitled source"))
        labels = (
            ("Section", "section"),
            ("Version", "version"),
        )
        context = " · ".join(f"{label}: {source[key]}" for label, key in labels if source.get(key))
        if context:
            blocks.append(_context(context))
        raw = _string(source.get("excerpt") or "No excerpt is available.")
        excerpt = raw if len(raw) <= SOURCE_EXCERPT_LIMIT else raw[: SOURCE_EXCERPT_LIMIT - 1] + "…"
        blocks.append(_section(excerpt))
    if not sources:
        blocks.append(_section("No sources were attached to this answer."))
    elif len(sources) > SOURCE_LIMIT:
        blocks.append(
            _context(
                f"Showing {SOURCE_LIMIT} of {len(sources)} sources. See the full answer in PeopleFlow."
            )
        )
    return _modal("Answer sources", SOURCES, blocks)


def question_view() -> dict:
    view = _modal(
        "Ask PeopleFlow",
        QUESTION_SUBMIT,
        [
            _section("Ask about company policies, time off or sick leave."),
            _input(
                "question",
                "Your question",
                _text_input(limit=QUESTION_MAX_LENGTH),
                hint="Your answer appears in Messages. You can keep chatting there.",
            ),
        ],
    )
    view["submit"] = _plain("Ask question", 24)
    return view


def feedback_view(answer_id: str) -> dict:
    if not isinstance(answer_id, str) or not answer_id:
        raise ValueError("Feedback must be bound to an answer_id.")
    view = _modal(
        "Improve this answer",
        FEEDBACK_SUBMIT,
        [
            _input(
                "comment",
                "What should we improve?",
                _text_input(),
                optional=True,
                hint="Missing context, incorrect policy, unclear wording…",
            ),
        ],
        {"answer_id": answer_id},
    )
    view["submit"] = _plain("Send feedback", 24)
    return view


def conversation_view(detail: dict) -> dict:
    conversation = detail.get("conversation") or {}
    messages = detail.get("messages") or []
    visible, page, pages = _page(messages, detail.get("page", 0), CONVERSATION_PAGE_SIZE)
    blocks = [
        _section(conversation.get("title") or "Untitled chat"),
        _context("Your saved PeopleFlow conversation."),
    ]
    if not messages:
        blocks.append(_section("No messages yet. Continue this chat to ask a question."))
    for message in visible:
        role = "You" if message.get("role") == "user" else "PeopleFlow AI"
        blocks.append(_header(role))
        if message.get("created_at"):
            blocks.append(_context(_timestamp_label(message["created_at"])))
        blocks.extend(
            _text_sections(
                message.get("content"),
                3,
                "This message is shortened for Slack. Read the full message in PeopleFlow.",
            )
        )
        if message.get("role") == "assistant":
            identity = message.get("id")
            if identity and message.get("sources"):
                blocks.append(_actions(_button("View sources", VIEW_SOURCES, identity)))
            workflow = message.get("workflow") or message.get("workflow_request")
            if isinstance(workflow, dict) and workflow.get("id"):
                # Link to current API state instead of presenting a historical status as current.
                blocks.append(_actions(_button("View request", OPEN_REQUEST, workflow["id"])))
    identity = conversation.get("id")
    if identity:
        blocks.extend(_pagination(page, pages, CONVERSATION_PAGE, {"conversation_id": identity}))
        blocks.extend(_conversation_actions(conversation))
    return _modal(
        "Conversation", CONVERSATION_DETAIL, blocks, {"conversation_id": identity, "page": page}
    )


def help_blocks() -> list:
    return [
        _header("Just ask PeopleFlow"),
        _section(
            "Write here as you would in a conversation. Ask about a policy, "
            "say when you need time off, or let me know you’re unwell."
        ),
        _section(
            "“How much notice do I need for vacation?”\n"
            "“I need PTO from September 21–23.”\n"
            "“I’m sick today.”"
        ),
        _context(
            "Say “sources” for the references behind an answer. Use /peopleflow request to review a draft."
        ),
        _context("Home keeps your requests and saved conversations together."),
    ]


def loading_blocks(text: str = "Finding the context for your question…") -> list:
    return [_context(text)]


def state_blocks(text: str) -> list:
    return [_section(text)]


def error_blocks(text: str = "PeopleFlow is unavailable right now. Please try again.") -> list:
    """Pass a user-facing error message, never raw exceptions or credentials."""
    return [_section(text), _context("Your saved requests and chats are available in Home.")]


def text_blocks(text):
    """Bounded literal message content for loading, errors, and notices."""
    return [_section(text)]


def notice_view(title, text):
    """A read-only notice modal; status text uses the same safe primitives as answers."""
    return {
        "type": "modal",
        "title": _plain(title, 24),
        "close": _plain("Close", 24),
        "blocks": text_blocks(text),
    }
