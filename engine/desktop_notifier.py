"""
engine/desktop_notifier.py

Native Windows desktop toast notification for AI verdicts - a second,
more reliable alert channel alongside Telegram (especially useful right
now, since Telegram is network-blocked on the owner's connection). Fires
the instant an eligible setup gets a verdict.

Uses win11toast's `notify()` (wraps the native WinRT
ToastNotificationManager API) - confirmed non-blocking (~30ms, doesn't
wait for the toast to be dismissed), which matters because main.py's live
polling loop must never be delayed by a UI popup. Windows only, same
platform scope as engine/mt5_bridge.py.

Per CLAUDE.md's graceful degradation rule: any failure here (not on
Windows, package missing, WinRT error) is caught, logged, and never
crashes the rest of the system - the toast import is lazy specifically so
this module stays importable even on a non-Windows machine, matching
engine/ai_evaluator.py's lazy `import anthropic`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from engine.logging_config import get_logger

if TYPE_CHECKING:
    from engine.ai_evaluator import Verdict

logger = get_logger("desktop_notifier")

APP_ID = "ICT AI Trading System"
MAX_BODY_LENGTH = 200  # toast bodies get visually cut off if too long - full reasoning is in Telegram/dashboard/verdicts.json


def _default_transport(title: str, body: str) -> None:
    from win11toast import notify

    notify(title, body, app_id=APP_ID)


class DesktopNotifier:
    """Fires a native Windows toast notification. Never raises.

    `transport` defaults to the real win11toast call but can be swapped
    out in tests, same pattern as every other integration module in this
    project (MT5CandleFeed, TelegramNotifier, AIEvaluator,
    ContextLayerProvider).
    """

    def __init__(self, transport: Optional[Callable[[str, str], None]] = None, enabled: bool = True):
        self.enabled = enabled
        self._transport = transport or _default_transport

    def notify(self, title: str, body: str) -> bool:
        if not self.enabled:
            return False
        try:
            self._transport(title, body)
            return True
        except Exception:
            logger.exception("Failed to show desktop notification (non-fatal, continuing).")
            return False

    def notify_verdict(self, verdict: "Verdict") -> bool:
        """Convenience wrapper for an AI verdict."""
        title = f"{verdict.verdict} - {verdict.symbol} {verdict.timeframe} ({verdict.confidence})"
        body = verdict.reasoning if len(verdict.reasoning) <= MAX_BODY_LENGTH else verdict.reasoning[: MAX_BODY_LENGTH - 3] + "..."
        return self.notify(title, body)
