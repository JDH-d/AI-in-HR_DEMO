"""Employee interactions, hostile content, and documented Slack surface limits."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from peopleflow_slack import views
from peopleflow_slack.views import primitives


@pytest.fixture(autouse=True)
def stable_today(monkeypatch):
    monkeypatch.setattr(primitives, "_today_iso", lambda: "2026-09-06")


def request(kind="pto", status="draft", **overrides):
    return {
        "id": "request-123",
        "type": kind,
        "type_label": "PTO" if kind == "pto" else "Sick leave",
        "status": status,
        "start_date": "2026-09-07",
        "end_date": "2026-09-09",
        "duration_days": 3,
        "comment": "I’ll hand over current work before I go.",
        "applicant": "employee",
        "approver": "manager",
        "details": {},
        **overrides,
    }


def conversation(**overrides):
    return {"id": "conversation-123", "title": "Vacation policy", "message_count": 2, **overrides}


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def buttons(value, action=None):
    return [
        item
        for item in walk(value)
        if item.get("type") == "button" and (action is None or item.get("action_id") == action)
    ]


def selections(value, action):
    return [
        item
        for item in walk(value)
        if item.get("type") == "static_select" and item.get("action_id") == action
    ]


def selected_values(value, action):
    return [option["value"] for menu in selections(value, action) for option in menu["options"]]


def texts(value):
    return "\n".join(
        item["text"] for item in walk(value) if item.get("type") in {"plain_text", "mrkdwn", "text"}
    )


def inputs(view):
    return {block["block_id"]: block for block in view["blocks"] if block["type"] == "input"}


def assert_slack_shape(value):
    """Independently enforce limits of the primitives used by these views."""
    blocks = value if isinstance(value, list) else value["blocks"]
    assert 0 < len(blocks) <= (50 if isinstance(value, list) else 100)
    ids = [block["block_id"] for block in blocks if "block_id" in block]
    assert len(ids) == len(set(ids))
    if isinstance(value, dict):
        assert len(value.get("private_metadata", "")) <= 3000
        json.loads(value["private_metadata"])
        assert len(value["callback_id"]) <= 255
        if value["type"] == "modal":
            for field in ("title", "close", "submit"):
                if field in value:
                    assert len(value[field]["text"]) <= 24
                    assert value[field]["type"] == "plain_text"
            if any(block["type"] == "input" for block in blocks):
                assert "submit" in value
    for item in walk(value):
        assert "color" not in item
        assert "unfurl_links" not in item
        assert "unfurl_media" not in item
        kind = item.get("type")
        if kind in {"plain_text", "mrkdwn"}:
            assert 0 < len(item["text"]) <= 3000
            assert "<" not in item["text"] and ">" not in item["text"]
            if kind == "mrkdwn":
                assert item["verbatim"] is True
                assert item["text"] in {
                    f"*{label}* · {status}"
                    for label in ("Vacation / PTO", "Sick leave", "Request")
                    for status in (
                        "Draft",
                        "In review",
                        "Reported",
                        "Acknowledged",
                        "Approved",
                        "Declined",
                        "Cancelled",
                        "Status unavailable",
                    )
                }
        if kind == "rich_text":
            assert all(element["type"] == "rich_text_section" for element in item["elements"])
        if kind == "rich_text_section":
            assert all(element["type"] == "text" for element in item["elements"])
        if kind == "text":
            assert 0 < len(item["text"]) <= 2800
            assert "style" not in item  # API data must not inject formatting.
        if kind == "section" and "fields" in item:
            assert 1 <= len(item["fields"]) <= 10
            for field in item["fields"]:
                assert field["type"] == "plain_text" and len(field["text"]) <= 2000
                assert "\n" not in field["text"]
        if kind == "header":
            assert len(item["text"]["text"]) <= 150
        if kind == "actions":
            assert 1 <= len(item["elements"]) <= 25
            actions = [element["action_id"] for element in item["elements"]]
            assert len(actions) == len(set(actions))
        if kind == "context":
            assert 1 <= len(item["elements"]) <= 10
        if kind == "button":
            assert len(item["text"]["text"]) <= 75
            assert len(item["action_id"]) <= 255
            if "value" in item:
                assert 0 < len(item["value"]) <= 2000
            if "url" in item:
                assert item["url"].startswith(("https://", "slack://app?"))
                assert len(item["url"]) <= 3000
                assert "value" not in item
            if "confirm" in item:
                confirm = item["confirm"]
                for field, limit in (("title", 100), ("text", 300), ("confirm", 30), ("deny", 30)):
                    assert confirm[field]["type"] == "plain_text"
                    assert len(confirm[field]["text"]) <= limit
        if kind == "input":
            if item["block_id"] in {"expected_return_unknown", "time_away"}:
                assert item["element"]["action_id"] == "request_field_changed"
                assert item["dispatch_action"] is True
            else:
                assert item["element"]["action_id"] == "value"
            assert len(item["label"]["text"]) <= 2000
            assert len(item.get("hint", {"text": ""})["text"]) <= 2000
        if kind in {"static_select", "checkboxes", "radio_buttons"}:
            assert 1 <= len(item["options"]) <= (100 if kind == "static_select" else 10)
            for option in item["options"]:
                assert len(option["text"]["text"]) <= 75
                assert len(option["value"]) <= 150
            if "initial_option" in item:
                assert item["initial_option"] in item["options"]
            for option in item.get("initial_options", []):
                assert option in item["options"]
        if kind == "plain_text_input":
            assert 1 <= item["max_length"] <= 3000
            assert len(item.get("initial_value", "")) <= item["max_length"]
    # Payloads must be directly serializable; no SDK objects/datetime/sets.
    assert json.loads(json.dumps(value, ensure_ascii=False)) == value


def test_home_empty_and_overview_navigation():
    view = views.home_view([], [])
    assert view["type"] == "home"
    assert "No active or upcoming requests" in texts(view)
    assert "get help from HR" not in texts(view)
    assert {button["action_id"] for button in buttons(view)} == {
        "ask_question",
        "new_request",
    }
    assert selected_values(view, "home_section") == ["overview", "requests", "conversations"]
    assert len(buttons(view)) + len(selections(view, "home_section")) == 3
    assert "Messages" in texts(view)
    assert_slack_shape(view)


@pytest.mark.parametrize(
    "section,action", [("requests", "select_request"), ("conversations", "open_conversation")]
)
def test_home_pages_cover_every_item_once_without_mutation(section, action):
    records = [
        request(id=str(index)) if section == "requests" else conversation(id=str(index))
        for index in range(23)
    ]
    before = copy.deepcopy(records)
    seen = []
    for page in range(3):
        view = views.home_view(
            records if section == "requests" else [],
            records if section == "conversations" else [],
            section,
            page,
        )
        seen.extend(
            selected_values(view, action)
            if section == "requests"
            else [button["value"] for button in buttons(view, action)]
        )
        assert selections(view, "home_section")[0]["initial_option"]["value"] == section
        assert not buttons(view, "cancel_request") and not buttons(view, "delete_conversation")
        assert_slack_shape(view)
        assert json.loads(view["private_metadata"]) == {"section": section, "page": page}
        pager = [
            button
            for button in buttons(view, "show_" + section)
            if button["text"]["text"] in {"Previous", "Next"}
        ]
        assert [int(button["value"]) for button in pager] == (
            [1] if page == 0 else [0, 2] if page == 1 else [1]
        )
    assert seen == [str(index) for index in range(23)]
    assert records == before


@pytest.mark.parametrize("page,expected", [(-1, 0), (999, 1), ("bad", 0), (None, 0)])
def test_home_page_clamping(page, expected):
    view = views.home_view([request(id=str(index)) for index in range(10)], [], "requests", page)
    assert json.loads(view["private_metadata"])["page"] == expected
    assert_slack_shape(view)


def test_overview_is_bounded_and_unknown_section_falls_back():
    view = views.home_view(
        [request(id=str(index)) for index in range(100)],
        [conversation(id=str(index)) for index in range(100)],
        "unknown",
        99,
    )
    assert not buttons(view, "edit_request")
    assert texts(view).count("Vacation / PTO") == 3
    assert "97 more active requests" in texts(view)
    assert not buttons(view, "open_conversation")
    assert len(view["blocks"]) <= 12
    assert json.loads(view["private_metadata"]) == {"section": "overview", "page": 0}
    assert_slack_shape(view)


@pytest.mark.parametrize("kind", ["pto", "sick_leave"])
@pytest.mark.parametrize(
    "status",
    [
        "draft",
        "in_review",
        "reported",
        "acknowledged",
        "approved",
        "declined",
        "cancelled",
        "future_status",
    ],
)
def test_employee_actions_follow_workflow_status(kind, status):
    card = views.request_blocks(request(kind, status))
    actions = {button["action_id"] for button in buttons(card)}
    assert not actions
    assert ("Not sent yet" in texts(card)) is (status == "draft")
    explicit = views.request_blocks(request(kind, status), include_actions=True)
    assert {button["action_id"] for button in buttons(explicit)} == (
        {"edit_request"} if status == "draft" else {"open_request"}
    )
    detail = views.request_detail_view({"request": request(kind, status)})
    detail_actions = {button["action_id"] for button in buttons(detail)}
    assert ("edit_request" in detail_actions) == (status == "draft")
    expected_cancel = status in ({"draft", "in_review"} if kind == "pto" else {"draft", "reported"})
    assert ("cancel_request" in detail_actions) == expected_cancel
    assert "open_request" not in detail_actions
    assert "request-123" not in texts(detail)
    assert (
        not {"approve_request", "decline_request", "acknowledge_request", "manage_documents"}
        & actions
    )
    for button in buttons(card):
        assert button["value"] == "request-123"
    if expected_cancel:
        assert "confirm" in buttons(detail, "cancel_request")[0]
    assert not buttons(views.request_blocks(request(kind, status), include_actions=False))
    assert_slack_shape(card)
    assert_slack_shape(detail)


def test_sick_display_unknown_partial_and_legacy_return():
    card = views.request_blocks(
        request(
            "sick_leave",
            "reported",
            end_date=None,
            details={
                "expected_return_unknown": True,
                "time_away": "partial_day",
                "partial_hours": 3.5,
                "extended_or_recurring": True,
            },
        )
    )
    assert "Return date unknown" in texts(card)
    assert "3.5 hours" in texts(card)
    assert "People Ops" not in texts(card)
    flagged = views.request_detail_view(
        {"request": request("sick_leave", details={"extended_or_recurring": True})}
    )
    assert "People Ops follow-up flagged" in texts(flagged)
    assert "no message is sent to People Ops." in texts(flagged)
    assert "Back Sep 10, 2026" in texts(views.request_blocks(request("sick_leave")))
    explicit = request(
        "sick_leave", details={"expected_return_date": "2026-09-07", "time_away": "partial_day"}
    )
    assert "Back Sep 7, 2026" in texts(views.request_blocks(explicit))


def test_delete_confirmation_explains_peopleflow_and_slack_history():
    view = views.conversation_view({"conversation": conversation()})
    button = buttons(view, "delete_conversation")[0]
    confirmation = texts(button["confirm"])
    assert button["value"] == "conversation-123"
    assert "PeopleFlow history" in confirmation
    assert "Existing Slack messages will remain" in confirmation
    assert "cannot be undone" in confirmation
    assert "requests will stay" in confirmation


def test_chat_answers_never_render_controls_even_with_sources_and_request():
    blocks = views.answer_blocks("Answer", [{"title": "Policy"}], request())
    assert not buttons(blocks)
    assert "Sources: Policy" in texts(blocks)
    assert "Not sent yet. Open Home → My requests" in texts(blocks)
    assert "Reply in thread" not in texts(blocks)
    assert not buttons(views.answer_blocks("Answer", [{"title": "Policy"}]))
    assert not buttons(views.answer_blocks("Answer"), "view_sources")
    assert_slack_shape(blocks)


@pytest.mark.parametrize("sources", [[], [{"title": "Vacation policy"}]])
def test_saved_feedback_hides_rating_buttons_and_preserves_sources(sources):
    default = views.answer_blocks("Answer", sources, request())
    explicit_default = views.answer_blocks("Answer", sources, request(), feedback_saved=False)
    assert default == explicit_default
    assert not buttons(default)
    saved = views.answer_blocks("Answer", sources, request(), feedback_saved=True)
    assert not buttons(saved, "feedback_helpful") and not buttons(saved, "feedback_unhelpful")
    assert buttons(saved, "view_sources") == buttons(default, "view_sources")
    assert buttons(saved, "edit_request") == buttons(default, "edit_request")
    assert "Feedback saved" in texts(saved) and "Feedback saved" not in texts(default)
    assert_slack_shape(saved)


def test_saved_feedback_has_no_empty_action_block():
    saved = views.answer_blocks("Answer", feedback_saved=True)
    assert "Feedback saved" in texts(saved) and not buttons(saved)
    assert_slack_shape(saved)


def test_request_summary_has_compact_date_range_on_home_and_in_modal():
    record = request(status="in_review")
    home = views.home_view([record], [])
    assert "Waiting for your manager" in texts(home)
    assert "Vacation / PTO · Sep 7–9, 2026" in texts(home)
    assert not buttons(home, "open_request")
    for surface in (views.request_detail_view({"request": record}),):
        summary = next(
            block for block in surface["blocks"] if block.get("text", {}).get("type") == "mrkdwn"
        )
        assert summary["text"] == {
            "type": "mrkdwn",
            "text": "*Vacation / PTO* · In review",
            "verbatim": True,
        }
        assert "fields" not in summary  # A lone Slack field would still use half the modal width.
        assert "Sep 7–9, 2026" in texts(surface)
        assert_slack_shape(surface)


def test_multiline_notes_answers_and_sources_are_literal_rich_text():
    raw = "First line\n<!channel> <@U123> <https://evil.invalid|Policy> *bold* `code` &amp;\nLast line"
    outputs = [
        views.request_detail_view({"request": request(comment=raw)}),
        views.answer_blocks(raw),
        views.sources_view([{"title": "Policy", "excerpt": raw}]),
        views.conversation_view(
            {
                "conversation": conversation(),
                "messages": [
                    {"role": "user", "content": raw},
                ],
            }
        ),
    ]
    for output in outputs:
        literals = [item["text"] for item in walk(output) if item.get("type") == "text"]
        assert any(raw in literal for literal in literals)
        for item in walk(output):
            if item.get("type") == "section" and item.get("text", {}).get("type") == "plain_text":
                assert "\n" not in item["text"]["text"]
        assert_slack_shape(output)


def test_answer_chunks_preserve_literal_text_and_stop_with_notice():
    raw = "<@U123> & <!everyone> *bold* _italic_ `code`\n" * 160
    blocks = views.answer_blocks(raw)
    content = "".join(item["text"] for item in walk(blocks) if item.get("type") == "text")
    assert content == raw
    assert_slack_shape(blocks)
    long = views.answer_blocks("<&>" * 100000, [{"title": "Policy"}], request())
    assert "shortened for Slack" in texts(long)
    assert not buttons(long)
    assert_slack_shape(long)


def test_all_untrusted_surface_text_is_literal_and_escaped():
    hostile = "<!channel> <@U123> <https://evil.invalid|Policy> &amp; *bold* _italic_ `code`"
    record = request(comment=hostile, applicant=hostile, validation_errors=[hostile])
    record["start_date"] = hostile
    source = {
        key: hostile for key in ("title", "source", "section", "category", "version", "excerpt")
    }
    outputs = [
        views.home_view([record], [conversation(title=hostile)]),
        views.answer_blocks(hostile, [source], record),
        views.sources_view([source]),
        views.request_detail_view(
            {
                "request": record,
                "events": [
                    {"actor": hostile, "to_status": "draft", "details": {"comment": hostile}}
                ],
                "comments": [{"body": hostile, "author": hostile}],
            }
        ),
        views.conversation_view(
            {
                "conversation": conversation(title=hostile),
                "messages": [{"role": "user", "content": hostile}],
            }
        ),
        views.error_blocks(hostile),
        views.loading_blocks(hostile),
        views.state_blocks(hostile),
    ]
    for output in outputs:
        assert_slack_shape(output)
        assert "&lt;!channel&gt;" in texts(output) or hostile in texts(output)
        assert "&amp;amp;" in texts(output) or hostile in texts(output)


def test_pto_form_submission_and_raw_draft_prefill():
    record = request(comment="Handoff to R&D <team> *today*")
    before = copy.deepcopy(record)
    view = views.request_form(draft=record)
    fields = inputs(view)
    assert view["callback_id"] == "request_submit"
    metadata = json.loads(view["private_metadata"])
    assert metadata["request_type"] == "pto" and metadata["draft_id"] == "request-123"
    assert metadata["state_values"]["end_date"] == "2026-09-09"
    assert "comment" not in metadata["state_values"]
    assert set(fields) == {"start_date", "end_date", "comment"}
    assert all(not field["optional"] for field in fields.values())
    assert fields["comment"]["element"]["initial_value"] == record["comment"]
    assert fields["start_date"]["element"]["initial_date"] == "2026-09-07"
    assert view["submit"]["text"] == "Send for review"
    assert record == before
    assert_slack_shape(view)


def test_sick_form_preserves_details_and_expresses_conditional_requirements():
    record = request(
        "sick_leave",
        end_date=None,
        details={
            "expected_return_date": "2026-09-07",
            "expected_return_unknown": False,
            "time_away": "partial_day",
            "partial_hours": 0.25,
            "extended_or_recurring": True,
        },
    )
    before = copy.deepcopy(record)
    view = views.request_form(draft=record)
    fields = inputs(view)
    assert set(fields) == {
        "start_date",
        "comment",
        "expected_return_date",
        "expected_return_unknown",
        "time_away",
        "partial_hours",
        "extended_or_recurring",
    }
    assert json.loads(view["private_metadata"])["request_type"] == "sick_leave"
    assert fields["comment"]["optional"] is True
    assert fields["expected_return_date"]["optional"] is False
    assert fields["partial_hours"]["optional"] is False
    assert fields["expected_return_date"]["element"]["initial_date"] == "2026-09-07"
    assert fields["time_away"]["element"]["initial_option"]["value"] == "partial_day"
    assert fields["partial_hours"]["element"]["initial_value"] == "0.25"
    assert fields["partial_hours"]["element"]["is_decimal_allowed"] is True
    assert fields["extended_or_recurring"]["element"]["initial_options"][0]["value"] == "true"
    assert "records a follow-up flag" in fields["extended_or_recurring"]["hint"]["text"]
    assert "No message is sent to People Ops." in fields["extended_or_recurring"]["hint"]["text"]
    assert view["submit"]["text"] == "Report absence"
    assert "for acknowledgement" in texts(view)
    assert record == before
    assert_slack_shape(view)
    record["details"]["expected_return_unknown"] = True
    fields = inputs(views.request_form(draft=record))
    assert "expected_return_date" not in fields
    assert fields["expected_return_unknown"]["element"]["initial_options"][0]["value"] == "true"


def test_fresh_sick_form_defaults_to_today_full_day_and_unknown_return():
    for kind in ("pto", "sick_leave"):
        view = views.request_form(kind)
        assert json.loads(view["private_metadata"])["request_type"] == kind
        if kind == "sick_leave":
            fields = inputs(view)
            assert fields["start_date"]["element"]["initial_date"] == "2026-09-06"
            assert fields["time_away"]["element"]["initial_option"]["value"] == "full_day"
            assert (
                fields["expected_return_unknown"]["element"]["initial_options"][0]["value"]
                == "true"
            )
            assert (
                not {"expected_return_date", "partial_hours", "extended_or_recurring"}
                & fields.keys()
            )
            assert "Return date unknown" in texts(view)
        else:
            assert "initial_date" not in inputs(view)["start_date"]["element"]
        assert not {"applicant", "approver", "manager", "user"} & set(inputs(view))
        assert_slack_shape(view)
    with pytest.raises(ValueError):
        views.request_form("payroll")


def test_question_and_feedback_contracts():
    question = views.question_view()
    assert question["callback_id"] == "question_submit"
    assert json.loads(question["private_metadata"]) == {}
    assert not inputs(question)["question"]["optional"]
    assert inputs(question)["question"]["hint"]["text"] == (
        "Your answer appears in Messages. You can keep chatting there."
    )
    assert "get help from HR" not in texts(question)
    assert "HR" not in texts(question) and "demo" not in texts(question)
    feedback = views.feedback_view('answer-<1>"')
    assert feedback["callback_id"] == "feedback_submit"
    assert json.loads(feedback["private_metadata"]) == {"answer_id": 'answer-<1>"'}
    assert inputs(feedback)["comment"]["optional"]
    assert_slack_shape(question)
    assert_slack_shape(feedback)
    with pytest.raises(ValueError):
        views.feedback_view("")


def test_request_activity_pagination_and_decision_note():
    record = request(status="declined")
    events = [
        {"actor": "manager", "to_status": "declined", "details": {"comment": f"Decision {i}"}}
        for i in range(12)
    ]
    comments = [{"author": "employee", "body": "Can we review other dates?"}]
    detail = {"request": record, "events": events, "comments": comments}
    first = views.request_detail_view(detail)
    assert "Reason for decline\nDecision 11" in texts(first)
    assert not buttons(first, "cancel_request")
    assert not buttons(first, "open_request")
    next_button = buttons(first, "request_detail_page")[0]
    assert json.loads(next_button["value"]) == {"request_id": "request-123", "page": 1}
    last = views.request_detail_view({**detail, "page": 1})
    assert "Can we review other dates?" in texts(last)
    assert "Decision 8" in texts(last)
    assert_slack_shape(first)
    assert_slack_shape(last)


@pytest.mark.parametrize("surface", ["activity", "conversation"])
@pytest.mark.parametrize(
    "timestamp,expected",
    [
        ("2026-09-06T16:30:34.997316+00:00", "Sep 6, 2026 · 4:30 PM UTC"),
        ("2026-09-06T19:30:34+03:00", "Sep 6, 2026 · 4:30 PM UTC"),
        ("2026-09-07T01:05:00+03:00", "Sep 6, 2026 · 10:05 PM UTC"),
        ("2026-09-06T00:00:00Z", "Sep 6, 2026 · 12:00 AM UTC"),
        ("2026-09-06T12:00:00+00:00", "Sep 6, 2026 · 12:00 PM UTC"),
        ("2026-09-06T16:30:34", "Sep 6, 2026 · 4:30 PM UTC"),
        ("2026-02-30T16:30:34+00:00", "2026-02-30T16:30:34+00:00"),
        ("not a timestamp", "not a timestamp"),
        ("2026-09-06", "2026-09-06"),
    ],
)
def test_timestamps_are_english_utc_or_preserve_invalid_fallback(surface, timestamp, expected):
    if surface == "activity":
        detail = {
            "request": request(),
            "events": [{"to_status": "draft", "created_at": timestamp}],
            "comments": [{"author": "employee", "body": "A note", "created_at": timestamp}],
        }
        render = views.request_detail_view
    else:
        detail = {
            "conversation": conversation(),
            "messages": [
                {"role": "user", "content": "Question", "created_at": timestamp},
                {"role": "assistant", "content": "Answer", "created_at": timestamp},
            ],
        }
        render = views.conversation_view
    before = copy.deepcopy(detail)
    view = render(detail)
    assert texts(view).splitlines().count(expected) == 2
    assert detail == before
    assert_slack_shape(view)


def test_history_pages_expose_all_messages_and_link_current_request():
    detail = {
        "conversation": conversation(),
        "messages": [
            {
                "id": f"answer-{i}",
                "role": "assistant",
                "content": f"Unique message {i}",
                "sources": [{"title": "Policy"}],
                "workflow": request(status="draft"),
            }
            for i in range(19)
        ],
    }
    before = copy.deepcopy(detail)
    seen = []
    for page in range(4):
        view = views.conversation_view({**detail, "page": page})
        seen.extend(button["value"] for button in buttons(view, "view_sources"))
        assert not buttons(view, "edit_request")  # A saved status must not drive current actions.
        assert buttons(view, "continue_conversation")[0]["value"] == "conversation-123"
        for button in buttons(view, "conversation_page"):
            value = json.loads(button["value"])
            assert value["conversation_id"] == "conversation-123"
            assert abs(value["page"] - page) == 1
        assert_slack_shape(view)
    assert seen == [f"answer-{i}" for i in range(19)]
    assert detail == before


def test_worst_case_surface_budgets_and_sources_empty_state():
    huge = "<&>" * 10000
    source = {key: huge for key in ("title", "source", "section", "category", "version", "excerpt")}
    sources = views.sources_view([source] * 100)
    assert "Showing 20 of 100" in texts(sources)
    assert len(sources["blocks"]) < 100
    assert "No sources were attached" in texts(views.sources_view([]))
    assert_slack_shape(sources)
    assert_slack_shape(
        views.conversation_view(
            {
                "conversation": conversation(title=huge),
                "messages": [
                    {
                        "id": str(i),
                        "role": "assistant",
                        "content": huge,
                        "created_at": huge,
                        "sources": [source],
                        "workflow": request(),
                    }
                    for i in range(100)
                ],
                "page": 5,
            }
        )
    )
    assert_slack_shape(
        views.request_detail_view(
            {
                "request": request(
                    "sick_leave",
                    comment=huge,
                    validation_errors=[huge] * 10,
                    details={"extended_or_recurring": True},
                ),
                "events": [{"actor": huge, "created_at": huge, "details": {"comment": huge}}] * 100,
                "comments": [{"author": huge, "body": huge, "created_at": huge}] * 100,
                "page": 1,
            }
        )
    )


def test_long_clipping_is_visible_and_entities_are_not_cut():
    for character in ("&", "<", ">", "🙂", "a"):
        view = views.sources_view([{"title": character * 10000, "excerpt": character * 10000}])
        assert "…" in texts(view)
        for item in walk(view):
            if item.get("type") == "plain_text":
                # All ampersands must form a complete one of Slack's three entities.
                clean = item["text"].replace("&amp;", "").replace("&lt;", "").replace("&gt;", "")
                assert "&" not in clean
        assert_slack_shape(view)


def test_ids_and_editable_drafts_are_never_silently_truncated():
    with pytest.raises(ValueError):
        views.request_blocks(request(id="a" * 2001), include_actions=True)
    with pytest.raises(ValueError):
        views.feedback_view("a" * 3001)
    with pytest.raises(ValueError):
        views.request_form(draft=request(comment="x" * 3001))


@pytest.mark.parametrize(
    "url",
    [
        "https://slack.com/app_redirect?app=A123&team=T123",
        "slack://app?team=T0BGD66SC3X&id=A0BV7367MUM&tab=messages",
        "slack://app?tab=messages&id=A0BV7367MUM&team=T0BGD66SC3X",
    ],
)
def test_home_chat_url_is_primary_without_duplicate_navigation(url):
    view = views.home_view([], [], chat_url=url)
    assert view["blocks"][0]["text"]["text"] == "Your HR, in Slack"
    primary = buttons(view, "open_slack_chat")
    assert len(primary) == 1 and primary[0]["url"] == url
    assert primary[0]["style"] == "primary" and primary[0]["text"]["text"] == "Open Messages"
    assert not buttons(view, "ask_question") and not buttons(view, "show_home")
    assert len(buttons(view)) == 2
    assert len(selections(view, "home_section")) == 1
    assert_slack_shape(view)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "javascript:alert(1)",
        "http://slack.com/",
        "https://",
        "https://u:p@slack.com/",
        "https://slack.com/\n<!channel>",
        "ftp://slack.com/messages",
        "\x00slack://app?team=T123&id=A123&tab=messages",
        "slack://external.example?team=T123&id=A123&tab=messages",
        "slack://app.external.example?team=T123&id=A123&tab=messages",
        "slack://app@external.example?team=T123&id=A123&tab=messages",
        "slack://user@app?team=T123&id=A123&tab=messages",
        "slack://app:443?team=T123&id=A123&tab=messages",
        "slack://app/?team=T123&id=A123&tab=messages",
        "slack://app/messages?team=T123&id=A123&tab=messages",
        "slack://app?team=T123&id=A123&tab=messages#home",
        "slack://app?team=T123&id=A123&tab=messages#",
        "slack://app?team=T123&id=A123&tab=home",
        "slack://app?team=T123&id=A123",
        "slack://app?team=T123&tab=messages",
        "slack://app?id=A123&tab=messages",
        "slack://app?team=&id=A123&tab=messages",
        "slack://app?team=T123&id=&tab=messages",
        "slack://app?team=T&id=A&tab=messages",
        "slack://app?team=E123&id=A123&tab=messages",
        "slack://app?team=T123&id=B123&tab=messages",
        "slack://app?team=T12a&id=A123&tab=messages",
        "slack://app?team=T123&id=A12_3&tab=messages",
        "slack://app?team=T１２３&id=A123&tab=messages",
        "slack://app?team=T123&id=A123&tab=messages&team=T456",
        "slack://app?team=T123&id=A123&tab=messages&tab=messages",
        "slack://app?team=T123&id=A123&tab=messages&redirect=https://external.example",
        "slack://app?team=T123&id=A123&tab=messages&unexpected",
        "slack://app?team=T123&id=A123&tab=messages&",
        "slack://app?team=T123&id=A123&tab=messages%0A",
        "slack://app?team=T123&id=A%ZZ&tab=messages",
    ],
)
def test_missing_or_invalid_urls_keep_working_modal_fallbacks(url):
    home = views.home_view([], [], chat_url=url)
    record = conversation(slack_url=url)
    history = views.home_view([], [record], "conversations")
    modal = views.conversation_view({"conversation": record})
    assert buttons(home, "ask_question") and not buttons(home, "open_slack_chat")
    assert buttons(history, "open_conversation") and not buttons(history, "open_slack_conversation")
    assert buttons(modal, "continue_conversation") and not buttons(modal, "open_slack_conversation")
    for view in (home, history, modal):
        assert_slack_shape(view)


def test_conversation_links_open_slack_and_delete_stays_in_saved_detail():
    url = "https://example.slack.com/archives/D123/p1234567890123456"
    record = conversation(slack_url=url)
    home = views.home_view([], [record, conversation(id="web-only")], "conversations")
    link = buttons(home, "open_slack_conversation")[0]
    assert link["url"] == url and link["text"]["text"] == "Open conversation"
    assert [button["value"] for button in buttons(home, "open_conversation")] == ["web-only"]
    assert not buttons(home, "continue_conversation") and not buttons(home, "delete_conversation")
    detail = views.conversation_view({"conversation": record})
    link = buttons(detail, "open_slack_conversation")[0]
    assert link["style"] == "primary" and link["text"]["text"] == "Open in Slack"
    assert link["url"] == url and not buttons(detail, "continue_conversation")
    assert buttons(detail, "delete_conversation")[0]["value"] == record["id"]
    assert_slack_shape(home)
    assert_slack_shape(detail)


@pytest.mark.parametrize(
    "status,start,end,included",
    [
        ("draft", None, None, True),
        ("draft", "2026-09-05", "2026-09-08", True),
        ("draft", "2026-09-01", "2026-09-05", True),
        ("in_review", "2026-09-06", "2026-09-06", True),
        ("in_review", "2026-09-01", "2026-09-05", True),
        ("approved", "2026-09-06", "2026-09-07", True),
        ("approved", "2026-09-05", "2026-09-07", True),
        ("approved", None, "2026-09-07", False),
        ("acknowledged", "2026-09-07", None, True),
        ("reported", "2026-09-07", None, True),
        ("cancelled", "2026-09-07", "2026-09-08", False),
        ("declined", "2026-09-07", "2026-09-08", False),
        ("rejected", "2026-09-07", "2026-09-08", False),
        ("future_status", "2026-09-07", "2026-09-08", False),
    ],
)
def test_home_overview_only_active_or_upcoming_requests(status, start, end, included):
    record = request(status=status, start_date=start, end_date=end)
    overview = views.home_view([record], [])
    assert ("Vacation / PTO" in texts(overview)) is included
    assert not buttons(overview, "open_request") and not buttons(overview, "edit_request")
    # Filtering the launchpad must not hide historical records from the list.
    history = views.home_view([record], [], "requests")
    assert selected_values(history, "select_request") == [record["id"]]


def test_home_actionable_first_date_order_and_three_row_limit_without_mutation():
    records = [
        request(id="approved", status="approved"),
        request(id="review", status="in_review"),
        request(id="later-draft", start_date="2026-09-09"),
        request(id="earlier-draft", start_date="2026-09-08"),
        request(id="cancelled", status="cancelled"),
    ]
    before = copy.deepcopy(records)
    view = views.home_view(records, [conversation()])
    content = texts(view)
    assert (
        content.index("Sep 8") < content.index("Sep 9") < content.index("Waiting for your manager")
    )
    assert "Active &amp; upcoming" not in content
    assert content.count("Vacation / PTO") == 3
    assert not buttons(view, "open_request") and not buttons(view, "edit_request")
    assert records == before


def test_home_keeps_an_acknowledged_absence_with_unknown_return_visible():
    ongoing = request(
        "sick_leave",
        "acknowledged",
        start_date="2026-09-01",
        end_date=None,
        details={"expected_return_unknown": True},
    )
    view = views.home_view([ongoing], [])
    assert not buttons(view, "open_request")
    assert "Return date unknown" in texts(view)


@pytest.mark.parametrize(
    "start,end,expected",
    [
        ("2026-09-07", "2026-09-07", "Sep 7, 2026"),
        ("2026-09-07", "2026-09-09", "Sep 7–9, 2026"),
        ("2026-09-30", "2026-10-02", "Sep 30, 2026 – Oct 2, 2026"),
        ("2026-12-31", "2027-01-02", "Dec 31, 2026 – Jan 2, 2027"),
        (None, None, "Choose dates"),
        ("", "", "Choose dates"),
        ("2026-09-07", None, "From Sep 7, 2026 · Choose last day"),
        (None, "2026-09-09", "Until Sep 9, 2026 · Choose first day"),
    ],
)
def test_compact_date_ranges_keep_calendar_boundaries(start, end, expected):
    card = views.request_blocks(request(start_date=start, end_date=end))
    assert expected in texts(card)


@pytest.mark.parametrize("cleared", [None, ""])
def test_rebuilt_sick_form_preserves_explicit_clears_over_legacy_dates(cleared):
    record = request(
        "sick_leave",
        start_date=cleared,
        comment=cleared,
        details={
            "expected_return_date": cleared,
            "expected_return_unknown": False,
            "time_away": "partial_day",
            "partial_hours": cleared,
            "extended_or_recurring": False,
        },
    )
    view = views.request_form(draft=record)
    fields = inputs(view)
    assert "initial_date" not in fields["start_date"]["element"]
    assert "initial_date" not in fields["expected_return_date"]["element"]
    assert "initial_value" not in fields["partial_hours"]["element"]
    assert "initial_value" not in fields["comment"]["element"]
    assert "extended_or_recurring" not in fields
    stash = json.loads(view["private_metadata"])["state_values"]
    assert stash["expected_return_date"] == cleared and stash["partial_hours"] == cleared
    assert stash["expected_return_unknown"] is False
    assert_slack_shape(view)


def test_dynamic_form_roundtrip_restores_hidden_fields_and_raw_note():
    from peopleflow_slack.forms import merge_request_form_state

    record = request(
        "sick_leave",
        comment='  R&D <team>\n"handoff"  ',
        details={
            "time_away": "partial_day",
            "partial_hours": "3.50",
            "expected_return_date": "2026-09-10",
            "expected_return_unknown": False,
            "extended_or_recurring": True,
        },
    )
    first = views.request_form(draft=record)
    values = {
        "comment": {"value": {"value": record["comment"]}},
        "time_away": {"request_field_changed": {"selected_option": {"value": "full_day"}}},
        "expected_return_unknown": {
            "request_field_changed": {"selected_options": [{"value": "true"}]}
        },
        "extended_or_recurring": {"value": {"selected_options": []}},
    }
    hidden_draft = merge_request_form_state(values, "sick_leave", first["private_metadata"])
    before = copy.deepcopy(hidden_draft)
    hidden = views.request_form("sick_leave", hidden_draft)
    assert hidden_draft == before
    assert (
        not {"partial_hours", "expected_return_date", "extended_or_recurring"}
        & inputs(hidden).keys()
    )
    stash = json.loads(hidden["private_metadata"])["state_values"]
    assert stash["partial_hours"] == "3.50" and stash["expected_return_date"] == "2026-09-10"
    assert stash["extended_or_recurring"] is False
    values["time_away"]["request_field_changed"]["selected_option"]["value"] = "partial_day"
    values["expected_return_unknown"]["request_field_changed"]["selected_options"] = []
    restored = views.request_form(
        "sick_leave", merge_request_form_state(values, "sick_leave", hidden["private_metadata"])
    )
    fields = inputs(restored)
    assert fields["partial_hours"]["element"]["initial_value"] == "3.50"
    assert fields["expected_return_date"]["element"]["initial_date"] == "2026-09-10"
    assert fields["comment"]["element"]["initial_value"] == record["comment"]
    assert json.loads(restored["private_metadata"])["draft_id"] == record["id"]
    for view in (first, hidden, restored):
        assert_slack_shape(view)


def test_long_escaped_note_is_not_copied_to_metadata_or_truncated():
    note = '\n"\\' * 666
    view = views.request_form(
        draft=request("sick_leave", comment=note, state_values={"comment": note})
    )
    assert inputs(view)["comment"]["element"]["initial_value"] == note
    assert "comment" not in json.loads(view["private_metadata"])["state_values"]
    assert_slack_shape(view)


def test_answer_optional_question_context_is_bounded_literal_and_preserved_with_feedback():
    question = "<!channel> <@U1> *bold* &\n" * 50
    default = views.answer_blocks("Answer")
    assert default == views.answer_blocks("Answer", question="")
    for saved in (False, True):
        blocks = views.answer_blocks(
            "Answer", [{"title": "Policy"}], question=question, feedback_saved=saved
        )
        context = blocks[0]["elements"][0]
        assert context["type"] == "plain_text" and len(context["text"]) <= 400
        assert context["text"].startswith("You asked: &lt;!channel&gt;")
        assert context["text"].endswith("…") and "\n" not in context["text"]
        assert "Reply in thread" not in texts(blocks)
        assert "Sources: Policy" in texts(blocks)
        assert not buttons(blocks)
        assert_slack_shape(blocks)


@pytest.mark.parametrize(
    "status,phrase",
    [
        ("approved", "Your time off was approved."),
        ("declined", "Your request was declined."),
        ("acknowledged", "Your sick leave was acknowledged."),
        ("cancelled", "Your request was cancelled."),
    ],
)
def test_status_notification_includes_decision_and_distinct_new_comment(status, phrase):
    detail = {
        "request": request(status=status, comment="Original receipt planning note"),
        "events": [
            {"to_status": "in_review", "details": {"comment": "Old note"}},
            {"to_status": status, "details": {"comment": "Manager decision"}},
        ],
        "comments": [{"body": "Separate manager comment"}],
    }
    before = copy.deepcopy(detail)
    blocks = views.notification_blocks(detail)
    assert phrase in texts(blocks) and "Sep 7–9, 2026" in texts(blocks)
    assert "Manager decision" in texts(blocks) and "Separate manager comment" in texts(blocks)
    assert "Old note" not in texts(blocks) and "Original receipt" not in texts(blocks)
    assert not buttons(blocks)
    assert len(blocks) <= 5 and detail == before
    assert_slack_shape(blocks)


def test_notification_receipt_comment_deduplication_and_bounded_notes():
    detail = {
        "request": request(status="approved"),
        "events": [
            {"to_status": "approved", "details": {"comment": "Same note"}},
        ],
        "comments": [{"body": "Same note"}],
    }
    assert views.notification_blocks(detail, kind="receipt") == views.request_blocks(
        detail["request"]
    )
    assert texts(views.notification_blocks(detail)).count("Same note") == 1
    detail["comments"] = [{"body": "Older comment"}, {"body": "<!channel>\n" + "x" * 1000}]
    blocks = views.notification_blocks(detail, kind="comment")
    assert "New comment on your request" in texts(blocks)
    assert "Older comment" not in texts(blocks) and "Same note" not in texts(blocks)
    literal = next(item["text"] for item in walk(blocks) if item.get("type") == "text")
    assert len(literal) == 800 and literal.endswith("…")
    assert not buttons(blocks)
    assert_slack_shape(blocks)
    with pytest.raises(ValueError):
        views.notification_blocks(detail, kind="unsupported")


def test_sources_have_concise_titles_and_bounded_extracts():
    source = {
        "title": "Vacation policy",
        "source": "vacation.md",
        "section": "Eligibility",
        "version": "2",
        "excerpt": "x" * 5000,
    }
    view = views.sources_view([source])
    assert len(view["blocks"]) == 3
    assert "Vacation policy" in texts(view) and "Source 1" not in texts(view)
    assert "Section: Eligibility" in texts(view) and "Version: 2" in texts(view)
    assert len(view["blocks"][-1]["text"]["text"]) == 800
    assert_slack_shape(view)


def test_request_type_picker_is_one_native_required_choice_before_submission():
    view = views.request_type_view()
    assert view["callback_id"] == "request_type_submit"
    assert view["submit"]["text"] == "Continue"
    assert json.loads(view["private_metadata"]) == {}
    fields = inputs(view)
    assert set(fields) == {"request_type"}
    choice = fields["request_type"]
    assert choice["optional"] is False
    assert choice["element"]["type"] == "radio_buttons"
    assert choice["element"]["action_id"] == "value"
    assert [item["value"] for item in choice["element"]["options"]] == ["pto", "sick_leave"]
    assert "initial_option" not in choice["element"]
    assert "before anything is sent" in texts(view)
    assert not buttons(view)
    assert_slack_shape(view)


def test_request_list_keeps_opaque_select_ids_and_has_no_per_row_buttons():
    identity = 'request<&"123'
    records = [request(id=identity), request(id="approved", status="approved")]
    view = views.home_view(records, [], "requests")
    assert selected_values(view, "select_request") == [identity, "approved"]
    assert not buttons(view, "open_request") and not buttons(view, "edit_request")
    assert len(selections(view, "select_request")) == 1
    assert_slack_shape(view)


def test_request_list_preserves_long_ids_with_explicit_detail_fallback():
    identity = "request-" + "x" * 150
    view = views.home_view([request(id=identity), request(id="short")], [], "requests")
    assert buttons(view, "edit_request")[0]["value"] == identity
    assert selected_values(view, "select_request") == ["short"]
    assert identity not in texts(view)
    assert_slack_shape(view)


def test_answer_sources_are_deduplicated_bounded_literal_titles_without_excerpt_noise():
    sources = [
        {"title": "Vacation policy", "excerpt": "EXCERPT MUST NOT APPEAR"},
        {"title": "Vacation policy"},
        {"title": "<!channel>\nR&D policy"},
        {"source": "sick-leave.md"},
        {"title": "Fourth policy"},
    ]
    before = copy.deepcopy(sources)
    blocks = views.answer_blocks("Answer", sources)
    assert texts(blocks).count("Vacation policy") == 1
    assert "EXCERPT MUST NOT APPEAR" not in texts(blocks)
    assert "&lt;!channel&gt; R&amp;D policy" in texts(blocks)
    assert "+1 more" in texts(blocks) and "Fourth policy" not in texts(blocks)
    assert not buttons(blocks) and sources == before
    source_context = blocks[-1]["elements"][0]
    assert source_context["type"] == "plain_text"
    assert len(source_context["text"]) <= 600
    assert_slack_shape(blocks)


def test_sources_with_oversized_titles_are_visibly_shortened():
    blocks = views.answer_blocks("Answer", [{"title": "x" * 10000}])
    assert "…" in texts(blocks)
    assert len(blocks[-1]["elements"][0]["text"]) <= 600
    assert_slack_shape(blocks)


def test_draft_chat_hint_does_not_send_users_out_of_request_modal():
    draft = request()
    assert "Home → My requests" in texts(views.request_blocks(draft))
    assert "Home → My requests" not in texts(views.request_detail_view({"request": draft}))
    assert not buttons(views.help_blocks())
    assert "sources" in texts(views.help_blocks())


@pytest.mark.parametrize(
    "build",
    [
        lambda: views.home_view([], []),
        lambda: views.request_detail_view({}),
        lambda: views.sources_view([]),
        lambda: views.conversation_view({}),
        lambda: views.request_blocks({}),
        lambda: views.answer_blocks(""),
        views.question_view,
        views.request_form,
        views.request_type_view,
        views.help_blocks,
        views.loading_blocks,
        views.error_blocks,
        lambda: views.state_blocks("Saved."),
    ],
)
def test_empty_and_default_surfaces_are_valid(build):
    assert_slack_shape(build())


def test_view_modules_use_only_local_renderers_and_standard_library():
    modules = {"primitives", "requests", "home", "messages"}
    paths = sorted(Path(views.__file__).parent.glob("*.py"))
    assert {path.stem for path in paths} == modules | {"__init__"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert {alias.name for alias in node.names} <= {"json", "re"}
            elif isinstance(node, ast.ImportFrom):
                assert all(alias.name != "*" for alias in node.names)
                if node.level:
                    assert node.level == 1
                    assert node.module in modules or (
                        node.module is None and {alias.name for alias in node.names} <= modules
                    )
                else:
                    assert node.module in {"__future__", "datetime", "urllib.parse"}


def test_notice_helpers_share_literal_text_and_clipping_rules():
    raw = "First line\n<!channel> <https://example.invalid|link> & *bold*\nLast line"
    message = views.text_blocks(raw)
    assert_slack_shape(message)
    assert [item["text"] for item in walk(message) if item.get("type") == "text"] == [raw]
    notice = views.notice_view("<&>" * 30, raw)
    assert notice["type"] == "modal"
    assert notice["close"]["text"] == "Close"
    assert notice["blocks"] == message
    assert len(notice["title"]["text"]) <= 24
    assert "<" not in notice["title"]["text"]
    assert "…" in texts(views.text_blocks("x" * 10000))


@pytest.mark.parametrize(
    "status,expected",
    [
        ("draft", "before sending"),
        ("in_review", "with your manager"),
        ("approved", "approved"),
        ("declined", "declined"),
        ("cancelled", "cancelled"),
        ("unknown", "latest status"),
    ],
)
def test_workflow_presentation_uses_current_status_without_mutating_api_record(status, expected):
    record = request(status=status)
    before = copy.deepcopy(record)
    text = views.workflow_answer_text(record)
    assert expected in text
    assert ("draft" in text) is (status == "draft")
    assert record == before


def test_sick_workflow_presentation_and_incomplete_draft_are_specific():
    assert "absence draft" in views.workflow_answer_text(request("sick_leave"))
    assert "reported" in views.workflow_answer_text(request("sick_leave", "reported"))
    assert "acknowledged" in views.workflow_answer_text(request("sick_leave", "acknowledged"))
    incomplete = request(validation_errors=["Choose a date"])
    assert "missing details" in views.workflow_answer_text(incomplete)
