"""Local, credential-free Socket Mode health for the common desktop launcher."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Event


class RuntimeHealth:
    def __init__(self, path: Path, api_url: str):
        self.path = path
        self.api_url = api_url

    def write(self, status: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        payload = {
            "pid": os.getpid(),
            "status": status,
            "api_url": self.api_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


def serve_socket(
    handler, health: RuntimeHealth, *, stopped: Event | None = None, on_connected=None
) -> None:
    """The SDK reconnects automatically; report actual connection state every 5 s."""
    stopped = stopped or Event()
    handler.connect()
    announced = False
    while True:
        connected = handler.client.is_connected()
        health.write("connected" if connected else "disconnected")
        if connected and not announced:
            print("PeopleFlow Slack is connected. Open the app's Home or Messages tab.")
            announced = True
            if on_connected:
                on_connected()
        if stopped.wait(5):
            return
