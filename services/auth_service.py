from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DemoIdentity:
    id: str
    username: str
    display_name: str
    role: str
    manager_id: str | None = None

    def public_dict(self) -> dict:
        return asdict(self)


DEMO_IDENTITIES = {
    "employee": DemoIdentity(
        id="employee.demo",
        username="employee",
        display_name="Demo Employee",
        role="employee",
        manager_id="manager.demo",
    ),
    "manager": DemoIdentity(
        id="manager.demo",
        username="manager",
        display_name="Demo Manager",
        role="manager",
    ),
    "knowledge_admin": DemoIdentity(
        id="admin.demo",
        username="knowledge_admin",
        display_name="Demo Knowledge Admin",
        role="knowledge_admin",
    ),
}


class AuthenticationError(RuntimeError):
    pass


class DemoAuthService:
    def __init__(self, secret: str, password: str, ttl_seconds: int = 28800) -> None:
        if not secret or not password:
            raise ValueError("Demo authentication requires a secret and password")
        self.secret = secret.encode("utf-8")
        self.password = password
        self.ttl_seconds = ttl_seconds

    def login(self, username: str, password: str) -> tuple[str, DemoIdentity]:
        identity = DEMO_IDENTITIES.get((username or "").strip().lower())
        password_valid = secrets.compare_digest(password or "", self.password)
        if identity is None or not password_valid:
            raise AuthenticationError("Invalid demo credentials.")
        return self.issue_token(identity), identity

    def issue_token(self, identity: DemoIdentity) -> str:
        now = int(time.time())
        payload = {
            "sub": identity.id,
            "username": identity.username,
            "role": identity.role,
            "iat": now,
            "exp": now + self.ttl_seconds,
        }
        encoded = _base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = _base64url(
            hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{encoded}.{signature}"

    def verify_token(self, token: str) -> DemoIdentity:
        try:
            encoded, provided_signature = token.split(".", 1)
        except ValueError as exc:
            raise AuthenticationError("Invalid authentication token.") from exc
        expected_signature = _base64url(
            hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not secrets.compare_digest(provided_signature, expected_signature):
            raise AuthenticationError("Invalid authentication token.")
        try:
            payload = json.loads(_base64url_decode(encoded))
            expires_at = int(payload["exp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AuthenticationError("Invalid authentication token.") from exc
        if expires_at <= int(time.time()):
            raise AuthenticationError("Authentication token has expired.")
        identity = DEMO_IDENTITIES.get(str(payload.get("username", "")))
        if (
            identity is None
            or payload.get("sub") != identity.id
            or payload.get("role") != identity.role
        ):
            raise AuthenticationError("Invalid authentication token.")
        return identity


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
