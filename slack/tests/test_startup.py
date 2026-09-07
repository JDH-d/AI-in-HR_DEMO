"""Startup ownership checks run before inbox recovery or Socket Mode delivery."""

from contextlib import ExitStack
from unittest.mock import Mock

import pytest

from peopleflow_slack import __main__ as startup
from peopleflow_slack.config import Settings
from peopleflow_slack.store import Store

BACKEND = "cc7e95a1-ffac-47a6-ac5d-068a26652d2e"
OTHER_BACKEND = "c2265708-dae7-4868-b04f-22e0fa6f1be2"
INSTALLATION = {"team": "TDEMO", "employee": "UEMPLOYEE", "bot": "UBOT"}


@pytest.fixture
def system(tmp_path, monkeypatch):
    settings = Settings(
        bot_token="xoxb-fixture",
        app_token="xapp-fixture",
        team_id="TDEMO",
        employee_user_id="UEMPLOYEE",
        api_url="http://127.0.0.1:8129",
        state_path=tmp_path / "slack.db",
    )
    store = Store(settings.state_path)
    api = Mock()
    api.me.return_value = {"user": {"role": "employee"}, "backend_id": BACKEND}
    slack = Mock()
    slack.auth_test.return_value = {"team_id": "TDEMO", "user_id": "UBOT"}
    create_service = Mock()
    recover = Mock()
    socket = Mock()
    monkeypatch.setattr(startup, "PeopleFlowClient", Mock(return_value=api))
    monkeypatch.setattr(startup, "WebClient", Mock(return_value=slack))
    monkeypatch.setattr(startup, "EmployeeApp", create_service)
    monkeypatch.setattr(startup, "recover_inbox", recover)
    monkeypatch.setattr(startup, "create_bolt_app", Mock())
    monkeypatch.setattr(startup, "SocketModeHandler", socket)
    return settings, store, api, create_service, recover, socket


def test_changed_backend_rejects_saved_actions_before_recovery(system):
    settings, store, _, service, recover, socket = system
    previous = {**INSTALLATION, "backend": OTHER_BACKEND}
    store.set("installation", previous)
    store.receive_inbox("receipt", "operation", "ask", {"text": "pending fixture"})

    with ExitStack() as stack, pytest.raises(ValueError, match="another PeopleFlow backend"):
        startup.run(settings, False, stack)

    service.assert_not_called()
    recover.assert_not_called()
    socket.assert_not_called()
    assert store.get("installation") == previous
    assert store.inbox_item("receipt")["state"] == "pending"


@pytest.mark.parametrize("legacy", [False, True])
def test_same_backend_survives_port_change_and_upgrades_legacy_installation(system, legacy):
    settings, store, _, service, recover, socket = system
    store.set("installation", INSTALLATION if legacy else {**INSTALLATION, "backend": BACKEND})

    with ExitStack() as stack:
        startup.run(settings, False, stack)

    assert store.get("installation") == {**INSTALLATION, "backend": BACKEND}
    service.assert_called_once()
    recover.assert_called_once_with(service.return_value)
    socket.return_value.start.assert_called_once()
    socket.return_value.close.assert_called_once()


def test_backend_without_storage_identity_is_rejected_before_delivery(system):
    settings, _, api, service, recover, socket = system
    api.me.return_value = {"user": {"role": "employee"}}

    with ExitStack() as stack, pytest.raises(ValueError, match="storage identity"):
        startup.run(settings, False, stack)

    service.assert_not_called()
    recover.assert_not_called()
    socket.assert_not_called()


def test_connectivity_check_never_starts_a_receiver_or_replays_actions(system):
    settings, _, _, service, recover, socket = system
    with ExitStack() as stack:
        startup.run(settings, True, stack)
    service.assert_not_called()
    recover.assert_not_called()
    socket.assert_not_called()
