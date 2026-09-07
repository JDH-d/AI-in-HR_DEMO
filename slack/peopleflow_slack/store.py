from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import RLock


class Store:
    """Slack transport state only. Business records are always read through HTTP."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS threads(
                    channel TEXT NOT NULL, ts TEXT NOT NULL, conversation_id TEXT,
                    deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(channel, ts));
                CREATE TABLE IF NOT EXISTS answers(
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cards(
                    request_id TEXT NOT NULL, channel TEXT NOT NULL, ts TEXT NOT NULL,
                    answer_id TEXT NOT NULL DEFAULT '', PRIMARY KEY(channel, ts));
                CREATE TABLE IF NOT EXISTS operations(
                    id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL,
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots(
                    request_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notifications(
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending');
                CREATE TABLE IF NOT EXISTS deliveries(
                    channel TEXT NOT NULL, ts TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(channel, ts));
                CREATE TABLE IF NOT EXISTS inbox(
                    id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS inbox_operation ON inbox(operation_id);
            """)

    @contextmanager
    def connection(self):
        with self._lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    def get(self, key, default=None):
        with self.connection() as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, json.dumps(value)))

    def bind(self, channel, ts, conversation_id):
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO threads VALUES (?,?,?,0)", (channel, ts, conversation_id)
            )

    def thread(self, channel, ts):
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM threads WHERE channel=? AND ts=?", (channel, ts)
            ).fetchone()
        return dict(row) if row else None

    def conversation_thread(self, conversation_id):
        """The first Slack entry point for a saved conversation, including older installs."""
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM threads WHERE conversation_id=? AND deleted=0 "
                "ORDER BY CAST(ts AS REAL) LIMIT 1",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def forget_conversation(self, conversation_id):
        """Forget confirmed-deleted backend history without deleting its surviving requests."""
        with self.connection() as db:
            db.execute("UPDATE threads SET deleted=1 WHERE conversation_id=?", (conversation_id,))
            # Remove cached source/feedback data too; original Slack messages remain in Slack.
            removed_answers = set()
            for row in db.execute("SELECT id,payload FROM answers").fetchall():
                answer = json.loads(row["payload"])
                if answer.get("conversation_id") == conversation_id:
                    removed_answers.add(row["id"])
                    db.execute("DELETE FROM answers WHERE id=?", (row["id"],))
                    db.execute("UPDATE cards SET answer_id='' WHERE answer_id=?", (row["id"],))
                    db.execute(
                        "DELETE FROM deliveries WHERE channel=? AND ts=?",
                        (answer.get("channel"), answer.get("ts")),
                    )
            exact_keys = {
                prefix + conversation_id
                for prefix in (
                    "conversation_entry:",
                    "conversation_link:",
                    "request_for_conversation:",
                )
            }
            for row in db.execute("SELECT key,value FROM metadata").fetchall():
                key, value = row["key"], json.loads(row["value"])
                linked = (
                    key in exact_keys
                    or (key.startswith("active_conversation:") and value == conversation_id)
                    or (
                        key.startswith("latest_answer:")
                        and isinstance(value, str)
                        and value in removed_answers
                    )
                )
                if linked:
                    db.execute("DELETE FROM metadata WHERE key=?", (key,))

    def save_answer(self, payload, answer_id=None):
        answer_id = answer_id or uuid.uuid4().hex
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO answers VALUES (?,?)", (answer_id, json.dumps(payload))
            )
        return answer_id

    def answer(self, answer_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM answers WHERE id=?", (answer_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def saved_answers(self):
        """Recent rendered messages owned by this integration, for presentation upgrades."""
        with self.connection() as db:
            rows = db.execute("SELECT id,payload FROM answers ORDER BY rowid DESC").fetchall()
        answers = [(row[0], json.loads(row[1])) for row in rows]
        return [
            (key, answer) for key, answer in answers if answer.get("channel") and answer.get("ts")
        ]

    def track_card(self, request_id, channel, ts, answer_id=""):
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO cards VALUES (?,?,?,?)",
                (request_id, channel, ts, answer_id),
            )

    def cards(self, request_id):
        with self.connection() as db:
            return [
                dict(r) for r in db.execute("SELECT * FROM cards WHERE request_id=?", (request_id,))
            ]

    def remove_card(self, channel, ts):
        with self.connection() as db:
            db.execute("DELETE FROM cards WHERE channel=? AND ts=?", (channel, ts))

    def claim(self, operation_id, retry_failed=False):
        """A repeated Slack delivery can never repeat a backend mutation."""
        with self.connection() as db:
            receipts = db.execute(
                "SELECT state FROM inbox WHERE operation_id=?", (operation_id,)
            ).fetchall()
            if receipts and not any(row[0] == "pending" for row in receipts):
                return False
            if retry_failed:
                db.execute("DELETE FROM operations WHERE id=? AND state='failed'", (operation_id,))
            return bool(
                db.execute(
                    "INSERT OR IGNORE INTO operations VALUES (?,'started','{}',?)",
                    (operation_id, time.time()),
                ).rowcount
            )

    def finish(self, operation_id, state="complete", payload=None):
        with self.connection() as db:
            db.execute(
                "UPDATE operations SET state=?,payload=? WHERE id=?",
                (state, json.dumps(payload or {}), operation_id),
            )
            if state not in {"started", "draft_created"}:
                db.execute(
                    "UPDATE inbox SET state=?,payload='{}' "
                    "WHERE operation_id=? AND state='pending'",
                    ("uncertain" if state == "uncertain" else "done", operation_id),
                )

    def receive_inbox(self, receipt_id, operation_id, kind, payload):
        """Commit the minimal action before Bolt may acknowledge its delivery.

        Receipt IDs deduplicate Slack deliveries; operation IDs also deduplicate
        different clicks for the same feedback. Only a *new* feedback delivery
        may retry an explicitly failed (never uncertain) previous attempt.
        """
        encoded = json.dumps(payload, allow_nan=False)
        with self.connection() as db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO inbox(id,operation_id,kind,payload,created) VALUES (?,?,?,?,?)",
                (receipt_id, operation_id, kind, encoded, time.time()),
            ).rowcount
            if not inserted:
                original = db.execute("SELECT * FROM inbox WHERE id=?", (receipt_id,)).fetchone()
                if (
                    original["operation_id"] != operation_id
                    or original["kind"] != kind
                    or (
                        original["state"] == "pending"
                        and json.loads(original["payload"]) != payload
                    )
                ):
                    raise ValueError("The action receipt does not match its original delivery.")
            if inserted:
                operation = db.execute(
                    "SELECT state FROM operations WHERE id=?", (operation_id,)
                ).fetchone()
                if operation and operation[0] == "failed" and kind == "rate":
                    db.execute("DELETE FROM operations WHERE id=?", (operation_id,))
                elif operation and operation[0] not in {"started", "draft_created"}:
                    db.execute(
                        "UPDATE inbox SET state=?,payload='{}' WHERE id=?",
                        ("uncertain" if operation[0] == "uncertain" else "done", receipt_id),
                    )
            return bool(inserted)

    def inbox_item(self, receipt_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM inbox WHERE id=?", (receipt_id,)).fetchone()
        return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    def recover_inbox(self):
        """Startup only, before receiving or running new work.

        A started operation may have reached either remote service. Persist its
        uncertain outcome, keeping known request/answer IDs, without resending it.
        Return only receipts whose operation never started, in acceptance order.
        """
        with self.connection() as db:
            db.execute(
                "UPDATE operations SET state='uncertain' WHERE state IN ('started','draft_created')"
            )
            db.execute(
                "UPDATE inbox SET state=CASE WHEN (SELECT state FROM operations "
                "WHERE operations.id=inbox.operation_id)='uncertain' THEN 'uncertain' ELSE 'done' END,"
                "payload='{}' WHERE state='pending' AND EXISTS "
                "(SELECT 1 FROM operations WHERE operations.id=inbox.operation_id)"
            )
            rows = db.execute("SELECT * FROM inbox WHERE state='pending' ORDER BY rowid").fetchall()
        items = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                payload = None
            items.append({**dict(row), "payload": payload})
        return items

    def settle_inbox(self, receipt_id, *, uncertain=False):
        """After a recovery job stops, never leave an interrupted action replayable."""
        with self.connection() as db:
            receipt = db.execute(
                "SELECT operation_id,state FROM inbox WHERE id=?", (receipt_id,)
            ).fetchone()
            if receipt is None or receipt["state"] != "pending":
                return
            operation_id = receipt["operation_id"]
            operation = db.execute(
                "SELECT state FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
            uncertain = uncertain or (
                operation is not None
                and operation["state"] in {"started", "draft_created", "uncertain"}
            )
            if uncertain:
                db.execute(
                    "INSERT OR IGNORE INTO operations VALUES (?,'uncertain','{}',?)",
                    (operation_id, time.time()),
                )
                db.execute(
                    "UPDATE operations SET state='uncertain' "
                    "WHERE id=? AND state IN ('started','draft_created')",
                    (operation_id,),
                )
            db.execute(
                "UPDATE inbox SET state=?,payload='{}' WHERE id=?",
                ("uncertain" if uncertain else "done", receipt_id),
            )

    def operation(self, operation_id):
        with self.connection() as db:
            row = db.execute(
                "SELECT state,payload FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
        return {"state": row[0], "payload": json.loads(row[1])} if row else None

    def snapshot(self, request_id):
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM snapshots WHERE request_id=?", (request_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def remember_request(self, detail, notification=None):
        """Atomically record observed state and enqueue its one notification."""
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?,?)",
                (detail["request"]["id"], json.dumps(detail)),
            )
            if notification:
                key, payload = notification
                db.execute(
                    "INSERT OR IGNORE INTO notifications(id,payload) VALUES (?,?)",
                    (key, json.dumps(payload)),
                )

    def pending_notifications(self):
        with self.connection() as db:
            return [
                {"id": r[0], **json.loads(r[1])}
                for r in db.execute(
                    "SELECT id,payload FROM notifications WHERE state='pending' ORDER BY rowid"
                )
            ]

    def notification_state(self, key, state):
        with self.connection() as db:
            db.execute("UPDATE notifications SET state=? WHERE id=?", (state, key))

    def save_delivery(self, channel, ts, text, blocks):
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO deliveries VALUES (?,?,?)",
                (channel, ts, json.dumps({"text": text, "blocks": blocks})),
            )

    def deliveries(self):
        with self.connection() as db:
            return [
                {"channel": row[0], "ts": row[1], **json.loads(row[2])}
                for row in db.execute("SELECT * FROM deliveries")
            ]

    def delivered(self, channel, ts):
        with self.connection() as db:
            db.execute("DELETE FROM deliveries WHERE channel=? AND ts=?", (channel, ts))
