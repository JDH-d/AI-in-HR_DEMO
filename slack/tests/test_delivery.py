"""Employee delivery regressions using fake API, Slack, and transport storage.

Exercise the production EmployeeApp methods without credentials, network calls,
backend imports, a polling thread, filesystem state, or real-time sleeps.
"""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from slack_sdk.errors import SlackApiError

from peopleflow_slack import chat, views
from peopleflow_slack.application import EmployeeApp
from peopleflow_slack.client import APIError
from peopleflow_slack.inbox import normalize_action

EMPLOYEE = "UEMPLOYEE"
CHANNEL = "DEMPLOYEE"
THREAD = "1700000000.000001"
POLICY_ANSWER = "Choose the first and last calendar day when planning your time off."
HR_BACKEND_ANSWER = (
    "Contacting HR is a simulated interaction in this demo. No HR ticket has been sent. "
    "I can help with company policies, time off, and sick leave."
)
SOURCES = [
    {
        "source": "leave-policy.md",
        "title": "Leave policy",
        "section": "Planning time off",
        "category": "HR",
        "version": "1.0",
        "excerpt": "Choose the first and last calendar day of your time off.",
        "score": 0.9,
    }
]


def block_text(value):
    """Read visible composition text, excluding opaque metadata/action values."""
    if isinstance(value, dict):
        if value.get("type") in {"plain_text", "mrkdwn", "text"} and "text" in value:
            return value["text"]
        return "\n".join(block_text(child) for child in value.values())
    if isinstance(value, list):
        return "\n".join(block_text(child) for child in value)
    return ""


def action_ids(value):
    if isinstance(value, dict):
        own = [value["action_id"]] if "action_id" in value else []
        return own + [action for child in value.values() for action in action_ids(child)]
    if isinstance(value, list):
        return [action for child in value for action in action_ids(child)]
    return []


class FakeStore:
    """In-memory double of the caller's public transport-store contract."""

    def __init__(self):
        self.metadata = {}
        self.operations = {}
        self.answers = {}
        self.threads = {}
        self.request_cards = {}
        self.snapshots = {}
        self.notifications = {}
        self.pending_updates = {}

    def get(self, key, default=None):
        return deepcopy(self.metadata.get(key, default))

    def set(self, key, value):
        self.metadata[key] = deepcopy(value)

    def claim(self, operation_id, retry_failed=False):
        existing = self.operations.get(operation_id)
        if existing and not (retry_failed and existing["state"] == "failed"):
            return False
        self.operations[operation_id] = {"state": "started", "payload": {}}
        return True

    def finish(self, operation_id, state="complete", payload=None):
        self.operations[operation_id] = {"state": state, "payload": deepcopy(payload or {})}

    def operation(self, operation_id):
        return deepcopy(self.operations.get(operation_id))

    def bind(self, channel, ts, conversation_id):
        self.threads[channel, ts] = {
            "channel": channel,
            "ts": ts,
            "conversation_id": conversation_id,
            "deleted": False,
        }

    def thread(self, channel, ts):
        return deepcopy(self.threads.get((channel, ts)))

    def conversation_thread(self, conversation_id):
        entries = [
            item
            for item in self.threads.values()
            if item["conversation_id"] == conversation_id and not item["deleted"]
        ]
        return deepcopy(min(entries, key=lambda item: item["ts"])) if entries else None

    def forget_conversation(self, conversation_id):
        for thread in self.threads.values():
            if thread["conversation_id"] == conversation_id:
                thread["deleted"] = True
        self.answers = {
            key: answer
            for key, answer in self.answers.items()
            if answer.get("conversation_id") != conversation_id
        }

    def save_answer(self, payload, answer_id=None):
        answer_id = answer_id or f"answer-{len(self.answers) + 1}"
        self.answers[answer_id] = deepcopy(payload)
        return answer_id

    def answer(self, answer_id):
        return deepcopy(self.answers.get(answer_id))

    def track_card(self, request_id, channel, ts, answer_id=""):
        self.request_cards[channel, ts] = {
            "request_id": request_id,
            "channel": channel,
            "ts": ts,
            "answer_id": answer_id,
        }

    def cards(self, request_id):
        return deepcopy(
            [card for card in self.request_cards.values() if card["request_id"] == request_id]
        )

    def remove_card(self, channel, ts):
        self.request_cards.pop((channel, ts), None)

    def snapshot(self, request_id):
        return deepcopy(self.snapshots.get(request_id))

    def remember_request(self, detail, notification=None):
        self.snapshots[detail["request"]["id"]] = deepcopy(detail)
        if notification:
            key, payload = notification
            self.notifications.setdefault(key, {**deepcopy(payload), "state": "pending"})

    def pending_notifications(self):
        return [
            {"id": key, **deepcopy(payload)}
            for key, payload in self.notifications.items()
            if payload["state"] == "pending"
        ]

    def notification_state(self, key, state):
        self.notifications[key]["state"] = state

    def save_delivery(self, channel, ts, text, blocks):
        self.pending_updates[channel, ts] = deepcopy(
            {
                "channel": channel,
                "ts": ts,
                "text": text,
                "blocks": blocks,
            }
        )

    def deliveries(self):
        return deepcopy(list(self.pending_updates.values()))

    def delivered(self, channel, ts):
        self.pending_updates.pop((channel, ts), None)


class FakeAPI:
    """Keep fake backend persistence independent from Slack delivery and caches."""

    def __init__(self):
        self.chat_calls = []
        self.saved_history = {}
        self.request_details = {}
        self.feedback_attempts = []
        self.saved_ratings = []
        self.feedback_errors = []
        self.chat_outcome = "grounded"
        self.cancel_calls = []
        self.delete_calls = []

    def stream_chat(self, text, conversation_id=None):
        self.chat_calls.append((text, conversation_id))
        conversation_id = conversation_id or f"conversation-{len(self.saved_history) + 1}"
        answer = HR_BACKEND_ANSWER if self.chat_outcome == "handoff_demo" else POLICY_ANSWER
        sources = [] if self.chat_outcome == "handoff_demo" else deepcopy(SOURCES)
        yield {"type": "start"}
        yield {"type": "token", "content": answer}
        # The real API persists both messages before sending its complete event.
        messages = self.saved_history.setdefault(conversation_id, [])
        messages.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": answer, "sources": sources},
            ]
        )
        yield {
            "type": "complete",
            "conversation_id": conversation_id,
            "outcome_code": self.chat_outcome,
            "intent": "work",
            "language": "en",
            "sources": sources,
            "workflow_request": None,
        }

    def conversations(self):
        return [
            {"id": key, "title": messages[0]["content"], "message_count": len(messages)}
            for key, messages in self.saved_history.items()
        ]

    def conversation(self, conversation_id):
        messages = deepcopy(self.saved_history[conversation_id])
        for index, message in enumerate(messages):
            message.setdefault("id", f"{conversation_id}-message-{index}")
        return {
            "conversation": {
                "id": conversation_id,
                "title": messages[0]["content"],
                "message_count": len(messages),
            },
            "messages": messages,
        }

    def requests(self):
        return [deepcopy(detail["request"]) for detail in self.request_details.values()]

    def request(self, request_id):
        return deepcopy(self.request_details[request_id])

    def cancel_request(self, request_id):
        self.cancel_calls.append(request_id)
        detail = self.request_details[request_id]
        previous = detail["request"]["status"]
        detail["request"]["status"] = "cancelled"
        detail["events"].append(
            {
                "id": f"{request_id}-cancelled",
                "from_status": previous,
                "to_status": "cancelled",
                "actor": "employee.demo",
                "details": {},
                "created_at": "2026-09-06T10:05:00Z",
            }
        )
        return deepcopy(detail)

    def delete_conversation(self, conversation_id):
        self.delete_calls.append(conversation_id)
        del self.saved_history[conversation_id]

    def feedback(self, question, answer, rating, comment=""):
        payload = {"question": question, "answer": answer, "rating": rating, "comment": comment}
        self.feedback_attempts.append(deepcopy(payload))
        if self.feedback_errors:
            raise self.feedback_errors.pop(0)
        self.saved_ratings.append(deepcopy(payload))
        return {"feedback": {"id": f"feedback-{len(self.saved_ratings)}", **payload}}

    def close(self):
        pass


class FakeSlack:
    def __init__(self):
        self.posts = []
        self.update_attempts = []
        self.updates = []
        self.home_views = []
        self.modal_updates = []
        self.messages = {}
        self.fail_updates = 0
        self.dm_errors = []
        self.post_errors = []
        self.permalink_calls = []

    def conversations_open(self, *, users):
        assert users == EMPLOYEE
        if self.dm_errors:
            raise self.dm_errors.pop(0)
        return {"channel": {"id": CHANNEL}}

    def chat_postMessage(self, **payload):
        assert payload["channel"] == CHANNEL, "Employee output must stay in the app DM."
        if self.post_errors:
            raise self.post_errors.pop(0)
        ts = f"1700000001.{len(self.posts) + 1:06d}"
        self.posts.append(deepcopy(payload))
        self.messages[payload["channel"], ts] = deepcopy(payload)
        return {"ok": True, "channel": payload["channel"], "ts": ts}

    def chat_update(self, **payload):
        self.update_attempts.append(deepcopy(payload))
        if self.fail_updates:
            self.fail_updates -= 1
            raise SlackApiError("Known Slack rejection", {"ok": False, "error": "ratelimited"})
        key = payload["channel"], payload["ts"]
        assert key in self.messages, "Retry must update the original response message."
        self.messages[key].update(deepcopy(payload))
        self.updates.append(deepcopy(payload))
        return {"ok": True, "channel": key[0], "ts": key[1]}

    def views_publish(self, **payload):
        assert payload["user_id"] == EMPLOYEE
        self.home_views.append(deepcopy(payload))
        return {"ok": True}

    def views_update(self, **payload):
        self.modal_updates.append(deepcopy(payload))
        return {"ok": True, "view": {"id": payload["view_id"]}}

    def chat_getPermalink(self, *, channel, message_ts):
        assert channel == CHANNEL
        self.permalink_calls.append((channel, message_ts))
        return {
            "ok": True,
            "permalink": f"https://peopleflow-demo.slack.com/archives/{channel}/p{message_ts.replace('.', '')}",
        }


@pytest.fixture
def app(monkeypatch):
    # No token preview should consume the failure intended for the final update.
    monkeypatch.setattr(chat, "time", SimpleNamespace(monotonic=lambda: 100.0))
    service = EmployeeApp(
        SimpleNamespace(employee_user_id=EMPLOYEE, team_id="TDEMO", app_id="ADEMO", api_timeout=1),
        FakeAPI(),
        FakeStore(),
        FakeSlack(),
    )
    yield service
    service.close()


@pytest.mark.parametrize("new_message", [False, True])
def test_final_answer_delivery_retries_on_poll_without_repeating_backend_chat(app, new_message):
    app.slack.fail_updates = 1
    app.queue(
        app.ask, "How do I plan time off?", CHANNEL, THREAD, "event-policy", new_message
    ).result(2)

    assert len(app.api.chat_calls) == 1
    assert len(app.slack.update_attempts) == 1
    assert not app.slack.updates
    assert len(app.slack.posts) == 1
    assert "Thinking" in app.slack.posts[0]["text"]
    assert len(app.store.deliveries()) == 1, "Saved answer needs pending Slack delivery."
    assert len(app.api.saved_history["conversation-1"]) == 2

    app.poll_once()

    assert len(app.slack.updates) == 1
    delivered = app.slack.updates[0]
    assert POLICY_ANSWER in delivered["text"]
    assert POLICY_ANSWER in block_text(delivered["blocks"])
    assert "Sources: Leave policy" in block_text(delivered["blocks"])
    assert (delivered["channel"], delivered["ts"]) == next(iter(app.slack.messages))
    assert app.slack.messages[CHANNEL, delivered["ts"]].get("thread_ts") == (
        None if new_message else THREAD
    )
    assert not app.store.deliveries()

    # Both another poll and Slack redelivery must be harmless after recovery.
    app.poll_once()
    app.ask("How do I plan time off?", CHANNEL, THREAD, "event-policy", new_message)
    assert len(app.api.chat_calls) == 1
    assert len(app.api.saved_history["conversation-1"]) == 2
    assert len(app.slack.posts) == 1
    assert len(app.slack.updates) == 1


@pytest.mark.parametrize(
    "question",
    [
        "I need help from HR",
        "  I   need\thelp\nfrom HR?!  ",
        "  CONTACT   HR!  ",
    ],
)
def test_hr_demo_is_saved_by_backend_and_never_publishes_an_unqualified_ticket_promise(
    app,
    monkeypatch,
    question,
):
    # Both streaming previews and the final render must use the same backend answer.
    ticks = iter(range(0, 100, 2))
    monkeypatch.setattr(chat, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    app.api.chat_outcome = "handoff_demo"

    app.ask(question, CHANNEL, THREAD, "event-hr")

    assert len(app.api.chat_calls) == 1, "HR demo must use the existing saved chat flow."
    saved = app.api.saved_history["conversation-1"]
    assert [message["role"] for message in saved] == ["user", "assistant"]
    assert saved[0]["content"] == app.api.chat_calls[0][0]
    assert " ".join(saved[0]["content"].split()).lower() == " ".join(question.split()).lower()
    assert saved[1]["content"] == HR_BACKEND_ANSWER
    assert app.store.thread(CHANNEL, THREAD)["conversation_id"] == "conversation-1"
    assert app.slack.updates, "The backend result must become a visible employee reply."

    for payload in [*app.slack.posts, *app.slack.updates]:
        for text in (payload["text"], block_text(payload.get("blocks", []))):
            if "private hr support request" in text.lower():
                assert "demo" in text.lower()
                assert "no hr ticket" in text.lower()
    final = app.slack.updates[-1]
    assert final["text"] == saved[1]["content"]
    for text in (final["text"], block_text(final["blocks"])):
        assert "demo" in text.lower()
        assert "no hr ticket" in text.lower()

    app.ask(question, CHANNEL, THREAD, "event-hr")
    assert len(app.api.chat_calls) == 1
    assert len(app.api.saved_history["conversation-1"]) == 2


@pytest.mark.parametrize(("rating", "comment"), [(5, ""), (1, "Please include the policy date.")])
def test_known_feedback_failure_can_retry_once_without_duplicate_rating(app, rating, comment):
    answer_id, ts = seed_visible_answer(app)
    app.api.feedback_errors.append(APIError(503, "Could not connect.", uncertain=False))

    app.rate(answer_id, rating, comment)
    assert len(app.api.feedback_attempts) == 1
    assert not app.api.saved_ratings
    assert app.store.operation(f"feedback:{answer_id}")["state"] == "failed"
    messages_after_failure = len(app.slack.posts)

    app.rate(answer_id, rating, comment)
    expected = {
        "question": "How do I plan time off?",
        "answer": POLICY_ANSWER,
        "rating": rating,
        "comment": comment,
    }
    assert app.api.feedback_attempts == [expected, expected]
    assert app.api.saved_ratings == [expected]
    assert app.store.operation(f"feedback:{answer_id}")["state"] == "complete"
    assert all(post["thread_ts"] == THREAD for post in app.slack.posts)
    assert len(app.slack.posts) == messages_after_failure, (
        "Successful retry updates the answer only."
    )
    card = app.slack.messages[CHANNEL, ts]["blocks"]
    assert "Feedback saved" in block_text(card)
    assert "feedback_helpful" not in action_ids(card)
    assert "feedback_unhelpful" not in action_ids(card)
    assert not action_ids(card)

    app.rate(answer_id, rating, comment)
    app.rate(answer_id, 1 if rating == 5 else 5, "Another click on the same answer")
    assert len(app.api.feedback_attempts) == 2
    assert app.api.saved_ratings == [expected]


@pytest.mark.parametrize("with_separate_comment", [False, True])
def test_decline_notification_uses_decision_event_comment_and_is_not_repeated(
    app,
    with_separate_comment,
):
    request = {
        "id": "request-1",
        "type": "pto",
        "type_label": "PTO",
        "status": "in_review",
        "start_date": "2026-09-14",
        "end_date": "2026-09-16",
        "duration_days": 3,
        "comment": "Planned time off; handoff is ready.",
        "details": {},
        "applicant": "employee.demo",
        "approver": "manager.demo",
    }
    detail = {
        "request": request,
        "events": [
            {
                "id": "event-submitted",
                "to_status": "in_review",
                "actor": "employee.demo",
                "details": {},
                "created_at": "2026-09-06T10:00:00Z",
            }
        ],
        "comments": [],
    }
    separate_comment = "Earlier discussion: handoff details look complete."
    if with_separate_comment:
        detail["comments"].append(
            {
                "id": "comment-1",
                "author": "manager.demo",
                "body": separate_comment,
                "created_at": "2026-09-06T09:59:00Z",
            }
        )
    app.api.request_details[request["id"]] = detail
    app.poll_once()
    assert not app.slack.posts, "Startup should establish a baseline without old-request DMs."

    reason = "Coverage is unavailable for those dates; please choose the following week."
    detail["request"]["status"] = "declined"
    detail["events"].append(
        {
            "id": "event-declined",
            "from_status": "in_review",
            "to_status": "declined",
            "actor": "manager.demo",
            "details": {"comment": reason},
            "created_at": "2026-09-06T10:01:00Z",
        }
    )
    app.poll_once()

    assert len(app.slack.posts) == 1
    notice = app.slack.posts[0]
    visible = block_text(notice["blocks"])
    assert "declined" in visible.lower()
    assert reason in visible, "Decision reason lives in events[].details.comment, not comments[]."
    if with_separate_comment:
        assert separate_comment not in visible, (
            "Do not repeat old comments in a short decision notice."
        )
    assert not app.store.pending_notifications()

    app.poll_once()
    assert len(app.slack.posts) == 1, "An unchanged decision must not send another notification."


def request_detail(status="in_review", request_id="request-1"):
    return {
        "request": {
            "id": request_id,
            "type": "pto",
            "type_label": "PTO",
            "status": status,
            "start_date": "2026-09-14",
            "end_date": "2026-09-16",
            "duration_days": 3,
            "comment": "Planned time off; handoff is ready.",
            "details": {},
            "applicant": "employee.demo",
            "approver": "manager.demo",
        },
        "events": [
            {
                "id": f"{request_id}-{status}",
                "to_status": status,
                "actor": "manager.demo" if status == "approved" else "employee.demo",
                "details": {},
                "created_at": "2026-09-06T10:00:00Z",
            }
        ],
        "comments": [],
    }


def seed_request_card(app, detail):
    request = detail["request"]
    receipt = app.post(
        f"PTO: {request['status']}",
        views.request_blocks(request),
        thread_ts=THREAD,
    )
    app.store.track_card(request["id"], CHANNEL, receipt["ts"])
    app.store.remember_request(detail)
    app.store.set("initialized", True)
    return receipt["ts"]


def test_poll_uses_fresh_detail_when_request_changes_after_list_read(app, monkeypatch):
    before = request_detail()
    ts = seed_request_card(app, before)
    after = request_detail("approved")
    app.api.request_details["request-1"] = after
    # Manager approves between GET /requests and GET /requests/{id}.
    monkeypatch.setattr(app.api, "requests", lambda: [deepcopy(before["request"])])

    app.poll_once()
    monkeypatch.setattr(app.api, "requests", lambda: [deepcopy(after["request"])])
    app.poll_once()

    visible = block_text(app.slack.messages[CHANNEL, ts]["blocks"])
    assert "Approved" in visible, "A fresh snapshot must not leave the older card In review."
    assert "Cancel request" not in visible


def test_pending_old_delivery_cannot_overwrite_a_newer_request_status(app):
    before = request_detail()
    ts = seed_request_card(app, before)
    # A prior response update was queued while the request was still In review.
    app.store.save_delivery(CHANNEL, ts, "PTO: in_review", views.request_blocks(before["request"]))
    app.api.request_details["request-1"] = request_detail("approved")
    # On this poll, replay fails but refreshing the current API status can succeed.
    app.slack.fail_updates = 1
    app.poll_once()
    app.poll_once()

    visible = block_text(app.slack.messages[CHANNEL, ts]["blocks"])
    assert "Approved" in visible, "A queued older render must never roll back the visible decision."
    assert "Cancel request" not in visible
    assert not app.store.deliveries()


def test_notification_retries_when_opening_dm_fails_before_message_send(app):
    app.store.set("initialized", True)
    app.api.request_details["request-1"] = request_detail("approved")
    app.slack.dm_errors.append(OSError("Connection interrupted while opening DM"))

    app.queue(app.poll_once).result(2)
    assert not app.slack.posts
    assert len(app.store.pending_notifications()) == 1, "No message send was attempted yet."

    app.poll_once()
    assert len(app.slack.posts) == 1
    assert "approved" in block_text(app.slack.posts[0]["blocks"]).lower()
    assert not app.store.pending_notifications()
    app.poll_once()
    assert len(app.slack.posts) == 1


def test_history_hr_demo_remains_honest_without_persisted_outcome_code(app):
    # The current conversation-read API omits outcome_code from saved messages.
    app.api.saved_history["conversation-hr"] = [
        {"role": "user", "content": "I need help from HR"},
        {"role": "assistant", "content": HR_BACKEND_ANSWER, "sources": []},
    ]

    app.show_detail("view-history", "open_conversation", "conversation-hr")

    visible = block_text(app.slack.modal_updates[-1]["view"]).lower()
    assert "demo" in visible and "no hr ticket" in visible
    assert "i’ve opened a private hr support request" not in visible
    assert app.api.saved_history["conversation-hr"][1]["content"] == HR_BACKEND_ANSWER


def test_background_refresh_preserves_selected_home_section_and_page(app):
    for index in range(12):
        identity = f"request-{index}"
        app.api.request_details[identity] = request_detail(request_id=identity)
    app.home("requests", 1)
    selected = json.loads(app.slack.home_views[-1]["view"]["private_metadata"])
    assert selected == {"section": "requests", "page": 1}

    app.ask("How do I plan time off?", CHANNEL, THREAD, "event-preserve-home")
    after_answer = json.loads(app.slack.home_views[-1]["view"]["private_metadata"])
    assert after_answer == selected

    app.store.set("initialized", True)
    app.api.request_details["request-0"] = request_detail("approved", "request-0")
    app.poll_once()
    after_poll = json.loads(app.slack.home_views[-1]["view"]["private_metadata"])
    assert after_poll == selected


def test_uncertain_feedback_is_not_retried_as_a_known_failure(app):
    answer_id, _ = seed_visible_answer(app)
    app.api.feedback_errors.append(APIError(504, "Response lost after send.", uncertain=True))

    app.rate(answer_id, 5)
    app.rate(answer_id, 5)

    assert len(app.api.feedback_attempts) == 1
    assert app.store.operation(f"feedback:{answer_id}")["state"] == "uncertain"


def seed_visible_answer(app, *, request=None):
    app.api.saved_history["conversation-1"] = [
        {"role": "user", "content": "How do I plan time off?"},
        {"role": "assistant", "content": POLICY_ANSWER, "sources": SOURCES},
    ]
    receipt = app.post(
        POLICY_ANSWER,
        views.answer_blocks(POLICY_ANSWER, SOURCES),
        thread_ts=THREAD,
    )
    answer_id = app.store.save_answer(
        {
            "question": "How do I plan time off?",
            "answer": POLICY_ANSWER,
            "sources": SOURCES,
            "conversation_id": "conversation-1",
            "channel": CHANNEL,
            "thread_ts": THREAD,
            "ts": receipt["ts"],
            "request_id": request["id"] if request else None,
        }
    )
    if request:
        app.store.track_card(request["id"], CHANNEL, receipt["ts"], answer_id)
    return answer_id, receipt["ts"]


def test_saved_feedback_card_recovers_from_slack_failure_without_reposting_rating(app):
    answer_id, ts = seed_visible_answer(app)
    app.slack.fail_updates = 1
    # Feedback is acknowledged on the existing answer, including after a failed update.
    previous_posts = len(app.slack.posts)
    app.queue(app.rate, answer_id, 5).result(2)

    assert len(app.api.saved_ratings) == 1
    assert app.store.operation(f"feedback:{answer_id}")["state"] == "complete"
    assert app.store.deliveries()
    app.poll_once()

    card = app.slack.messages[CHANNEL, ts]
    assert POLICY_ANSWER in block_text(card["blocks"])
    assert "feedback_helpful" not in action_ids(card["blocks"])
    assert "feedback_unhelpful" not in action_ids(card["blocks"])
    assert "feedback" in block_text(card["blocks"]).lower()
    assert not action_ids(card["blocks"])
    assert not app.store.deliveries()

    app.rate(answer_id, 5)
    app.poll_once()
    assert len(app.api.feedback_attempts) == 1
    assert len(app.api.saved_ratings) == 1
    assert len(app.slack.posts) == previous_posts, "Do not add a redundant feedback thanks DM."


def test_feedback_receipt_read_failure_does_not_allow_duplicate_backend_rating(app, monkeypatch):
    detail = request_detail()
    app.api.request_details["request-1"] = detail
    answer_id, _ = seed_visible_answer(app, request=detail["request"])
    read_request = app.api.request
    failures = [APIError(503, "Cannot refresh request right now.", uncertain=False)]

    def temporarily_unavailable(request_id):
        if failures:
            raise failures.pop(0)
        return read_request(request_id)

    monkeypatch.setattr(app.api, "request", temporarily_unavailable)
    app.queue(app.rate, answer_id, 5).result(2)
    assert len(app.api.saved_ratings) == 1

    app.queue(app.rate, answer_id, 5).result(2)
    assert len(app.api.feedback_attempts) == 1, (
        "A receipt GET failure must not retry a saved rating."
    )
    assert len(app.api.saved_ratings) == 1
    assert app.store.operation(f"feedback:{answer_id}")["state"] == "complete"


def test_feedback_saved_state_survives_request_status_refresh(app):
    detail = request_detail()
    app.api.request_details["request-1"] = detail
    app.store.remember_request(detail)
    app.store.set("initialized", True)
    answer_id, ts = seed_visible_answer(app, request=detail["request"])
    app.rate(answer_id, 5)
    assert "feedback_helpful" not in action_ids(app.slack.messages[CHANNEL, ts]["blocks"])

    app.api.request_details["request-1"] = request_detail("approved")
    app.poll_once()

    card = app.slack.messages[CHANNEL, ts]
    assert "Approved" in block_text(card["blocks"])
    assert "feedback_helpful" not in action_ids(card["blocks"])
    assert "feedback_unhelpful" not in action_ids(card["blocks"])
    assert not action_ids(card["blocks"])
    assert len(app.api.saved_ratings) == 1


@pytest.mark.parametrize("subtype", [None, "file_share"])
def test_unsupported_file_input_is_not_replayed_as_a_question_after_restart(app, subtype):
    # on_message rejects uploads before asking, regardless of an optional subtype.
    # Persisting a different action here would silently run it during recovery.
    event = {
        "type": "message",
        "channel_type": "im",
        "user": EMPLOYEE,
        "channel": CHANNEL,
        "ts": THREAD,
        "text": "Please use this attached file to request my time off.",
        "files": [{"id": "FATTACHMENT"}],
    }
    if subtype:
        event["subtype"] = subtype
    body = {"type": "event_callback", "team_id": "TDEMO", "event_id": "event-file", "event": event}

    assert normalize_action(body, app) is None
    assert not app.api.chat_calls


@pytest.mark.parametrize("kind,status", [("sick_leave", "reported"), ("pto", "in_review")])
@pytest.mark.parametrize("poll_fails", [False, True])
def test_cancel_refreshes_the_open_request_modal_and_removes_cancel_control(
    app, monkeypatch, kind, status, poll_fails
):
    detail = request_detail(status)
    if kind == "sick_leave":
        detail["request"].update(
            type="sick_leave",
            type_label="Sick leave",
            details={
                "time_away": "full_day",
                "expected_return_date": "2026-09-17",
                "expected_return_unknown": False,
            },
        )
    app.api.request_details["request-1"] = deepcopy(detail)
    app.store.remember_request(detail)
    app.store.set("initialized", True)
    view_id = "VOPENREQUEST"
    app.show_detail(view_id, "open_request", "request-1")
    before = app.slack.modal_updates[-1]["view"]
    assert "cancel_request" in action_ids(before)
    assert ("Reported" if kind == "sick_leave" else "In review") in block_text(before)
    previous_updates = len(app.slack.modal_updates)
    failed_reads = []
    if poll_fails:

        def unavailable_requests():
            failed_reads.append(True)
            raise APIError(503, "Request-list refresh is temporarily unavailable.", uncertain=False)

        monkeypatch.setattr(app.api, "requests", unavailable_requests)

    app.queue(app.cancel, "request-1", "action-cancel-modal", view_id).result(2)

    assert app.api.cancel_calls == ["request-1"]
    assert app.api.request_details["request-1"]["request"]["status"] == "cancelled"
    assert failed_reads == ([True] if poll_fails else [])
    assert app.store.operation("action-cancel-modal")["state"] == "complete", (
        "A subsequent polling failure cannot turn a confirmed cancellation into a failed mutation."
    )
    assert len(app.slack.modal_updates) == previous_updates + 1
    refreshed = app.slack.modal_updates[-1]
    assert refreshed["view_id"] == view_id, "Update the existing modal, not only Home or a DM."
    assert refreshed["view"]["callback_id"] == "request_detail"
    assert "Cancelled" in block_text(refreshed["view"])
    assert "cancel_request" not in action_ids(refreshed["view"])
    assert "edit_request" not in action_ids(refreshed["view"])
    assert json.loads(refreshed["view"]["private_metadata"])["request_id"] == "request-1"

    app.cancel("request-1", "action-cancel-modal", view_id)
    assert app.api.cancel_calls == ["request-1"]


def test_delete_replaces_the_open_conversation_modal_with_deleted_notice(app):
    app.api.saved_history["conversation-1"] = [
        {"role": "user", "content": "How do I plan time off?"},
        {"role": "assistant", "content": POLICY_ANSWER, "sources": SOURCES},
    ]
    app.store.bind(CHANNEL, THREAD, "conversation-1")
    app.api.request_details["request-1"] = request_detail()
    view_id = "VOPENCONVERSATION"
    app.show_detail(view_id, "open_conversation", "conversation-1")
    before = app.slack.modal_updates[-1]["view"]
    assert "delete_conversation" in action_ids(before)
    assert "open_slack_conversation" in action_ids(before)
    assert POLICY_ANSWER in block_text(before)
    previous_updates = len(app.slack.modal_updates)

    app.queue(app.delete, "conversation-1", "action-delete-modal", view_id).result(2)

    assert app.api.delete_calls == ["conversation-1"]
    assert "conversation-1" not in app.api.saved_history
    assert app.store.operation("action-delete-modal")["state"] == "complete"
    assert app.store.thread(CHANNEL, THREAD)["deleted"] is True
    assert len(app.slack.modal_updates) == previous_updates + 1
    refreshed = app.slack.modal_updates[-1]
    assert refreshed["view_id"] == view_id, "Replace the open conversation, not only its Home row."
    assert refreshed["view"]["title"]["text"] == "Conversation deleted"
    visible = block_text(refreshed["view"])
    assert "Conversation deleted from PeopleFlow" in visible
    assert "Slack messages and your requests remain" in visible
    assert POLICY_ANSWER not in visible
    assert "delete_conversation" not in action_ids(refreshed["view"])
    assert "continue_conversation" not in action_ids(refreshed["view"])
    assert "open_slack_conversation" not in action_ids(refreshed["view"])
    assert app.api.request_details["request-1"] == request_detail()

    app.delete("conversation-1", "action-delete-modal", view_id)
    assert app.api.delete_calls == ["conversation-1"]


def test_first_dm_answer_is_visible_and_both_reply_roots_keep_the_same_history(app):
    question = "How do I plan time off?"
    app.ask(question, CHANNEL, THREAD, "event-first-visible", new_message=True)

    assert len(app.slack.posts) == 1
    assert app.slack.posts[0].get("thread_ts") is None, (
        "The first answer must be visible in Messages."
    )
    answer_ts = app.slack.updates[-1]["ts"]
    assert POLICY_ANSWER in block_text(app.slack.messages[CHANNEL, answer_ts]["blocks"])
    assert app.store.thread(CHANNEL, THREAD)["conversation_id"] == "conversation-1"
    assert app.store.thread(CHANNEL, answer_ts)["conversation_id"] == "conversation-1"

    # A new service instance must use stored aliases, not an in-process active chat.
    resumed = EmployeeApp(app.settings, app.api, app.store, app.slack)
    try:
        resumed.ask("Continue under your answer", CHANNEL, answer_ts, "event-bot-root")
        resumed.ask("Continue under my question", CHANNEL, THREAD, "event-user-root")
    finally:
        resumed.close()

    assert app.api.chat_calls == [
        (question, None),
        ("Continue under your answer", "conversation-1"),
        ("Continue under my question", "conversation-1"),
    ]
    assert list(app.api.saved_history) == ["conversation-1"]
    assert len(app.api.saved_history["conversation-1"]) == 6
    assert [post.get("thread_ts") for post in app.slack.posts] == [None, answer_ts, THREAD]


def test_shortcut_creates_one_answer_root_without_a_question_echo(app):
    question = "When should I plan my time off?"
    app.ask_new(question, "question-single-root")

    assert app.api.chat_calls == [(question, None)]
    assert len(app.slack.posts) == 1, (
        "A shortcut must not post a question root plus a hidden reply."
    )
    assert app.slack.posts[0].get("thread_ts") is None
    answer_ts = app.slack.updates[-1]["ts"]
    answer = app.slack.messages[CHANNEL, answer_ts]
    assert question in block_text(answer["blocks"]), "Retain the shortcut question on its answer."
    assert POLICY_ANSWER in block_text(answer["blocks"])
    assert app.store.thread(CHANNEL, answer_ts)["conversation_id"] == "conversation-1"

    app.ask_new(question, "question-single-root")
    assert len(app.slack.posts) == 1
    app.ask("And for a longer vacation?", CHANNEL, answer_ts, "event-shortcut-follow-up")
    assert app.api.chat_calls[-1] == ("And for a longer vacation?", "conversation-1")
    assert app.slack.posts[-1]["thread_ts"] == answer_ts
    assert len(app.api.saved_history["conversation-1"]) == 4


def test_saved_chat_link_points_to_original_answer_after_a_new_service_instance(app):
    app.ask("How do I plan time off?", CHANNEL, THREAD, "event-chat-link", new_message=True)
    answer_ts = app.slack.updates[-1]["ts"]
    original_link = app.conversation_link("conversation-1")
    assert original_link and app.slack.permalink_calls == [(CHANNEL, answer_ts)]
    previous_posts = len(app.slack.posts)

    resumed = EmployeeApp(app.settings, app.api, app.store, app.slack)
    try:
        resumed.show_detail("VSAVEDCHAT", "open_conversation", "conversation-1")
        assert original_link in json.dumps(app.slack.modal_updates[-1]["view"])
        assert resumed.conversation_link("conversation-1") == original_link
    finally:
        resumed.close()

    assert len(app.slack.posts) == previous_posts, (
        "Opening history must not create another chat root."
    )
    assert app.slack.permalink_calls == [(CHANNEL, answer_ts)]
    assert len(app.api.chat_calls) == 1


@pytest.mark.parametrize("rating", [1, 5])
def test_successful_feedback_updates_the_answer_without_an_extra_dm(app, rating):
    answer_id, ts = seed_visible_answer(app)
    previous_posts = len(app.slack.posts)

    app.rate(answer_id, rating, "Please keep the planning example.")
    app.rate(answer_id, rating)

    card = app.slack.messages[CHANNEL, ts]["blocks"]
    assert len(app.api.saved_ratings) == 1
    assert len(app.api.feedback_attempts) == 1
    assert len(app.slack.posts) == previous_posts
    assert "Feedback saved" in block_text(card)
    assert POLICY_ANSWER in block_text(card)
    assert not action_ids(card)
    assert "feedback_helpful" not in action_ids(card)
    assert "feedback_unhelpful" not in action_ids(card)


def test_manager_updates_keep_one_receipt_and_leave_short_notifications_unchanged(app):
    app.store.set("initialized", True)
    app.api.request_details["request-1"] = request_detail()
    app.poll_once()
    assert len(app.slack.posts) == 1
    cards = app.store.cards("request-1")
    assert len(cards) == 1
    receipt_key = cards[0]["channel"], cards[0]["ts"]

    app.api.request_details["request-1"] = request_detail("approved")
    app.poll_once()
    assert len(app.slack.posts) == 2, "One short decision accompanies the existing receipt update."
    status_key = next(key for key in app.slack.messages if key != receipt_key)
    status_message = deepcopy(app.slack.messages[status_key])
    assert "approved" in block_text(status_message["blocks"]).lower()
    assert "Planning note" not in block_text(status_message["blocks"])
    assert app.store.cards("request-1") == cards
    assert "Approved" in block_text(app.slack.messages[receipt_key]["blocks"])

    note = {
        "id": "manager-note-1",
        "author": "manager.demo",
        "body": "Your handoff is confirmed. Enjoy your time off.",
        "created_at": "2026-09-06T10:10:00Z",
    }
    app.api.request_details["request-1"]["comments"].append(note)
    app.poll_once()
    assert len(app.slack.posts) == 3
    comment = app.slack.posts[-1]
    assert note["body"] in block_text(comment["blocks"])
    assert "Planning note" not in block_text(comment["blocks"])
    assert "cancel_request" not in action_ids(comment["blocks"])
    assert app.store.cards("request-1") == cards
    assert app.slack.messages[status_key] == status_message, "A decision is not another live card."

    app.poll_once()
    assert len(app.slack.posts) == 3


@pytest.mark.parametrize("local_cancel", [True, False])
def test_local_cancel_is_quiet_but_external_cancel_notifies(app, local_cancel):
    detail = request_detail()
    app.api.request_details["request-1"] = detail
    ts = seed_request_card(app, detail)
    previous_posts = len(app.slack.posts)
    if local_cancel:
        app.cancel("request-1", "action-local-cancel")
    else:
        # The same employee cancels through the web API, outside the Slack action.
        app.api.cancel_request("request-1")
        app.poll_once()

    app.poll_once()
    assert len(app.slack.posts) == previous_posts + (0 if local_cancel else 1)
    assert "Cancelled" in block_text(app.slack.messages[CHANNEL, ts]["blocks"])
    assert "cancel_request" not in action_ids(app.slack.messages[CHANNEL, ts]["blocks"])
    assert len(app.store.cards("request-1")) == 1
    if not local_cancel:
        assert "cancelled" in block_text(app.slack.posts[-1]["blocks"]).lower()


def test_metadata_changes_and_noop_polls_do_not_send_notifications(app):
    app.store.set("initialized", True)
    app.api.request_details["request-1"] = request_detail()
    app.poll_once()
    previous_posts = len(app.slack.posts)
    assert previous_posts == 1

    app.api.request_details["request-1"]["request"]["updated_at"] = "2026-09-06T10:20:00Z"
    app.api.request_details["request-1"]["request"]["validation_errors"] = []
    app.poll_once()
    app.poll_once()

    assert len(app.slack.posts) == previous_posts
    assert not app.store.pending_notifications()
    assert len(app.store.cards("request-1")) == 1


@pytest.mark.parametrize("failure", ["open_dm", "known_post_failure"])
def test_delayed_first_receipt_uses_current_status_after_a_manager_decision(app, failure):
    app.store.set("initialized", True)
    app.api.request_details["request-1"] = request_detail()
    if failure == "open_dm":
        app.slack.dm_errors.append(ConnectionError("DM unavailable before send"))
    else:
        app.slack.post_errors.append(
            SlackApiError("Known Slack rejection", {"ok": False, "error": "ratelimited"})
        )
    app.queue(app.poll_once).result(2)
    assert not app.slack.posts
    assert len(app.store.pending_notifications()) == 1

    app.api.request_details["request-1"] = request_detail("approved")
    app.poll_once()
    app.poll_once()

    cards = app.store.cards("request-1")
    assert len(cards) == 1
    card = app.slack.messages[cards[0]["channel"], cards[0]["ts"]]
    assert "Approved" in block_text(card["blocks"]), (
        "A queued receipt must not publish its old In review snapshot after approval."
    )
    assert "cancel_request" not in action_ids(card["blocks"])
    assert not app.store.pending_notifications()
    assert not app.store.deliveries()
