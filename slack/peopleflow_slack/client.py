"""Synchronous, employee-only adapter to the existing PeopleFlow /api/v1 API.

History and workflow decisions belong to the API. Share one client across Bolt
handler threads, then close it after the handlers have stopped. No payloads,
credentials, raw error bodies, or transport exception messages are logged here.
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

import httpx


class APIError(RuntimeError):
    """Safe English error; uncertain means a server-side change may have happened."""

    def __init__(self, status: int, detail: str, uncertain: bool = False) -> None:
        self.status = status
        self.detail = detail
        self.uncertain = uncertain
        super().__init__(detail)


# Only known, static API messages can reach Slack. In particular, FastAPI's
# validation objects may contain the original input, and proxy errors may contain
# credentials or internal diagnostics. Never stringify those objects.
_SAFE_DETAILS = frozenset(
    {
        "Invalid demo credentials.",
        "Bearer authentication is required.",
        "Invalid authentication token.",
        "Authentication token has expired.",
        "This role cannot perform this action.",
        "The conversation could not be found.",
        "The conversation could not be saved.",
        "The workflow request could not be found.",
        "Only the applicant can submit this draft.",
        "The request must include a user message.",
        "The request must include at least one message.",
        "The request must include at least one user message.",
        "Request type is not supported.",
        "Comment is required.",
        "Comment cannot be empty.",
        "Approver is required.",
        "Start date is required.",
        "End date is required.",
        "Start date must be a real calendar date in YYYY-MM-DD format.",
        "End date must be a real calendar date in YYYY-MM-DD format.",
        "End date cannot be earlier than start date.",
        "Choose whether you will be away for a full or partial day.",
        "Choose an expected return date or select Not sure yet.",
        "Expected return must be a real calendar date in YYYY-MM-DD format.",
        "Expected return must be after the first full day away.",
        "Expected return cannot be before the first day away.",
        "Partial-day hours must be greater than 0 and no more than 24.",
        "Rating must be between 1 and 5.",
    }
)
_STATUS_DETAILS = {
    400: "PeopleFlow could not accept this request. Check the supplied information.",
    401: "PeopleFlow authentication failed. Check the demo credentials.",
    403: "This action is not available to the demo employee.",
    404: "The requested PeopleFlow item could not be found.",
    409: "This request has changed or the action is no longer available. Refresh its status.",
    422: "Check the request fields and try again.",
    429: "PeopleFlow is receiving too many requests. Please try again later.",
}


def _safe_detail(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value in _SAFE_DETAILS:
        return value
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item in _SAFE_DETAILS for item in value)
    ):
        return " ".join(value[:8])
    return fallback


def _invalid(*, uncertain: bool = False) -> APIError:
    detail = "PeopleFlow returned an invalid response."
    if uncertain:
        detail += " The change may have been saved; check its status before trying again."
    return APIError(502, detail, uncertain)


def _object(value: Any, *, uncertain: bool = False) -> dict:
    if not isinstance(value, dict):
        raise _invalid(uncertain=uncertain)
    return value


def _objects(value: Any, *, uncertain: bool = False) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise _invalid(uncertain=uncertain)
    return value


def _strings(value: dict, *keys: str, uncertain: bool = False) -> None:
    if any(not isinstance(value.get(key), str) for key in keys):
        raise _invalid(uncertain=uncertain)


def _record(value: Any, *, uncertain: bool = False) -> dict:
    result = _object(value, uncertain=uncertain)
    if not isinstance(result.get("id"), str) or not result["id"]:
        raise _invalid(uncertain=uncertain)
    return result


def _workflow(value: Any, *, uncertain: bool = False, expected_id: str | None = None) -> dict:
    result = _record(value, uncertain=uncertain)
    if expected_id is not None and result["id"] != expected_id:
        raise _invalid(uncertain=uncertain)
    if "applicant" in result and result["applicant"] != "employee.demo":
        raise _invalid(uncertain=uncertain)
    _strings(result, "type", "status", "type_label", uncertain=uncertain)
    if "details" in result:
        _object(result["details"], uncertain=uncertain)
    errors = result.get("validation_errors", [])
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        raise _invalid(uncertain=uncertain)
    return result


def _chat_metadata(value: dict, conversation_id: str | None = None) -> None:
    _strings(value, "intent", "language", "outcome_code", "conversation_id", uncertain=True)
    if not value["conversation_id"]:
        raise _invalid(uncertain=True)
    if conversation_id is not None and value["conversation_id"] != conversation_id:
        raise _invalid(uncertain=True)
    if value.get("sources") is not None:
        _objects(value["sources"], uncertain=True)
    if value.get("workflow_request") is not None:
        _workflow(value["workflow_request"], uncertain=True)


def _identity(value: Any) -> dict:
    user = _object(value)
    _strings(user, "id", "username", "role")
    if (user["id"], user["username"], user["role"]) != ("employee.demo", "employee", "employee"):
        raise APIError(403, "The Slack integration requires the employee.demo identity.")
    return user


def _id(value: str) -> str:
    # Backend IDs are UUIDs. A single URL segment prevents a caller-controlled
    # identifier from selecting a different route or injecting query parameters.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise APIError(400, "A valid PeopleFlow item ID is required.")
    return value


def _ndjson_lines(response: httpx.Response) -> Iterator[bytes]:
    # Split only at the NDJSON delimiter. httpx.iter_lines() also splits on
    # Unicode separators inside JSON strings and replaces invalid UTF-8 bytes.
    pending = b""
    for chunk in response.iter_bytes():
        lines = (pending + chunk).split(b"\n")
        pending = lines.pop()
        # A broken streaming peer must not grow an unterminated JSON record forever.
        if len(pending) > 1_048_576 or any(len(line) > 1_048_576 for line in lines):
            raise _invalid(uncertain=True)
        yield from lines
    if pending:
        yield pending


class PeopleFlowClient:
    """Use an API origin or a URL ending in /api/v1; authentication is lazy.

    me(), conversation(), request(), submit_request(), cancel_request(), and
    feedback() preserve API envelopes. Lists and create_request() are unwrapped.
    Successful NDJSON error events are yielded and terminate the iterator;
    HTTP/transport/protocol failures raise APIError instead.
    """

    def __init__(
        self,
        base_url: str,
        password: str = "demo-password",
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        try:
            url = httpx.URL(base_url)
        except (TypeError, httpx.InvalidURL):
            raise ValueError("PeopleFlow requires a valid HTTP(S) API URL.") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError("PeopleFlow requires an HTTP(S) API URL without credentials or query.")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("PeopleFlow timeout must be a positive number of seconds.")
        if not isinstance(password, str) or not password:
            raise ValueError("PeopleFlow demo password is required.")
        root = str(url).rstrip("/")
        if not root.endswith("/api/v1"):
            root += "/api/v1"
        self._http = httpx.Client(
            base_url=root + "/",
            timeout=timeout,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )
        self._password = password
        self._refresh_lock = Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._closed = False

    def _token(self, rejected: str | None = None) -> str:
        with self._refresh_lock:
            if self._access_token == rejected:
                self._access_token = None
            if self._access_token is not None and time.monotonic() < self._expires_at:
                return self._access_token
            self._access_token = None
            started = time.monotonic()
            data = self._json(
                "POST",
                "auth/login",
                {"username": "employee", "password": self._password},
                authenticated=False,
            )
            _identity(data.get("user"))
            token, ttl = data.get("access_token"), data.get("expires_in")
            if (
                not isinstance(token, str)
                or not token
                or any(ord(char) <= 32 or ord(char) >= 127 for char in token)
                or data.get("token_type") != "bearer"
                or isinstance(ttl, bool)
                or not isinstance(ttl, (int, float))
                or not math.isfinite(ttl)
                or ttl <= 0
            ):
                raise _invalid()
            # expires_in describes the server-signed token. Use elapsed time,
            # not the workstation clock, and allow for login latency/rounding.
            self._expires_at = started + ttl - min(5.0, ttl / 10)
            self._access_token = token
            return token

    def _forget(self, token: str) -> None:
        with self._refresh_lock:
            if self._access_token == token:
                self._access_token = None

    @contextmanager
    def _response(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        authenticated: bool = True,
        ndjson: bool = False,
    ) -> Iterator[httpx.Response]:
        if self._closed:
            raise APIError(503, "The PeopleFlow connection has been closed.")
        changing = method in {"POST", "DELETE"} and authenticated
        token = self._token() if authenticated else None
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            if ndjson:
                headers["Accept"] = "application/x-ndjson"
            try:
                with self._http.stream(method, path, json=payload, headers=headers) as response:
                    if response.status_code == 401 and token and attempt == 0:
                        # Release the connection before login, including with a
                        # one-connection pool. A 401 means no business action ran.
                        response.close()
                    else:
                        if response.status_code == 401 and token:
                            self._forget(token)
                        if not response.is_success:
                            response.read()
                            self._raise_http(response, changing=changing)
                        yield response
                        return
            except httpx.HTTPError as exc:
                uncertain = changing and not isinstance(
                    exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
                )
                detail = (
                    "PeopleFlow timed out."
                    if isinstance(exc, httpx.TimeoutException)
                    else "PeopleFlow could not be reached or the connection was interrupted."
                )
                if uncertain:
                    detail += (
                        " The change may have been saved; check its status before trying again."
                    )
                raise APIError(
                    504 if isinstance(exc, httpx.TimeoutException) else 503, detail, uncertain
                ) from None
            token = self._token(rejected=token)

    @staticmethod
    def _raise_http(response: httpx.Response, *, changing: bool) -> None:
        status = response.status_code
        fallback = _STATUS_DETAILS.get(status, "PeopleFlow is temporarily unavailable.")
        try:
            data = response.json()
        except (ValueError, UnicodeError):
            data = None
        detail = _safe_detail(data.get("detail") if isinstance(data, dict) else None, fallback)
        uncertain = changing and status >= 500 and detail != "The conversation could not be saved."
        if uncertain:
            detail += " The change may have been saved; check its status before trying again."
        raise APIError(status, detail, uncertain)

    def _json(
        self, method: str, path: str, payload: dict | None = None, *, authenticated: bool = True
    ) -> dict:
        if payload is not None and not isinstance(payload, dict):
            raise APIError(400, "PeopleFlow request fields must be an object.")
        changing = method == "POST" and authenticated
        with self._response(method, path, payload, authenticated=authenticated) as response:
            response.read()
            try:
                data = response.json()
            except (ValueError, UnicodeError):
                raise _invalid(uncertain=changing) from None
            return _object(data, uncertain=changing)

    def health(self) -> dict:
        data = self._json("GET", "health", authenticated=False)
        _strings(data, "status")
        return data

    def me(self) -> dict:
        data = self._json("GET", "me")
        try:
            _identity(data.get("user"))
            if "backend_id" in data:
                backend_id = data["backend_id"]
                try:
                    valid_id = (
                        isinstance(backend_id, str) and str(uuid.UUID(backend_id)) == backend_id
                    )
                except ValueError:
                    valid_id = False
                if not valid_id:
                    raise _invalid()
        except APIError:
            with self._refresh_lock:
                self._access_token = None
            raise
        return data

    @staticmethod
    def _chat_payload(text: str, conversation_id: str | None) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise APIError(400, "Enter a message for PeopleFlow.")
        data = {"messages": [{"role": "user", "content": text}]}
        if conversation_id is not None:
            data["conversation_id"] = _id(conversation_id)
        return data

    def chat(self, text: str, conversation_id: str | None = None) -> dict:
        data = self._json("POST", "chat", self._chat_payload(text, conversation_id))
        message = _object(data.get("message"), uncertain=True)
        _strings(message, "content", uncertain=True)
        if message.get("role") != "assistant":
            raise _invalid(uncertain=True)
        _chat_metadata(data, conversation_id)
        return data

    def stream_chat(self, text: str, conversation_id: str | None = None) -> Iterator[dict]:
        """Yield NDJSON events, preserving token/replace whitespace and final metadata.

        An error event (including persistence failure) is terminal, never success.
        Close the iterator if abandoning it before completion to release the socket.
        """
        payload = self._chat_payload(text, conversation_id)
        with self._response("POST", "chat/stream", payload, ndjson=True) as response:
            if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != (
                "application/x-ndjson"
            ):
                raise _invalid(uncertain=True)
            started = False
            for line in _ndjson_lines(response):
                if not line.strip():
                    continue
                try:
                    event = _object(json.loads(line.decode("utf-8")), uncertain=True)
                except (ValueError, UnicodeError):
                    raise _invalid(uncertain=True) from None
                kind = event.get("type")
                if kind == "start" and not started:
                    started = True
                elif kind in ("token", "replace") and started:
                    _strings(event, "content", uncertain=True)
                elif kind == "complete" and started:
                    _chat_metadata(event, conversation_id)
                    response.close()
                    yield event
                    return
                elif kind == "error":
                    _strings(event, "message", uncertain=True)
                    response.close()
                    yield {
                        "type": "error",
                        "message": _safe_detail(
                            event["message"],
                            "PeopleFlow could not complete the response. Check the conversation "
                            "before trying again.",
                        ),
                    }
                    return
                else:
                    raise _invalid(uncertain=True)
                yield event
            raise APIError(
                502,
                "The PeopleFlow response ended before completion. "
                "Check the conversation before trying again.",
                uncertain=True,
            )

    def conversations(self) -> list[dict]:
        items = _objects(self._json("GET", "conversations").get("conversations"))
        for item in items:
            _record(item)
            _strings(item, "title")
        return items

    def conversation(self, id: str) -> dict:
        data = self._json("GET", f"conversations/{_id(id)}")
        summary = _record(data.get("conversation"))
        if summary["id"] != id:
            raise _invalid()
        _strings(summary, "title")
        for message in _objects(data.get("messages")):
            _record(message)
            _strings(message, "content")
            if message.get("role") not in ("user", "assistant"):
                raise _invalid()
            if message.get("sources") is not None:
                _objects(message["sources"])
            if message.get("workflow") is not None:
                _workflow(message["workflow"])
        return data

    def delete_conversation(self, id: str) -> None:
        with self._response("DELETE", f"conversations/{_id(id)}") as response:
            if response.status_code != 204:
                raise _invalid(uncertain=True)

    def requests(self) -> list[dict]:
        items = _objects(self._json("GET", "requests").get("requests"))
        for item in items:
            _workflow(item)
        return items

    def request(self, id: str) -> dict:
        data = self._json("GET", f"requests/{_id(id)}")
        _workflow(data.get("request"), expected_id=id)
        _objects(data.get("events"))
        for comment in _objects(data.get("comments")):
            _strings(comment, "body")
        return data

    def create_request(self, payload: dict) -> dict:
        data = self._json("POST", "requests", payload)
        return _workflow(data.get("request"), uncertain=True)

    def submit_request(self, id: str, payload: dict) -> dict:
        data = self._json("POST", f"requests/{_id(id)}/submit", payload)
        _workflow(data.get("request"), uncertain=True, expected_id=id)
        return data

    def cancel_request(self, id: str, comment: str = "") -> dict:
        data = self._json("POST", f"requests/{_id(id)}/cancel", {"comment": comment})
        _workflow(data.get("request"), uncertain=True, expected_id=id)
        return data

    def feedback(self, question: str, answer: str, rating: int, comment: str = "") -> dict:
        data = self._json(
            "POST",
            "feedback",
            {"question": question, "answer": answer, "rating": rating, "comment": comment},
        )
        _record(data.get("feedback"), uncertain=True)
        return data

    def close(self) -> None:
        with self._refresh_lock:
            self._closed = True
            self._access_token = None
            self._password = ""
            self._http.close()
