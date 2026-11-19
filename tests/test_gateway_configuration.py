"""Gateway configuration and application lifecycle, with no provider traffic."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from services import runtime
from services.auth_service import DEMO_IDENTITIES
from services.notification_service import NotificationService
from services.workflow_service import WorkflowService


@pytest.fixture
def service_factory(tmp_path):
    workflow = WorkflowService(str(tmp_path / "workflow.db"))

    def create(**overrides):
        values = {
            "discord_token": "synthetic-bot-token",
            "discord_application_id": "123456",
            "app_url": "http://127.0.0.1:5173",
            "transport": Mock(),
        }
        values.update(overrides)
        return NotificationService(workflow.store.db_path, **values)

    return create


def test_default_gateway_can_link_without_public_key_or_enabled_delivery(service_factory):
    service = service_factory()
    assert service.discord_connection_mode == "gateway"
    assert service.discord_public_key == ""
    assert service.configured("discord")
    state = next(item for item in service.overview()["items"] if item["provider"] == "discord")
    assert not state["enabled"]
    assert state["configuration_error"] == ""
    code = service.link_code("discord", DEMO_IDENTITIES["employee"])
    assert code["command"] == "/peopleflow link code:" + code["code"]


@pytest.mark.parametrize(
    ("mode", "public_key", "configured"),
    [
        ("gateway", "", True),
        ("gateway", "unused-old-key", True),
        ("http", "a" * 64, True),
        ("http", "", False),
        ("http", "g" * 64, False),
        ("http", "a" * 63, False),
        ("invalid", "a" * 64, False),
        ("", "a" * 64, False),
    ],
)
def test_discord_configuration_requirements(service_factory, mode, public_key, configured):
    service = service_factory(discord_connection_mode=mode, discord_public_key=public_key)
    assert service.configured("discord") is configured


@pytest.mark.parametrize(
    "overrides",
    [{"discord_token": ""}, {"discord_application_id": ""}, {"discord_application_id": "abc"}],
)
def test_gateway_still_requires_bot_identity(service_factory, overrides):
    assert not service_factory(**overrides).configured("discord")


def test_switching_transport_preserves_confirmed_personal_destination(service_factory):
    previous = service_factory(discord_connection_mode="http", discord_public_key="a" * 64)
    employee = DEMO_IDENTITIES["employee"]
    code = previous.link_code("discord", employee)["code"]
    previous.accept_link_code("discord", code, "111111", "123456")
    pending = previous.accounts.connection("discord", employee.id, previous.clock())["pending"]
    previous.confirm_connection("discord", employee, pending["challenge_id"])
    saved = previous.destination("discord", employee.id)

    gateway = service_factory()
    assert gateway.destination("discord", employee.id) == saved
    states = gateway.connections(employee)["items"]
    assert next(item for item in states if item["provider"] == "discord")["connected"]
    assert gateway.destination("discord", DEMO_IDENTITIES["manager"].id) is None


def mock_lifecycle(monkeypatch, service):
    workers = []

    def make_worker(_service):
        assert _service is service
        worker = Mock()
        worker.stop = AsyncMock()
        workers.append(worker)
        return worker

    constructor = Mock(side_effect=make_worker)
    monkeypatch.setattr("services.notification_service.DiscordGatewayWorker", constructor)

    async def wait_until_stopped(_provider):
        await service.stopping.wait()

    monkeypatch.setattr(service, "_worker", wait_until_stopped)
    return constructor, workers


def test_gateway_start_stop_are_idempotent_and_restartable(service_factory, monkeypatch):
    service = service_factory()
    constructor, workers = mock_lifecycle(monkeypatch, service)

    async def exercise():
        await service.stop()
        service.start()
        tasks = list(service.tasks)
        service.start()
        constructor.assert_called_once_with(service)
        workers[0].start.assert_called_once_with()
        assert service.tasks == tasks

        await asyncio.wait_for(service.stop(), timeout=2)
        await service.stop()
        workers[0].stop.assert_awaited_once_with()
        assert service.tasks == []
        assert service.gateway is None
        assert all(task.done() for task in tasks)

        service.start()
        assert constructor.call_count == 2
        workers[1].start.assert_called_once_with()
        await asyncio.wait_for(service.stop(), timeout=2)
        workers[1].stop.assert_awaited_once_with()

    asyncio.run(exercise())
    service.transport.send.assert_not_called()


def exercise_gateway_failure(service, monkeypatch, stage):
    worker = Mock()
    worker.stop = AsyncMock()
    getattr(worker, stage).side_effect = RuntimeError("synthetic-private-token-in-provider-error")
    monkeypatch.setattr(
        "services.notification_service.DiscordGatewayWorker", Mock(return_value=worker)
    )

    async def exercise():
        providers_started = set()
        both_started = asyncio.Event()

        async def main_worker(provider):
            providers_started.add(provider)
            if providers_started == {"slack", "discord"}:
                both_started.set()
            await service.stopping.wait()

        monkeypatch.setattr(service, "_worker", main_worker)
        service.start()
        tasks = list(service.tasks)
        await asyncio.wait_for(both_started.wait(), timeout=2)
        assert all(not task.done() for task in tasks)
        await asyncio.wait_for(service.stop(), timeout=2)
        assert all(task.done() for task in tasks)
        assert service.tasks == []
        assert service.gateway is None
        worker.start.assert_called_once_with()
        worker.stop.assert_awaited_once_with()

    asyncio.run(exercise())
    service.transport.send.assert_not_called()


def test_gateway_start_failure_keeps_main_workers_running(service_factory, monkeypatch, caplog):
    exercise_gateway_failure(service_factory(), monkeypatch, "start")
    assert "Discord Gateway startup failed; core workflows remain available" in caplog.text
    assert "synthetic-private-token-in-provider-error" not in caplog.text


def test_gateway_stop_failure_still_finishes_main_workers(service_factory, monkeypatch, caplog):
    exercise_gateway_failure(service_factory(), monkeypatch, "stop")
    assert "Discord Gateway cleanup failed; continuing application shutdown" in caplog.text
    assert "synthetic-private-token-in-provider-error" not in caplog.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"discord_connection_mode": "http", "discord_public_key": "a" * 64},
        {"discord_connection_mode": "invalid"},
        {"discord_token": ""},
    ],
)
def test_gateway_does_not_start_for_http_or_invalid_configuration(
    service_factory, monkeypatch, overrides
):
    service = service_factory(**overrides)
    constructor, _ = mock_lifecycle(monkeypatch, service)

    async def exercise():
        service.start()
        await asyncio.wait_for(service.stop(), timeout=2)

    asyncio.run(exercise())
    constructor.assert_not_called()
    service.transport.send.assert_not_called()


@pytest.mark.parametrize("mode", ["gateway", "http"])
def test_runtime_forwards_selected_discord_connection_mode(monkeypatch, mode):
    monkeypatch.setattr(runtime.settings, "DISCORD_CONNECTION_MODE", mode)
    monkeypatch.setattr(runtime.settings, "validate_auth_settings", Mock())
    for name in (
        "DemoAuthService",
        "WorkflowService",
        "AISettingsStore",
        "LLMService",
        "ChatLogStore",
        "DocumentStore",
        "PromptStore",
        "ChatService",
        "ConversationStore",
        "ConversationService",
        "DocumentService",
        "AISettingsService",
        "QualityService",
    ):
        monkeypatch.setattr(runtime, name, Mock())
    notifications = Mock()
    monkeypatch.setattr(runtime, "NotificationService", notifications)

    result = runtime.get_runtime.__wrapped__()

    assert result.notification_service is notifications.return_value
    assert notifications.call_args.kwargs["discord_connection_mode"] == mode
