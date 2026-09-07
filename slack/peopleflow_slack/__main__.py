from __future__ import annotations

import argparse
import logging
import sys
from contextlib import ExitStack
from pathlib import Path

from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from .application import EmployeeApp
from .client import PeopleFlowClient
from .config import Settings
from .handlers import create_bolt_app
from .health import RuntimeHealth, serve_socket
from .inbox import recover_inbox
from .process_lock import ProcessLock, installation_lock_path
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="PeopleFlow employee Slack app")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check configuration, Slack identity and PeopleFlow connectivity without posting",
    )
    parser.add_argument("--health-file", type=Path, help="Local health file used by START.bat")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    health = None
    try:
        settings = Settings.load()
        with ExitStack() as stack:
            if not args.check:
                stack.enter_context(
                    ProcessLock(installation_lock_path(settings.team_id, settings.employee_user_id))
                )
                stack.enter_context(ProcessLock(settings.state_path.parent / "process.lock"))
                health = RuntimeHealth(
                    args.health_file or settings.state_path.parent / "health.json", settings.api_url
                )
                health.write("starting")
            run(settings, args.check, stack, health=health)
            if health:
                health.write("stopped")
    except KeyboardInterrupt:
        if health:
            health.write("stopped")
        print("PeopleFlow Slack stopped.")
    except Exception as exc:
        if health:
            health.write("failed")
        # Configuration messages contain names, never token values.
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"Unable to start PeopleFlow Slack: {message}", file=sys.stderr)
        sys.exit(1)


def run(settings, check, stack, health=None):
    api = PeopleFlowClient(settings.api_url, settings.password, settings.api_timeout)
    stack.callback(api.close)
    slack = WebClient(token=settings.bot_token, timeout=20, retry_handlers=[])
    identity = slack.auth_test()
    if identity["team_id"] != settings.team_id:
        raise ValueError("SLACK_TEAM_ID does not match the bot installation.")
    api.health()
    profile = api.me()
    if profile.get("user", {}).get("role") != "employee":
        raise ValueError("PeopleFlow must authenticate this integration as employee.")
    backend_id = profile.get("backend_id")
    if not isinstance(backend_id, str) or not backend_id:
        raise ValueError(
            "The PeopleFlow backend must expose its storage identity. Restart it with START.bat."
        )
    if check:
        print(
            "Configuration, Slack bot identity, and PeopleFlow employee API: OK. No messages sent."
        )
        return
    store = Store(settings.state_path)
    identity_key = {
        "team": settings.team_id,
        "employee": settings.employee_user_id,
        "bot": identity["user_id"],
        "backend": backend_id,
    }
    previous = store.get("installation")
    if previous and any(
        previous.get(key) != identity_key[key] for key in ("team", "employee", "bot")
    ):
        raise ValueError(
            "This local state belongs to another installation. Use a separate slack/.state directory for a different workspace/employee."
        )
    if previous and previous.get("backend", backend_id) != backend_id:
        raise ValueError(
            "This Slack state belongs to another PeopleFlow backend. Connect to the original "
            "backend or use a separate Slack state directory; saved actions were not replayed."
        )
    store.set("installation", identity_key)
    service = EmployeeApp(settings, api, store, slack)
    stack.callback(service.close)
    service.poll_once()  # Baseline old requests before receiving new employee actions.
    recover_inbox(service)
    app = create_bolt_app(service)
    handler = SocketModeHandler(app, settings.app_token)
    service.start_polling()

    def publish_startup_surfaces():
        service.queue(service.home, "overview")
        service.queue(service.upgrade_messages)

    try:
        if health:
            serve_socket(handler, health, on_connected=publish_startup_surfaces)
        else:
            handler.start()
    finally:
        handler.close()


if __name__ == "__main__":
    main()
