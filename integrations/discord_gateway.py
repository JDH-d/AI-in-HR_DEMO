"""Receive verified Discord commands over an outbound, reconnecting Gateway session."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import random
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

import discord

from integrations.discord_commands import DiscordCommandError, process_discord_interaction
from integrations.network import ProxyConfigurationError, https_proxy_for

logger = logging.getLogger(__name__)


class _ConfigurationError(Exception):
    """Only static error codes are allowed; never include provider responses."""


class _GatewayLock:
    """One local Gateway owner per bot, including separate uvicorn processes.

    The OS releases this lock on a crash. It contains no token or user data and
    does not change the application database. Multiple hosts need a shared lease.
    """

    def __init__(self, application_id, directory=None):
        digest = hashlib.sha256(str(application_id).encode()).hexdigest()[:32]
        self.path = Path(directory or tempfile.gettempdir()) / f"peopleflow-discord-{digest}.lock"
        self.handle = None

    def acquire(self):
        handle = self.path.open("a+b")
        try:
            if self.path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


class _GatewayClient(discord.Client):
    def __init__(self, worker):
        # No messages, member list, presence or privileged intent is requested.
        super().__init__(
            intents=discord.Intents.none(),
            max_messages=None,
            allowed_mentions=discord.AllowedMentions.none(),
            proxy=https_proxy_for("discord.com"),
        )
        self.worker = worker

    async def setup_hook(self):
        # Authentication happens before this hook, and this hook precedes events.
        info = await self.application_info()
        if str(info.id) != self.worker.application_id:
            raise _ConfigurationError("application_mismatch")
        if info.interactions_endpoint_url:
            raise _ConfigurationError("http_endpoint_configured")
        self.worker.verified = True

    async def on_ready(self):
        self.worker._connected()

    async def on_resumed(self):
        self.worker._connected()

    async def on_disconnect(self):
        if not self.worker.stopping:
            if self.worker.status != "reconnecting":
                logger.warning("Discord Gateway disconnected; reconnecting")
            self.worker.status = "reconnecting"

    async def on_interaction(self, interaction):
        await self.worker.handle_interaction(interaction)

    async def on_error(self, event_method, *args, **kwargs):
        # The SDK's default traceback can contain a callback URL or private input.
        logger.warning("Discord Gateway event could not be handled")


class DiscordGatewayWorker:
    def __init__(self, service, *, client_factory=None, lock_factory=None, sleep=asyncio.sleep):
        self.service = service
        self.application_id = str(service.discord_application_id)
        self.token = service.targets["discord"].token
        self.client_factory = client_factory or _GatewayClient
        self.lock_factory = lock_factory or _GatewayLock
        self.sleep = sleep
        self.status = "stopped"
        self.error_code = ""
        self.stopping = False
        self.verified = False
        self.task = None
        self.client = None
        self._seen = OrderedDict()
        self._failures = 0
        self._handlers = set()

    def start(self):
        if self.task is not None and not self.task.done():
            return
        if getattr(
            self.service, "discord_connection_mode", "gateway"
        ) != "gateway" or not self.service.configured("discord"):
            self.status = "not_configured"
            return
        # SDK DEBUG output includes interaction tokens and raw message payloads.
        # Keep our static status logs, and prevent SDK records reaching root handlers.
        logging.getLogger("discord")
        for name in list(logging.Logger.manager.loggerDict):
            if name == "discord" or name.startswith("discord."):
                sdk_logger = logging.getLogger(name)
                sdk_logger.handlers = [logging.NullHandler()]
                sdk_logger.propagate = False
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
            logger.addHandler(handler)
        self.stopping = False
        self.status = "connecting"
        self.error_code = ""
        self.task = asyncio.create_task(self._run(), name="discord-gateway")

    def _connected(self):
        if self.verified and not self.stopping:
            self.status = "connected"
            self.error_code = ""
            self._failures = 0
            logger.info("Discord Gateway connected; account linking is available")

    async def _run(self):
        lock = None
        try:
            lock = self.lock_factory(self.application_id)
            while not self.stopping:
                try:
                    acquired = lock.acquire()
                except OSError:
                    self.status, self.error_code = "error", "local_lock_unavailable"
                    logger.error(
                        "Discord Gateway local lock unavailable; check temporary directory"
                    )
                    return
                if acquired:
                    break
                self.status = "another_process"
                await self.sleep(5)
            while not self.stopping:
                self.verified = False
                self.status = "connecting"
                try:
                    self.client = self.client_factory(self)
                    await self.client.start(self.token, reconnect=True)
                except ProxyConfigurationError:
                    self.status, self.error_code = "error", "proxy_configuration"
                    logger.error(
                        "Discord proxy configuration is invalid; check system HTTP proxy settings and restart"
                    )
                    return
                except _ConfigurationError as exc:
                    self.status = "error"
                    self.error_code = (
                        "http_endpoint_configured"
                        if str(exc) == "http_endpoint_configured"
                        else "application_mismatch"
                    )
                    if self.error_code == "http_endpoint_configured":
                        logger.error(
                            "Discord Gateway unavailable: clear Interactions Endpoint URL in "
                            "Discord Developer Portal and restart the application"
                        )
                    else:
                        logger.error(
                            "Discord Gateway unavailable: token and Application ID must belong "
                            "to the same Discord application; correct settings and restart"
                        )
                    return
                except (discord.LoginFailure, discord.PrivilegedIntentsRequired):
                    self.status, self.error_code = "error", "invalid_credentials"
                    logger.error("Discord Gateway login rejected; check bot settings and restart")
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.error_code = "connection_failed"
                    logger.warning(
                        "Discord Gateway connection failed; retrying without affecting requests"
                    )
                finally:
                    self.verified = False
                    if self.client is not None:
                        try:
                            await asyncio.wait_for(self.client.close(), timeout=5)
                        except (Exception, asyncio.CancelledError):
                            pass
                        self.client = None
                if not self.stopping:
                    self.status = "reconnecting"
                    delay = min(60, 2 ** min(self._failures + 1, 6))
                    self._failures += 1
                    await self.sleep(delay + random.uniform(0, delay * 0.2))
        except asyncio.CancelledError:
            raise
        except Exception:
            self.status, self.error_code = "error", "local_worker_failed"
            logger.error("Discord Gateway worker unavailable; check settings and restart")
        finally:
            if lock is not None:
                try:
                    lock.release()
                except Exception:
                    logger.warning("Discord Gateway local lock cleanup failed")

    async def stop(self):
        self.stopping = True
        handlers = list(self._handlers)
        for handler in handlers:
            handler.cancel()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None
        self.verified = False
        self.status = "stopped"

    async def handle_interaction(self, interaction):
        task = asyncio.current_task()
        self._handlers.add(task)
        try:
            await self._handle_interaction(interaction)
        finally:
            self._handlers.discard(task)

    async def _handle_interaction(self, interaction):
        if (
            not self.verified
            or self.stopping
            or not self.service.configured("discord")
            or getattr(self.service, "discord_connection_mode", "gateway") != "gateway"
            or str(self.service.discord_application_id) != self.application_id
            or self.service.targets["discord"].token != self.token
        ):
            return
        # Discord interaction IDs are unique. Persisted link claims also remain
        # idempotent after reconnect/restart; this cache avoids duplicate callbacks.
        now = time.monotonic()
        while self._seen and (
            next(iter(self._seen.values())) < now - 900 or len(self._seen) >= 4096
        ):
            self._seen.popitem(last=False)
        identifier = str(interaction.id)
        if identifier in self._seen:
            return
        self._seen[identifier] = now
        try:
            if str(interaction.application_id) != self.application_id:
                return
            # Acknowledge before database work: Discord's initial deadline is 3s.
            await asyncio.wait_for(
                interaction.response.defer(ephemeral=True, thinking=True), timeout=2.5
            )
            payload = {
                "id": identifier,
                "application_id": str(interaction.application_id),
                "type": interaction.type.value,
                "data": interaction.data,
                "user": {"id": str(interaction.user.id)},
            }
            try:
                response = await asyncio.to_thread(
                    process_discord_interaction, self.service, payload
                )
                content = response["data"]["content"]
            except DiscordCommandError as exc:
                content = exc.detail
            except Exception:
                logger.warning("Discord account linking failed; retry from Personal notifications")
                content = (
                    "Unable to connect your account. Refresh Personal notifications and try again."
                )
            if self.stopping:
                return
            await asyncio.wait_for(
                interaction.edit_original_response(
                    content=content, allowed_mentions=discord.AllowedMentions.none()
                ),
                timeout=10,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not undo an already saved link claim on a lost reply.
            logger.warning(
                "Discord command response failed; check Personal notifications in the app"
            )
