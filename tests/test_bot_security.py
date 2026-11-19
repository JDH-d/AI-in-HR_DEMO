import hashlib
import hmac

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from integrations.bot_security import verify_discord_signature, verify_slack_signature

BODY = b'{"type":2,"data":{"name":"peopleflow"}}'
NOW = 1800000000.0
STAMP = str(int(NOW))
SECRET = "synthetic-signing-secret"


def slack_signature(body=BODY, timestamp=STAMP, secret=SECRET):
    message = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def test_slack_signature_is_bound_to_raw_body_timestamp_and_secret():
    signature = slack_signature()
    assert verify_slack_signature(BODY, STAMP, signature, SECRET, NOW)
    assert not verify_slack_signature(BODY + b" ", STAMP, signature, SECRET, NOW)
    assert not verify_slack_signature(BODY, str(int(NOW) + 1), signature, SECRET, NOW)
    assert not verify_slack_signature(BODY, STAMP, signature, "another-secret", NOW)


@pytest.mark.parametrize(
    "offset,valid", [(-301, False), (-300, True), (0, True), (300, True), (301, False)]
)
def test_slack_rejects_old_and_future_replays(offset, valid):
    stamp = str(int(NOW) + offset)
    assert (
        verify_slack_signature(BODY, stamp, slack_signature(timestamp=stamp), SECRET, NOW) is valid
    )


@pytest.mark.parametrize("stamp", ["", "1.8e9", " 1800000000", "-1", "9" * 100, None])
def test_slack_invalid_timestamp_is_rejected(stamp):
    assert not verify_slack_signature(BODY, stamp, slack_signature(), SECRET, NOW)


@pytest.mark.parametrize(
    "signature", ["", "v1=" + "a" * 64, "v0=" + "a" * 63, "v0=" + "g" * 64, None]
)
def test_slack_invalid_signature_is_rejected(signature):
    assert not verify_slack_signature(BODY, STAMP, signature, SECRET, NOW)


def test_discord_signature_verifies_exact_bytes_with_real_ed25519():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw().hex()
    signature = private.sign(STAMP.encode() + BODY).hex()
    assert verify_discord_signature(BODY, STAMP, signature, public, NOW)
    assert not verify_discord_signature(BODY + b" ", STAMP, signature, public, NOW)
    assert not verify_discord_signature(BODY, str(int(NOW) + 1), signature, public, NOW)
    wrong_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    assert not verify_discord_signature(BODY, STAMP, signature, wrong_key, NOW)


@pytest.mark.parametrize(
    "offset,valid", [(-301, False), (-300, True), (0, True), (300, True), (301, False)]
)
def test_discord_rejects_old_and_future_replays(offset, valid):
    private = Ed25519PrivateKey.generate()
    stamp = str(int(NOW) + offset)
    public = private.public_key().public_bytes_raw().hex()
    signature = private.sign(stamp.encode() + BODY).hex()
    assert verify_discord_signature(BODY, stamp, signature, public, NOW) is valid


@pytest.mark.parametrize(
    "signature,key", [("", ""), ("ab" * 64, "g" * 64), ("ab" * 63, "ab" * 32), (None, None)]
)
def test_discord_bad_hex_and_lengths_fail_closed(signature, key):
    assert not verify_discord_signature(BODY, STAMP, signature, key, NOW)


@pytest.mark.parametrize("now", [float("nan"), float("inf"), None])
def test_invalid_clock_never_disables_replay_protection(now):
    assert not verify_slack_signature(BODY, STAMP, slack_signature(), SECRET, now)
    private = Ed25519PrivateKey.generate()
    assert not verify_discord_signature(
        BODY,
        STAMP,
        private.sign(STAMP.encode() + BODY).hex(),
        private.public_key().public_bytes_raw().hex(),
        now,
    )
