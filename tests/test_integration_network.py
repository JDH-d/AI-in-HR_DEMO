"""Proxy routing keeps provider authentication inside verified TLS, without real requests."""

import asyncio
import json
import ssl
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations import network
from integrations.direct_messages import DirectMessageTarget, DirectMessageTransport
from integrations.discord_gateway import _GatewayClient
from scripts.register_discord_command import register_command


@pytest.fixture
def system_proxy(monkeypatch):
    proxies = {"https": "http://127.0.0.1:10809"}
    monkeypatch.setattr(network, "getproxies", lambda: proxies)
    monkeypatch.setattr(network, "proxy_bypass", lambda host: False)
    return proxies


def test_https_tunnel_uses_system_proxy_and_verifies_provider_certificate(system_proxy):
    factory = Mock()
    connection = network.https_connection("discord.com", timeout=7, connection_factory=factory)
    assert factory.call_args.args == ("127.0.0.1", 10809)
    assert factory.call_args.kwargs["timeout"] == 7
    context = factory.call_args.kwargs["context"]
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    connection.set_tunnel.assert_called_once_with("discord.com", 443, headers={})


def test_no_proxy_exclusion_connects_directly(system_proxy, monkeypatch):
    monkeypatch.setattr(network, "proxy_bypass", lambda host: host == "discord.com")
    factory = Mock()
    connection = network.https_connection("discord.com", connection_factory=factory)
    assert factory.call_args.args == ("discord.com",)
    connection.set_tunnel.assert_not_called()


def test_no_proxy_configuration_keeps_direct_connections(system_proxy):
    system_proxy.clear()
    factory = Mock()
    connection = network.https_connection("slack.com", connection_factory=factory)
    assert factory.call_args.args == ("slack.com",)
    connection.set_tunnel.assert_not_called()


def test_proxy_authentication_is_separate_from_bot_authentication(system_proxy):
    system_proxy["https"] = "http://proxy-user:private-proxy-password@127.0.0.1:10809"
    factory = Mock()
    response = Mock(status=200)
    response.read.return_value = b'{"ok": true}'
    response.getheader.return_value = None
    factory.return_value.getresponse.return_value = response
    target = DirectMessageTarget("discord", "synthetic.bot.token")
    _, result = DirectMessageTransport(connection_factory=factory)._post(
        target, "/api/v10/users/@me/channels", {"recipient_id": "123456789"}
    )
    assert not result.error_code
    tunnel = factory.return_value.set_tunnel.call_args
    request = factory.return_value.request.call_args
    assert "Proxy-Authorization" in tunnel.kwargs["headers"]
    assert "Authorization" not in tunnel.kwargs["headers"]
    assert request.kwargs["headers"]["Authorization"] == "Bot synthetic.bot.token"
    assert "Proxy-Authorization" not in request.kwargs["headers"]
    assert "private-proxy-password" not in repr(request.kwargs)


@pytest.mark.parametrize(
    "proxy",
    [
        "socks5://private-password@127.0.0.1:1080",
        "https://private-password@proxy.test",
        "http://",
        "http://proxy.test:70000",
        "http://proxy.test:0",
        "http://proxy.test/private-password",
        "http://proxy.test?private-password",
        "http://proxy.test#private-password",
        "http://proxy.test\r\nprivate-password",
    ],
)
def test_invalid_proxy_fails_closed_without_secret_in_error(system_proxy, proxy):
    system_proxy["https"] = proxy
    factory = Mock()
    with pytest.raises(network.ProxyConfigurationError) as error:
        network.https_connection("discord.com", connection_factory=factory)
    assert proxy not in str(error.value)
    assert "private-password" not in str(error.value)
    factory.assert_not_called()


def test_gateway_rest_and_websocket_share_system_proxy(system_proxy):
    async def run():
        client = _GatewayClient(SimpleNamespace())
        try:
            assert client.http.proxy == system_proxy["https"]
        finally:
            await client.close()

    asyncio.run(run())


def test_registration_uses_same_https_tunnel(system_proxy):
    factory = Mock()
    response = Mock(status=201)
    response.read.return_value = json.dumps(
        {
            "application_id": "123456789",
            "id": "223456789",
            "name": "peopleflow",
            "type": 1,
        }
    ).encode()
    factory.return_value.getresponse.return_value = response
    register_command("123456789", "synthetic.bot.token", connection_factory=factory)
    assert factory.call_args.args == ("127.0.0.1", 10809)
    factory.return_value.set_tunnel.assert_called_once_with("discord.com", 443, headers={})
    factory.return_value.close.assert_called_once()


def test_proxy_outage_never_falls_back_to_direct_network(system_proxy):
    factory = Mock(side_effect=OSError("private-password"))
    _, result = DirectMessageTransport(connection_factory=factory)._post(
        DirectMessageTarget("discord", "synthetic.bot.token"), "/api/v10/test", {}
    )
    assert result.error_code == "network" and result.retryable
    factory.assert_called_once()


def test_invalid_proxy_is_an_actionable_delivery_error(system_proxy):
    system_proxy["https"] = "socks5://private-password@localhost:1080"
    factory = Mock()
    _, result = DirectMessageTransport(connection_factory=factory)._post(
        DirectMessageTarget("discord", "synthetic.bot.token"), "/api/v10/test", {}
    )
    assert result.error_code == "proxy_configuration" and not result.retryable
    factory.assert_not_called()
