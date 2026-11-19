"""HTTPS provider connections through the user's environment or Windows system proxy."""

import base64
import http.client
import ssl
from urllib.parse import unquote, urlsplit
from urllib.request import getproxies, proxy_bypass


class ProxyConfigurationError(ValueError):
    """Static safe error; proxy addresses may include credentials."""


def https_proxy_for(host):
    if proxy_bypass(host):
        return None
    proxy = getproxies().get("https")
    if not proxy:
        return None
    try:
        if any(ord(char) < 33 or ord(char) == 127 for char in proxy):
            raise ValueError
        parsed = urlsplit(proxy)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.port == 0
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        # The SDK accepts credentials in the proxy URL; they are never logged.
        return proxy
    except (TypeError, ValueError):
        raise ProxyConfigurationError(
            "Configure a valid HTTP CONNECT proxy in system settings or HTTPS_PROXY."
        ) from None


def https_connection(host, *, timeout=10, connection_factory=None):
    """CONNECT carries TLS to the provider; tokens never go into proxy headers."""
    factory = connection_factory or http.client.HTTPSConnection
    context = ssl.create_default_context()
    proxy = https_proxy_for(host)
    if proxy is None:
        return factory(host, timeout=timeout, context=context)
    parsed = urlsplit(proxy)
    connection = factory(parsed.hostname, parsed.port or 80, timeout=timeout, context=context)
    headers = {}
    if parsed.username is not None:
        credentials = unquote(parsed.username) + ":" + unquote(parsed.password or "")
        headers["Proxy-Authorization"] = "Basic " + base64.b64encode(
            credentials.encode("utf-8")
        ).decode("ascii")
    try:
        connection.set_tunnel(host, 443, headers=headers)
    except Exception:
        connection.close()
        raise
    return connection
