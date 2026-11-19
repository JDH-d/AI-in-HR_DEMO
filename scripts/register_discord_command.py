"""Preview or explicitly register only the PeopleFlow Discord linking command."""

from __future__ import annotations

import argparse
import http.client
import json
import re
import sys

from integrations.network import ProxyConfigurationError, https_connection


class RegistrationError(RuntimeError):
    """Safe configuration/provider errors; never include credentials or response bodies."""


def command_payload() -> dict:
    # Guild installation also supports global commands in the bot's own DM.
    # https://docs.discord.com/developers/interactions/application-commands#contexts
    return {
        "name": "peopleflow",
        "type": 1,
        "description": "Connect your PeopleFlow account for personal notifications.",
        "integration_types": [0],
        "contexts": [0, 1],
        "options": [
            {
                "name": "link",
                "type": 1,
                "description": "Link the account using a one-time code from PeopleFlow.",
                "options": [
                    {
                        "name": "code",
                        "type": 3,
                        "description": "One-time code shown in your PeopleFlow account.",
                        "required": True,
                    }
                ],
            }
        ],
    }


def registration_path(application_id: str) -> str:
    if not isinstance(application_id, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", application_id):
        raise RegistrationError("Set a valid DISCORD_APPLICATION_ID in .env.integrations.")
    return f"/api/v10/applications/{application_id}/commands"


def register_command(application_id: str, token: str, *, connection_factory=None) -> None:
    path = registration_path(application_id)
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._-]{10,}", token):
        raise RegistrationError(
            "Set DISCORD_BOT_TOKEN in .env.integrations; do not pass it on the command line."
        )
    connection = None
    try:
        factory = connection_factory or http.client.HTTPSConnection
        connection = https_connection("discord.com", timeout=10, connection_factory=factory)
        connection.set_debuglevel(0)
        # POST upserts this name/type only. PUT here would overwrite every global command.
        connection.request(
            "POST",
            path,
            body=json.dumps(command_payload()).encode("utf-8"),
            headers={
                "Authorization": "Bot " + token,
                "Content-Type": "application/json",
                "User-Agent": "PeopleFlow-Command-Setup/2.2",
            },
        )
        response = connection.getresponse()
        if response.status in {401, 403}:
            raise RegistrationError(
                "Discord rejected registration. Check the bot token and application ID belong to the same app."
            )
        if response.status == 429:
            raise RegistrationError(
                "Discord rate limited registration. Wait before running --register again."
            )
        if response.status >= 500:
            raise RegistrationError(
                "Discord is temporarily unavailable. Try --register again later."
            )
        if response.status not in {200, 201}:
            raise RegistrationError(
                "Discord did not accept the command. Check the application setup; redirects are not followed."
            )
        body = response.read(65537)
        if len(body) > 65536:
            raise RegistrationError("Discord returned an unexpected registration response.")
        try:
            result = json.loads(body)
        except (UnicodeError, ValueError):
            raise RegistrationError(
                "Discord returned an unexpected registration response."
            ) from None
        if (
            not isinstance(result, dict)
            or result.get("name") != "peopleflow"
            or result.get("type") != 1
            or result.get("application_id") != application_id
            or not re.fullmatch(r"[1-9][0-9]{0,19}", str(result.get("id", "")))
        ):
            raise RegistrationError("Discord did not confirm the PeopleFlow command registration.")
    except ProxyConfigurationError:
        raise RegistrationError(
            "Check the system HTTP proxy or HTTPS_PROXY setting, then try again."
        ) from None
    except RegistrationError:
        raise
    except TimeoutError:
        raise RegistrationError(
            "Discord timed out. Check connectivity before retrying --register."
        ) from None
    except Exception:
        raise RegistrationError(
            "Could not register the command. Check connectivity and try again."
        ) from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--preview",
        action="store_true",
        help="Show safe request details without network access (default).",
    )
    action.add_argument(
        "--register", action="store_true", help="Create or update only /peopleflow link in Discord."
    )
    args = parser.parse_args(argv)
    try:
        # Uses the same .env/.env.integrations loader as the application, without starting it.
        from core import settings

        application_id = settings.DISCORD_APPLICATION_ID
        if args.register:
            register_command(application_id, settings.DISCORD_BOT_TOKEN)
            print(
                "Registered /peopleflow link code:<code>. Other Discord commands were not changed."
            )
            return 0
        path = (
            registration_path(application_id)
            if application_id
            else "/api/v10/applications/<DISCORD_APPLICATION_ID>/commands"
        )
        print("Preview only. No request was sent to Discord.")
        print("POST https://discord.com" + path)
        print(json.dumps(command_payload(), indent=2))
        print("After configuring .env.integrations, run with --register to apply this command.")
        return 0
    except RegistrationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print(
            "Command setup failed. Check .env.integrations and the project dependencies.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
