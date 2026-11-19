"""Verified personal destinations and short-lived, two-step account linking."""

import hashlib
import json
import secrets
import sqlite3
import uuid

from domain.notifications import IntegrationConflict, IntegrationError, IntegrationRateLimited
from storage.notification_store import NotificationStore


class PersonalNotificationStore(NotificationStore):
    def initialize(self):
        with self.transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS personal_notification_links (
                provider TEXT NOT NULL, user_id TEXT NOT NULL, external_user_id TEXT NOT NULL,
                external_scope TEXT NOT NULL, linked_at REAL NOT NULL,
                PRIMARY KEY(provider,user_id), UNIQUE(provider,external_scope,external_user_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS personal_link_challenges (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL, user_id TEXT NOT NULL,
                code_hash TEXT UNIQUE NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
                external_user_id TEXT, external_scope TEXT, confirmed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(provider,user_id)
            )""")

    def connection(self, provider, user_id, now):
        with self.transaction() as conn:
            link = conn.execute(
                "SELECT external_user_id,external_scope FROM personal_notification_links WHERE provider=? AND user_id=?",
                (provider, user_id),
            ).fetchone()
            pending = conn.execute(
                "SELECT id AS challenge_id,external_user_id FROM personal_link_challenges WHERE provider=? AND user_id=? AND confirmed=0 AND expires_at>? AND external_user_id IS NOT NULL",
                (provider, user_id, now),
            ).fetchone()
            return {
                "connected": link is not None,
                "external_user_id": link["external_user_id"] if link else None,
                "pending": dict(pending) if pending else None,
            }

    def destination(self, provider, user_id):
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM personal_notification_links WHERE provider=? AND user_id=?",
                (provider, user_id),
            ).fetchone()
            return dict(row) if row else None

    def issue(self, provider, user_id, now):
        code = secrets.token_urlsafe(24)
        identifier = uuid.uuid4().hex
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT created_at FROM personal_link_challenges WHERE provider=? AND user_id=?",
                (provider, user_id),
            ).fetchone()
            if existing and existing["created_at"] > now - 30:
                raise IntegrationRateLimited("Wait 30 seconds before generating another link code.")
            if conn.execute(
                "SELECT 1 FROM personal_notification_links WHERE provider=? AND user_id=?",
                (provider, user_id),
            ).fetchone():
                raise IntegrationConflict(
                    "Disconnect the current account before linking another one."
                )
            conn.execute(
                "DELETE FROM personal_link_challenges WHERE provider=? AND user_id=?",
                (provider, user_id),
            )
            conn.execute(
                "INSERT INTO personal_link_challenges(id,provider,user_id,code_hash,created_at,expires_at) VALUES (?,?,?,?,?,?)",
                (
                    identifier,
                    provider,
                    user_id,
                    hashlib.sha256(code.encode()).hexdigest(),
                    now,
                    now + 600,
                ),
            )
        return {"code": code, "expires_at": now + 600}

    def claim_code(self, provider, code, external_user_id, external_scope, now):
        """Only signed provider requests may call this; web confirmation grants the link."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM personal_link_challenges WHERE provider=? AND code_hash=? AND expires_at>?",
                (provider, hashlib.sha256(code.encode()).hexdigest(), now),
            ).fetchone()
            if not row:
                raise IntegrationError(
                    "This link code is invalid or expired. Generate a new code in the application."
                )
            if row["external_user_id"] and (
                row["external_user_id"] != external_user_id
                or row["external_scope"] != external_scope
            ):
                raise IntegrationConflict(
                    "This code has already been used by another account. Generate a new code."
                )
            existing = conn.execute(
                "SELECT user_id FROM personal_notification_links WHERE provider=? AND external_scope=? AND external_user_id=?",
                (provider, external_scope, external_user_id),
            ).fetchone()
            if existing and existing["user_id"] != row["user_id"]:
                raise IntegrationConflict(
                    "This service account is linked to another application user. Employee and Manager need separate accounts."
                )
            conn.execute(
                "UPDATE personal_link_challenges SET external_user_id=?,external_scope=? WHERE id=?",
                (external_user_id, external_scope, row["id"]),
            )
        return "Account identity received. Return to Personal notifications in the application, refresh, check your account ID and confirm the connection."

    def confirm(self, provider, user_id, challenge_id, now, *, expected_scope=None):
        try:
            with self.transaction() as conn:
                row = conn.execute(
                    "SELECT * FROM personal_link_challenges WHERE id=? AND provider=? AND user_id=? AND expires_at>? AND external_user_id IS NOT NULL",
                    (challenge_id, provider, user_id, now),
                ).fetchone()
                if not row:
                    raise IntegrationError(
                        "No verified pending connection was found. Generate a new link code."
                    )
                if expected_scope is not None and row["external_scope"] != expected_scope:
                    raise IntegrationConflict(
                        "The bot workspace or application changed. Generate a new link code and connect again."
                    )
                current = conn.execute(
                    "SELECT external_user_id,external_scope FROM personal_notification_links WHERE provider=? AND user_id=?",
                    (provider, user_id),
                ).fetchone()
                if current:
                    if row["confirmed"] and tuple(current) == (
                        row["external_user_id"],
                        row["external_scope"],
                    ):
                        return
                    raise IntegrationConflict(
                        "Disconnect the current account before linking another one."
                    )
                other = conn.execute(
                    "SELECT 1 FROM personal_notification_links WHERE provider=? AND external_scope=? AND external_user_id=?",
                    (provider, row["external_scope"], row["external_user_id"]),
                ).fetchone()
                if other:
                    raise IntegrationConflict(
                        "This service account is already linked to another user. Employee and Manager need separate accounts."
                    )
                conn.execute(
                    "INSERT INTO personal_notification_links VALUES (?,?,?,?,?)",
                    (provider, user_id, row["external_user_id"], row["external_scope"], now),
                )
                conn.execute(
                    "UPDATE personal_link_challenges SET confirmed=1 WHERE id=?", (row["id"],)
                )
        except sqlite3.IntegrityError:
            raise IntegrationConflict(
                "The account connection changed. Refresh and try again."
            ) from None

    def disconnect(self, provider, user_id, now=0):
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM personal_notification_links WHERE provider=? AND user_id=?",
                (provider, user_id),
            )
            conn.execute(
                "DELETE FROM personal_link_challenges WHERE provider=? AND user_id=?",
                (provider, user_id),
            )
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notification_jobs'"
            ).fetchone():
                for row in conn.execute(
                    "SELECT id,payload FROM notification_jobs WHERE provider=? AND status IN ('pending','sending')",
                    (provider,),
                ).fetchall():
                    try:
                        payload = json.loads(row["payload"])
                    except (ValueError, TypeError):
                        continue
                    if isinstance(payload, dict) and payload.get("recipient_id") == user_id:
                        conn.execute(
                            "UPDATE notification_jobs SET status='cancelled',lease_token=NULL,lease_until=0,updated_at=? WHERE id=?",
                            (now, row["id"]),
                        )
