"""Deletion reconciliation uses only temporary transport state, never backend storage."""

from peopleflow_slack.store import Store


def test_forgetting_deleted_history_clears_its_pointers_and_pending_copy(tmp_path):
    store = Store(tmp_path / "transport.db")
    store.bind("D1", "1", "deleted-chat")
    store.bind("D1", "2", "kept-chat")
    deleted_answer = store.save_answer(
        {"conversation_id": "deleted-chat", "channel": "D1", "ts": "3", "answer": "Old text"}
    )
    kept_answer = store.save_answer(
        {"conversation_id": "kept-chat", "channel": "D1", "ts": "4", "answer": "Kept text"}
    )
    removed_keys = {
        "active_conversation:D1": "deleted-chat",
        "latest_answer:D1": deleted_answer,
        "latest_answer:D1:1": deleted_answer,
        "conversation_entry:deleted-chat": {"channel": "D1", "ts": "1"},
        "conversation_link:deleted-chat": "https://slack.invalid/deleted-chat",
        "request_for_conversation:deleted-chat": "surviving-request",
    }
    for key, value in removed_keys.items():
        store.set(key, value)
    store.set("active_conversation:D2", "kept-chat")
    store.set("latest_answer:D2", kept_answer)
    store.save_delivery("D1", "3", "Old text", [])
    store.save_delivery("D1", "4", "Kept text", [])
    store.track_card("surviving-request", "D1", "3", deleted_answer)
    detail = {"request": {"id": "surviving-request", "status": "in_review"}}
    store.remember_request(detail)
    assert store.claim("original-delivery")
    store.finish("original-delivery", payload={"answer_id": deleted_answer})

    store.forget_conversation("deleted-chat")
    store.forget_conversation("deleted-chat")

    assert store.thread("D1", "1")["deleted"] == 1
    assert store.thread("D1", "2")["deleted"] == 0
    assert store.answer(deleted_answer) is None
    assert store.answer(kept_answer)["answer"] == "Kept text"
    assert all(store.get(key) is None for key in removed_keys)
    assert store.get("active_conversation:D2") == "kept-chat"
    assert store.get("latest_answer:D2") == kept_answer
    assert [item["ts"] for item in store.deliveries()] == ["4"]
    assert store.cards("surviving-request")[0]["answer_id"] == ""
    assert store.snapshot("surviving-request") == detail
    assert not store.claim("original-delivery")
