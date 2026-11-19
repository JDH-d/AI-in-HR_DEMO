"""Security boundaries exercised with synthetic credentials and isolated storage."""

import asyncio
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from api.http_security import JSON_BODY_LIMIT, HTTPGuardMiddleware, LoginThrottle
from app import create_app
from core import settings
from domain.errors import DocumentError
from services.document_service import DocumentService


def test_validation_response_does_not_echo_submitted_secret():
    client = TestClient(create_app())
    secret = "synthetic-private-password-do-not-echo"
    response = client.post(
        "/api/v1/auth/login", json={"username": "employee", "password": {"secret": secret}}
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert "input" not in response.text


def test_credentials_and_private_data_are_not_cacheable():
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "employee", "password": settings.DEMO_LOGIN_PASSWORD},
    )
    assert response.status_code == 200
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    for result in (response, client.get("/api/v1/conversations", headers=headers)):
        assert result.headers.get("cache-control") == "no-store"
        assert result.headers.get("x-content-type-options") == "nosniff"


def test_repeated_failed_logins_are_bounded():
    client = TestClient(create_app())
    for _ in range(10):
        response = client.post(
            "/api/v1/auth/login", json={"username": "employee", "password": "wrong"}
        )
        assert response.status_code == 401
    response = client.post("/api/v1/auth/login", json={"username": "manager", "password": "wrong"})
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60
    # Client-supplied forwarding headers do not reset the middleware's peer bucket.
    assert (
        client.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": "198.51.100.55"},
            json={"username": "employee", "password": "wrong"},
        ).status_code
        == 429
    )


def test_successful_sign_ins_do_not_exhaust_failed_attempt_budget():
    client = TestClient(create_app())
    for _ in range(12):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "employee", "password": settings.DEMO_LOGIN_PASSWORD},
            ).status_code
            == 200
        )


def test_throttle_expires_and_does_not_evict_blocked_clients_when_full():
    clock = Mock(return_value=0)
    throttle = LoginThrottle(attempts=2, window=60, max_clients=1, clock=clock)
    assert throttle.reserve("first") == (0, 0)
    assert throttle.reserve("first") == (0, 0)
    assert throttle.reserve("first")[1] == 60
    assert throttle.reserve("new")[1] == 60
    clock.return_value = 61
    assert throttle.reserve("new") == (61, 0)


def test_oversized_login_rejected_before_parsing_or_echoing_credentials():
    client = TestClient(create_app())
    result = client.post(
        "/api/v1/auth/login", json={"username": "employee", "password": "private" * 2000}
    )
    assert result.status_code == 413
    assert "private" not in result.text
    assert result.headers["cache-control"] == "no-store"


def test_chunked_body_limit_cannot_be_bypassed_without_content_length():
    downstream = Mock()
    responses = []
    chunks = iter(
        [
            {"type": "http.request", "body": b"x" * JSON_BODY_LIMIT, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": False},
        ]
    )

    async def receive():
        return next(chunks)

    async def send(message):
        responses.append(message)

    asyncio.run(
        HTTPGuardMiddleware(downstream)(
            {"type": "http", "path": "/api/v1/requests", "method": "POST", "headers": []},
            receive,
            send,
        )
    )
    downstream.assert_not_called()
    assert responses[0]["status"] == 413


def test_index_failures_do_not_publish_provider_exception(caplog):
    store = Mock()
    store.find_by_id.return_value = {"id": "document", "name": "policy.txt"}
    secret = "synthetic-provider-credential-do-not-log"
    service = DocumentService(store, Mock(), Mock(side_effect=RuntimeError(secret)))
    with pytest.raises(DocumentError):
        service.index("document")
    assert secret not in str(store.record_index_result.call_args_list)
    assert secret not in caplog.text
