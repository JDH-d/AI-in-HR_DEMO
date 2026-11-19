"""Verify provider signatures over the untouched request body before parsing it."""

import hashlib
import hmac
import math
import re

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _fresh(timestamp: str, now: float) -> bool:
    return (
        isinstance(timestamp, str)
        and re.fullmatch(r"[0-9]{1,12}", timestamp) is not None
        and isinstance(now, (int, float))
        and math.isfinite(now)
        and abs(now - int(timestamp)) <= 300
    )


def verify_slack_signature(
    body: bytes, timestamp: str, signature: str, secret: str, now: float
) -> bool:
    if (
        not isinstance(body, bytes)
        or not isinstance(secret, str)
        or not secret
        or not isinstance(signature, str)
        or re.fullmatch(r"v0=[0-9a-f]{64}", signature) is None
        or not _fresh(timestamp, now)
    ):
        return False
    signed = b"v0:" + timestamp.encode("ascii") + b":" + body
    expected = "v0=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_discord_signature(
    body: bytes, timestamp: str, signature: str, public_key: str, now: float
) -> bool:
    if (
        not isinstance(body, bytes)
        or not isinstance(signature, str)
        or not isinstance(public_key, str)
        or re.fullmatch(r"[0-9a-fA-F]{128}", signature) is None
        or re.fullmatch(r"[0-9a-fA-F]{64}", public_key) is None
        or not _fresh(timestamp, now)
    ):
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
        key.verify(bytes.fromhex(signature), timestamp.encode("ascii") + body)
    except (InvalidSignature, UnsupportedAlgorithm, ValueError):
        return False
    return True
