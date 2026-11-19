"""Durable notification cursor/outbox, separate from workflow transactions and data."""

import json
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager

from domain.notification_policy import has_recipient, is_current_recipient, notification_for_event
from domain.notifications import (
    PROVIDERS,
    IntegrationConflict,
    IntegrationError,
    IntegrationRateLimited,
    IntegrationUnavailable,
)
from domain.workflow import WorkflowNotFoundError
from storage.request_store import RequestStore


class NotificationStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)

    @contextmanager
    def transaction(self):
        try:
            with closing(sqlite3.connect(self.db_path, timeout=2)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                with conn:
                    yield conn
        except sqlite3.Error:
            raise IntegrationUnavailable(
                "Notification storage is temporarily unavailable. Try again later."
            ) from None

    def initialize(self):
        with self.transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS integration_settings (
                provider TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 0, cursor INTEGER NOT NULL,
                not_before REAL NOT NULL DEFAULT 0, updated_by TEXT, updated_at REAL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS notification_jobs (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL REFERENCES integration_settings(provider),
                event_id TEXT, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0,
                lease_until REAL NOT NULL DEFAULT 0, lease_token TEXT,
                error_code TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL,
                UNIQUE(provider, event_id)
            )""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notification_queue ON notification_jobs(provider,status,created_at)"
            )
            for provider in PROVIDERS:
                conn.execute(
                    "INSERT OR IGNORE INTO integration_settings(provider,cursor) VALUES (?, (SELECT COALESCE(MAX(rowid),0) FROM request_events))",
                    (provider,),
                )
            conn.execute("""CREATE TABLE IF NOT EXISTS notification_migrations (
                name TEXT PRIMARY KEY, applied_at REAL NOT NULL
            )""")
            if not conn.execute(
                "SELECT 1 FROM notification_migrations WHERE name='personal_routing_v1'"
            ).fetchone():
                now = time.time()
                # Preserve delivered history, but never send old channel broadcasts
                # through a newly configured personal destination or replay old events.
                for row in conn.execute(
                    "SELECT id,payload FROM notification_jobs WHERE status IN ('pending','sending')"
                ).fetchall():
                    if not has_recipient(self._payload(row["payload"])):
                        conn.execute(
                            "UPDATE notification_jobs SET status='cancelled',lease_until=0,lease_token=NULL,updated_at=? WHERE id=?",
                            (now, row["id"]),
                        )
                conn.execute(
                    "UPDATE integration_settings SET enabled=0,revision=revision+CASE WHEN enabled=1 THEN 1 ELSE 0 END,cursor=(SELECT COALESCE(MAX(rowid),0) FROM request_events)"
                )
                conn.execute(
                    "INSERT INTO notification_migrations(name,applied_at) VALUES ('personal_routing_v1',?)",
                    (now,),
                )

    def overview(self):
        with self.transaction() as conn:
            result = []
            for row in conn.execute("SELECT * FROM integration_settings ORDER BY provider"):
                last = conn.execute(
                    "SELECT id,status,attempts,error_code,updated_at,next_attempt_at FROM notification_jobs WHERE provider=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                    (row["provider"],),
                ).fetchone()
                active = conn.execute(
                    "SELECT id,status,attempts,error_code,updated_at,next_attempt_at FROM notification_jobs WHERE provider=? AND status IN ('pending','sending') ORDER BY created_at,rowid LIMIT 1",
                    (row["provider"],),
                ).fetchone()
                pending = conn.execute(
                    "SELECT COUNT(*) FROM notification_jobs WHERE provider=? AND status IN ('pending','sending')",
                    (row["provider"],),
                ).fetchone()[0]
                result.append(
                    {
                        "provider": row["provider"],
                        "enabled": bool(row["enabled"]),
                        "revision": row["revision"],
                        "pending": pending,
                        "last_delivery": dict(last) if last else None,
                        "active_delivery": dict(active) if active else None,
                    }
                )
            return result

    def set_enabled(self, provider, enabled, revision, actor, now):
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM integration_settings WHERE provider=?", (provider,)
            ).fetchone()
            if row["revision"] != revision:
                raise IntegrationConflict(
                    "Integration settings changed. Refresh before trying again."
                )
            if bool(row["enabled"]) == enabled:
                return
            # Never replay old events when enabling, or send an old queue after re-enabling.
            conn.execute(
                "UPDATE integration_settings SET enabled=?,revision=revision+1,cursor=(SELECT COALESCE(MAX(rowid),0) FROM request_events),updated_by=?,updated_at=? WHERE provider=?",
                (enabled, actor, now, provider),
            )
            conn.execute(
                "UPDATE notification_jobs SET status='cancelled',updated_at=? WHERE provider=? AND status IN ('pending','sending')",
                (now, provider),
            )

    def enqueue_test(self, provider, now, recipient_id, audience):
        payload = {"kind": "test", "recipient_id": recipient_id, "audience": audience}
        if not has_recipient(payload):
            raise IntegrationError("Choose an Employee or Manager recipient for the test.")
        with self.transaction() as conn:
            if not conn.execute(
                "SELECT enabled FROM integration_settings WHERE provider=?", (provider,)
            ).fetchone()[0]:
                raise IntegrationError(
                    "Enable this integration before sending a test notification."
                )
            recent = conn.execute(
                "SELECT payload FROM notification_jobs WHERE provider=? AND event_id IS NULL AND created_at>?",
                (provider, now - 30),
            ).fetchall()
            if any(
                self._payload(row["payload"]).get("recipient_id") == recipient_id for row in recent
            ):
                raise IntegrationRateLimited(
                    "Wait 30 seconds before sending another test notification."
                )
            return self._insert(conn, provider, None, payload, now)

    @staticmethod
    def _insert(conn, provider, event_id, payload, now):
        identifier = uuid.uuid4().hex
        conn.execute(
            "INSERT OR IGNORE INTO notification_jobs(id,provider,event_id,payload,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (identifier, provider, event_id, json.dumps(payload), now, now),
        )
        return identifier

    def collect(self, provider, now):
        with self.transaction() as conn:
            state = conn.execute(
                "SELECT * FROM integration_settings WHERE provider=?", (provider,)
            ).fetchone()
            if not state["enabled"]:
                return
            rows = conn.execute(
                """SELECT e.rowid AS sequence,e.*
                FROM request_events e
                WHERE e.rowid>? ORDER BY e.rowid LIMIT 100""",
                (state["cursor"],),
            ).fetchall()
            for row in rows:
                request = self._request(conn, row["request_id"])
                if request is None:
                    continue
                event = {**dict(row), "details": self._payload(row["details"])}
                payload = notification_for_event(event, request)
                if payload is not None:
                    self._insert(conn, provider, row["id"], payload, now)
            if rows:
                conn.execute(
                    "UPDATE integration_settings SET cursor=? WHERE provider=?",
                    (rows[-1]["sequence"], provider),
                )

    @staticmethod
    def _payload(value):
        try:
            payload = json.loads(value)
            return payload if isinstance(payload, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _request(conn, request_id):
        try:
            return dict(RequestStore._require_request(conn, request_id))
        except WorkflowNotFoundError:
            return None

    def is_current_recipient(self, payload):
        with self.transaction() as conn:
            return self._is_current_recipient(conn, payload)

    def _is_current_recipient(self, conn, payload):
        if not has_recipient(payload):
            return False
        request = None
        if payload.get("kind") != "test":
            request_id = payload.get("request_id")
            if not isinstance(request_id, str):
                return False
            request = self._request(conn, request_id)
        return is_current_recipient(payload, request)

    def claim(self, provider, now, max_attempts=5):
        with self.transaction() as conn:
            state = conn.execute(
                "SELECT * FROM integration_settings WHERE provider=?", (provider,)
            ).fetchone()
            if not state["enabled"] or state["not_before"] > now:
                return None
            row = conn.execute(
                "SELECT * FROM notification_jobs WHERE provider=? AND status IN ('pending','sending') ORDER BY created_at,rowid LIMIT 1",
                (provider,),
            ).fetchone()
            if row is None or row["next_attempt_at"] > now or row["lease_until"] > now:
                return None
            payload = self._payload(row["payload"])
            if not self._is_current_recipient(conn, payload):
                conn.execute(
                    "UPDATE notification_jobs SET status='cancelled',lease_until=0,lease_token=NULL,updated_at=? WHERE id=?",
                    (now, row["id"]),
                )
                return None
            if row["attempts"] >= max_attempts:
                conn.execute(
                    "UPDATE notification_jobs SET status='failed',error_code='delivery_unconfirmed',updated_at=? WHERE id=?",
                    (now, row["id"]),
                )
                return None
            lease = uuid.uuid4().hex
            conn.execute(
                "UPDATE notification_jobs SET status='sending',attempts=attempts+1,lease_token=?,lease_until=?,updated_at=? WHERE id=?",
                (lease, now + 60, now, row["id"]),
            )
            return {
                **dict(row),
                "payload": payload,
                "attempts": row["attempts"] + 1,
                "lease_token": lease,
            }

    def finish(self, job, status, error_code, next_attempt_at, now, pause):
        with self.transaction() as conn:
            changed = conn.execute(
                "UPDATE notification_jobs SET status=?,error_code=?,next_attempt_at=?,lease_until=0,lease_token=NULL,updated_at=? WHERE id=? AND lease_token=? AND status='sending'",
                (status, error_code, next_attempt_at, now, job["id"], job["lease_token"]),
            ).rowcount
            if changed:
                conn.execute(
                    "UPDATE integration_settings SET not_before=? WHERE provider=?",
                    (now + pause, job["provider"]),
                )
