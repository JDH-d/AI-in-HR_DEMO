import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from peopleflow_slack.health import RuntimeHealth, serve_socket
from peopleflow_slack.process_lock import ProcessLock, installation_lock_path


def test_health_is_atomic_local_and_contains_no_credentials(tmp_path):
    path = tmp_path / "state" / "health.json"
    health = RuntimeHealth(path, "http://127.0.0.1:8123")
    health.write("starting")
    health.write("connected")
    saved = json.loads(path.read_text())
    assert saved.keys() == {"pid", "status", "api_url", "updated_at"}
    assert saved["pid"] == os.getpid()
    assert saved["status"] == "connected"
    assert saved["api_url"] == "http://127.0.0.1:8123"
    assert (datetime.now(timezone.utc) - datetime.fromisoformat(saved["updated_at"])).seconds < 2
    assert not list(path.parent.glob("*.tmp"))


def test_heartbeat_follows_socket_connection_and_reconnection():
    handler = Mock()
    handler.client.is_connected.side_effect = [True, False, True]
    health = Mock()
    stopped = SimpleNamespace(wait=Mock(side_effect=[False, False, True]))
    on_connected = Mock()
    serve_socket(handler, health, stopped=stopped, on_connected=on_connected)
    handler.connect.assert_called_once_with()
    on_connected.assert_called_once_with()
    assert [call.args[0] for call in health.write.call_args_list] == [
        "connected",
        "disconnected",
        "connected",
    ]
    assert [call.args for call in stopped.wait.call_args_list] == [(5,), (5,), (5,)]


def test_connection_failure_is_never_announced_healthy():
    handler = Mock()
    handler.connect.side_effect = RuntimeError("connection failed")
    health = Mock()
    with pytest.raises(RuntimeError):
        serve_socket(handler, health)
    health.write.assert_not_called()


def test_installation_lock_is_shared_across_checkouts(tmp_path, monkeypatch):
    monkeypatch.setattr("peopleflow_slack.process_lock.tempfile.gettempdir", lambda: str(tmp_path))
    path = installation_lock_path("TDEMO", "UDEMO")
    assert path == installation_lock_path("TDEMO", "UDEMO")
    assert path != installation_lock_path("TOTHER", "UDEMO")
    with ProcessLock(path):
        with pytest.raises(ValueError, match="already running"):
            with ProcessLock(installation_lock_path("TDEMO", "UDEMO")):
                pytest.fail("Duplicate installation acquired the lock")
    with ProcessLock(path):
        pass
