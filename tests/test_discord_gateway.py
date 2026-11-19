import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from integrations.discord_gateway import (
    DiscordGatewayWorker,
    _ConfigurationError,
    _GatewayClient,
    _GatewayLock,
)

APP_ID = "123456789012345678"
USER_ID = "987654321012345678"


def service():
    return SimpleNamespace(
        discord_application_id=APP_ID,
        discord_connection_mode="gateway",
        targets={"discord": SimpleNamespace(token="synthetic-bot-token")},
        configured=Mock(return_value=True),
        accept_link_code=Mock(return_value="Confirm the connection in Personal notifications."),
    )


def interaction(identifier="123456789012345679"):
    return SimpleNamespace(
        id=identifier,
        application_id=APP_ID,
        type=SimpleNamespace(value=2),
        user=SimpleNamespace(id=USER_ID),
        data={
            "name": "peopleflow",
            "options": [{"name": "link", "options": [{"name": "code", "value": "a" * 32}]}],
        },
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def test_link_uses_authenticated_identity_and_defers_before_storage():
    async def run():
        item = interaction()
        target = service()
        order = []
        item.response.defer.side_effect = lambda **kwargs: order.append("deferred")
        target.accept_link_code.side_effect = lambda *args: order.append("stored") or "Confirm."
        worker = DiscordGatewayWorker(target)
        worker.verified = True
        await worker.handle_interaction(item)
        assert order == ["deferred", "stored"]
        target.accept_link_code.assert_called_once_with("discord", "a" * 32, USER_ID, APP_ID)
        item.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        assert item.edit_original_response.await_args.kwargs["content"] == "Confirm."
        assert item.edit_original_response.await_args.kwargs["allowed_mentions"].to_dict() == {
            "parse": []
        }

    asyncio.run(run())


def test_replayed_and_concurrent_events_do_not_repeat_claim_or_response():
    async def run():
        target = service()
        worker = DiscordGatewayWorker(target)
        worker.verified = True
        first, duplicate = interaction(), interaction()
        await asyncio.gather(worker.handle_interaction(first), worker.handle_interaction(duplicate))
        await worker.handle_interaction(duplicate)
        target.accept_link_code.assert_called_once()
        first.response.defer.assert_awaited_once()
        duplicate.response.defer.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "guard", ["unverified", "disabled", "wrong_app", "changed_app", "http", "rotated"]
)
def test_untrusted_or_no_longer_configured_session_never_claims_code(guard):
    async def run():
        target = service()
        worker = DiscordGatewayWorker(target)
        worker.verified = guard != "unverified"
        item = interaction()
        if guard == "disabled":
            target.configured.return_value = False
        elif guard == "wrong_app":
            item.application_id = "111111111111111111"
        elif guard == "changed_app":
            target.discord_application_id = "111111111111111111"
        elif guard == "http":
            target.discord_connection_mode = "http"
        elif guard == "rotated":
            target.targets["discord"].token = "rotated-token"
        await worker.handle_interaction(item)
        target.accept_link_code.assert_not_called()
        item.response.defer.assert_not_awaited()

    asyncio.run(run())


def test_invalid_command_returns_private_error_without_storage_change():
    async def run():
        target = service()
        worker = DiscordGatewayWorker(target)
        worker.verified = True
        item = interaction()
        item.data["name"] = "manager_approve"
        await worker.handle_interaction(item)
        target.accept_link_code.assert_not_called()
        item.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        assert (
            item.edit_original_response.await_args.kwargs["content"]
            == "Unsupported Discord command."
        )

    asyncio.run(run())


def test_reply_failure_does_not_repeat_saved_claim_or_leak_secret(caplog):
    async def run():
        target = service()
        worker = DiscordGatewayWorker(target)
        worker.verified = True
        item = interaction()
        item.edit_original_response.side_effect = OSError("private-provider-token")
        await worker.handle_interaction(item)
        await worker.handle_interaction(item)
        target.accept_link_code.assert_called_once()
        assert "private-provider-token" not in caplog.text
        assert "response failed" in caplog.text

    asyncio.run(run())


def test_storage_error_returns_safe_private_response(caplog):
    async def run():
        target = service()
        target.accept_link_code.side_effect = RuntimeError("private-code")
        worker = DiscordGatewayWorker(target)
        worker.verified = True
        item = interaction()
        await worker.handle_interaction(item)
        assert "Unable to connect" in item.edit_original_response.await_args.kwargs["content"]
        assert "private-code" not in caplog.text

    asyncio.run(run())


@pytest.mark.parametrize("mismatch", ["app", "endpoint", "none"])
def test_setup_checks_provider_application_and_endpoint_before_events(mismatch):
    async def run():
        worker = DiscordGatewayWorker(service())
        client = _GatewayClient(worker)
        client.application_info = AsyncMock(
            return_value=SimpleNamespace(
                id="999999999999999999" if mismatch == "app" else APP_ID,
                interactions_endpoint_url="https://example.invalid/interactions"
                if mismatch == "endpoint"
                else None,
            )
        )
        try:
            assert client.intents.value == 0
            if mismatch == "none":
                await client.setup_hook()
                assert worker.verified
                await client.on_ready()
                assert worker.status == "connected"
                await client.on_disconnect()
                assert worker.status == "reconnecting"
                await client.on_resumed()
                assert worker.status == "connected"
            else:
                with pytest.raises(_ConfigurationError):
                    await client.setup_hook()
                assert not worker.verified
        finally:
            await client.close()

    asyncio.run(run())


def test_local_os_lock_allows_only_one_bot_session(tmp_path):
    first = _GatewayLock(APP_ID, tmp_path)
    second = _GatewayLock(APP_ID, tmp_path)
    try:
        assert first.acquire()
        assert not second.acquire()
        first.release()
        assert second.acquire()
    finally:
        first.release()
        second.release()


class FakeLock:
    def __init__(self, application_id):
        self.acquired = 0
        self.released = 0

    def acquire(self):
        self.acquired += 1
        return True

    def release(self):
        self.released += 1


class FakeClient:
    def __init__(self, worker):
        self.worker = worker
        self.started = asyncio.Event()
        self.closed = 0

    async def start(self, token, *, reconnect):
        assert token == "synthetic-bot-token"
        assert reconnect is True
        self.worker.verified = True
        self.worker._connected()
        self.started.set()
        await asyncio.Event().wait()

    async def close(self):
        self.closed += 1


def test_start_is_nonblocking_idempotent_and_stop_releases_resources():
    async def run():
        target = service()
        lock = FakeLock(APP_ID)
        clients = []

        def factory(worker):
            client = FakeClient(worker)
            clients.append(client)
            return client

        worker = DiscordGatewayWorker(target, client_factory=factory, lock_factory=lambda app: lock)
        worker.start()
        first_task = worker.task
        worker.start()
        await asyncio.sleep(0)
        assert worker.task is first_task
        assert len(clients) == 1
        assert worker.status == "connected"
        await worker.stop()
        assert clients[0].closed == 1
        assert lock.released == 1
        assert worker.task is None
        assert worker.status == "stopped"
        assert not worker.verified

    asyncio.run(run())


def test_startup_network_failure_retries_with_backoff_and_safe_logs(caplog):
    async def run():
        delays, clients = [], []
        ready = asyncio.Event()

        class Client(FakeClient):
            async def start(self, token, *, reconnect):
                if len(clients) < 3:
                    raise OSError("private-token")
                ready.set()
                await super().start(token, reconnect=reconnect)

        async def pause(delay):
            delays.append(delay)
            await asyncio.sleep(0)

        def factory(worker):
            client = Client(worker)
            clients.append(client)
            return client

        worker = DiscordGatewayWorker(
            service(), client_factory=factory, lock_factory=FakeLock, sleep=pause
        )
        worker.start()
        await asyncio.wait_for(ready.wait(), timeout=2)
        assert worker.status == "connected"
        assert 2 <= delays[0] <= 2.4
        assert 4 <= delays[1] <= 4.8
        assert "private-token" not in caplog.text
        await worker.stop()
        assert all(client.closed == 1 for client in clients)

    asyncio.run(run())


def test_bad_credentials_stop_retrying_without_leaking_provider_response(caplog):
    async def run():
        class Client(FakeClient):
            async def start(self, token, *, reconnect):
                raise discord.LoginFailure("private-invalid-token")

        worker = DiscordGatewayWorker(service(), client_factory=Client, lock_factory=FakeLock)
        worker.start()
        await asyncio.wait_for(worker.task, timeout=2)
        assert worker.status == "error"
        assert worker.error_code == "invalid_credentials"
        assert "private-invalid-token" not in caplog.text
        await worker.stop()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["http", "unconfigured"])
def test_no_background_connection_for_http_or_unconfigured_bot(mode):
    async def run():
        target = service()
        if mode == "http":
            target.discord_connection_mode = mode
        else:
            target.configured.return_value = False
        factory = Mock()
        worker = DiscordGatewayWorker(target, client_factory=factory)
        worker.start()
        assert worker.task is None
        factory.assert_not_called()

    asyncio.run(run())


def test_sdk_debug_payloads_do_not_propagate_to_application_logs(caplog):
    async def run():
        worker = DiscordGatewayWorker(service(), client_factory=FakeClient, lock_factory=FakeLock)
        worker.start()
        with caplog.at_level(logging.DEBUG):
            assert logging.getLogger("discord").propagate is False
            assert logging.getLogger("discord.gateway").parent.name == "discord"
            logging.getLogger("discord.gateway").debug("private-link-code")
            logging.getLogger("discord.http").warning("private-callback-token")
        assert "private-link-code" not in caplog.text
        assert "private-callback-token" not in caplog.text
        await worker.stop()

    asyncio.run(run())


def test_shutdown_cancels_sdk_handlers_before_they_can_claim_or_reply():
    async def run():
        target = service()
        worker = DiscordGatewayWorker(target)
        worker.verified = True
        item = interaction()
        deferring = asyncio.Event()

        async def defer(**kwargs):
            deferring.set()
            await asyncio.Event().wait()

        item.response.defer.side_effect = defer
        pending = asyncio.create_task(worker.handle_interaction(item))
        await asyncio.wait_for(deferring.wait(), timeout=2)
        await worker.stop()
        assert pending.cancelled()
        assert not worker._handlers
        target.accept_link_code.assert_not_called()
        item.edit_original_response.assert_not_awaited()

    asyncio.run(run())


def test_unexpected_worker_setup_failure_does_not_break_shutdown(caplog):
    async def run():
        worker = DiscordGatewayWorker(
            service(), lock_factory=Mock(side_effect=RuntimeError("private-error"))
        )
        worker.start()
        await asyncio.wait_for(worker.task, timeout=2)
        assert worker.status == "error"
        assert worker.error_code == "local_worker_failed"
        await worker.stop()
        assert "private-error" not in caplog.text

    asyncio.run(run())
