"""
alerts/telegram_bot.py

Build Step 2: sends the rule engine's detected signals to the owner's
phone via Telegram. One-way only - this never reads or reacts to incoming
messages, it only sends alerts.

Engineering decision: this talks to Telegram's plain HTTP API directly
with the standard library (urllib), instead of the `python-telegram-bot`
package originally listed in requirements.txt. That library is built for
bots that also receive and respond to messages (it runs its own asyncio
event loop) - unnecessary complexity for a one-directional alert sender
bolted onto an otherwise fully synchronous engine. Removed from
requirements.txt; nothing here needs it.

Credentials: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID live in .env (see
.env.example and README.md for how to get them from @BotFather). Never
hardcoded, never committed.

Per CLAUDE.md's "graceful degradation" rule: a Telegram outage, a bad
token, or missing credentials must never crash the rest of the system.
Every failure here is caught, logged, and reported back as `False` -
nothing raises out of send().
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable, Optional

from dotenv import load_dotenv

from engine.event_narration import describe_event
from engine.logging_config import get_logger

logger = get_logger("telegram_bot")

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT_SECONDS = 10


def _default_transport(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


class TelegramNotifier:
    """Sends plain-text alerts to one Telegram chat.

    `transport` defaults to the real HTTP call but can be swapped out in
    tests, so send() is fully verifiable without hitting Telegram's real
    API (same pattern as MT5CandleFeed's injectable fetch_fn).
    """

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        transport: Optional[Callable[[str, dict], dict]] = None,
    ):
        load_dotenv()
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self._transport = transport or _default_transport

    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.is_configured():
            logger.error(
                "Cannot send Telegram alert - TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID "
                "are missing from .env. See .env.example."
            )
            return False

        url = TELEGRAM_API_URL.format(token=self.token)
        payload = {"chat_id": self.chat_id, "text": text}

        try:
            response = self._transport(url, payload)
        except Exception:
            logger.exception("Failed to send Telegram alert (network or API error).")
            return False

        if not response.get("ok"):
            logger.error(f"Telegram API rejected the message: {response}")
            return False

        return True

    def notify_event(self, event: object) -> bool:
        """Convenience handler for wiring straight into an EventBus:
            bus.subscribe_all(notifier.notify_event)
        """
        return self.send(describe_event(event))
