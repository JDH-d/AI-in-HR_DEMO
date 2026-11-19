"""Bound HTTP input and protect private responses before route parsing."""

import math
import time
from collections import deque
from threading import Lock

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

LOGIN_BODY_LIMIT = 8 * 1024
JSON_BODY_LIMIT = 256 * 1024
UPLOAD_BODY_LIMIT = 12 * 1024 * 1024  # Includes multipart overhead for the 10 MB document limit.


class LoginThrottle:
    """Single-process demo protection; deployment gateways must enforce their own limits."""

    def __init__(self, attempts=10, window=60, max_clients=2048, clock=time.monotonic):
        self.attempts = attempts
        self.window = window
        self.max_clients = max_clients
        self.clock = clock
        self._clients = {}
        self._lock = Lock()

    def reserve(self, client):
        now = self.clock()
        with self._lock:
            for key in list(self._clients):
                queue = self._clients[key]
                while queue and queue[0] <= now - self.window:
                    queue.popleft()
                if not queue:
                    del self._clients[key]
            if client not in self._clients and len(self._clients) >= self.max_clients:
                return None, self.window
            queue = self._clients.setdefault(client, deque())
            if len(queue) >= self.attempts:
                return None, max(1, math.ceil(queue[0] + self.window - now))
            queue.append(now)
            return now, 0

    def succeeded(self, client, reservation):
        with self._lock:
            queue = self._clients.get(client)
            if queue and reservation in queue:
                queue.remove(reservation)
                if not queue:
                    del self._clients[client]


class HTTPGuardMiddleware:
    def __init__(self, app, login_throttle=None):
        self.app = app
        self.login_throttle = login_throttle or LoginThrottle()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)

        login = scope["path"].rstrip("/") == "/api/v1/auth/login" and scope["method"] == "POST"
        client = (scope.get("client") or ("unknown",))[0]
        reservation = None

        async def protected_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                if login and reservation is not None and message["status"] < 400:
                    self.login_throttle.succeeded(client, reservation)
            await send(message)

        async def reject(status, detail, headers=None):
            await JSONResponse(status_code=status, content={"detail": detail}, headers=headers)(
                scope, receive, protected_send
            )

        if login:
            reservation, retry_after = self.login_throttle.reserve(client)
            if retry_after:
                return await reject(
                    429,
                    "Too many sign-in attempts. Wait one minute, then try again.",
                    {"Retry-After": str(retry_after)},
                )

        if scope["method"] in {"POST", "PUT", "PATCH"}:
            headers = Headers(scope=scope)
            multipart = headers.get("content-type", "").lower().startswith("multipart/form-data")
            limit = (
                LOGIN_BODY_LIMIT if login else UPLOAD_BODY_LIMIT if multipart else JSON_BODY_LIMIT
            )
            length = headers.get("content-length")
            if length is not None:
                try:
                    size = int(length)
                    if size < 0:
                        raise ValueError
                except ValueError:
                    return await reject(400, "Invalid request size.")
                if size > limit:
                    return await reject(413, "Request is too large. Reduce its size and try again.")
            # Read no more than the budget, including chunked requests without Content-Length.
            # The bounded buffer prevents multipart parsing from filling temporary disk first.
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > limit:
                    return await reject(413, "Request is too large. Reduce its size and try again.")
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay, protected_send)
        return await self.app(scope, receive, protected_send)
