"""Public notification vocabulary; no credentials or provider SDKs."""

PROVIDERS = ("slack", "discord")


class IntegrationError(RuntimeError):
    """Safe, user-facing error text only."""


class DiscordCommandError(IntegrationError):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class IntegrationConflict(IntegrationError):
    pass


class IntegrationRateLimited(IntegrationError):
    pass


class IntegrationUnavailable(IntegrationError):
    pass


ERROR_MESSAGES = {
    "proxy_configuration": "The proxy configuration is invalid. Check the system HTTP CONNECT proxy or HTTPS_PROXY setting, then restart.",
    "timeout": "The provider timed out.",
    "network": "The provider could not be reached.",
    "rate_limited": "The provider requested a pause before retrying.",
    "provider_unavailable": "The provider is temporarily unavailable.",
    "webhook_rejected": "The provider rejected the webhook. Check its configuration and channel permissions.",
    "unexpected_response": "The provider did not confirm delivery.",
    "configuration": "Bot configuration is missing or invalid. Update the server environment and restart.",
    "delivery_unconfirmed": "Delivery could not be confirmed before the retry limit.",
    "internal": "Notification delivery encountered an internal error.",
    "recipient_unlinked": "The recipient has not connected a personal account. Connect it in Personal notifications; future events will be delivered there.",
    "recipient_unavailable": "The personal recipient is unavailable or their permissions changed. Check the account connection and current request assignee.",
    "direct_messages_disabled": "The service could not open a personal conversation. Allow direct messages from this bot and try again.",
    "bot_rejected": "The service rejected the bot request. Check the bot token, installation and permissions on the server.",
}
