"""
scripts/test_telegram.py

Diagnostic script - sends one test message to confirm your Telegram bot
setup works end to end.

Before running this, add to your .env file (see .env.example):
    TELEGRAM_BOT_TOKEN=...   (from @BotFather)
    TELEGRAM_CHAT_ID=...     (from the getUpdates URL - see README.md)

Then run:
    python scripts/test_telegram.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alerts.telegram_bot import TelegramNotifier


def main() -> int:
    print("=" * 70)
    print("Telegram alert test")
    print("=" * 70)

    notifier = TelegramNotifier()
    if not notifier.is_configured():
        print("\nTELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID are missing from your .env file.")
        print("See README.md for how to get these from @BotFather, add them to .env, and try again.")
        return 1

    print("\nSending a test message...")
    ok = notifier.send("Test message from your ICT AI Trading System. If you can read this, alerts are working!")

    if ok:
        print("Sent! Check Telegram.")
        return 0

    print("Failed to send - check logs/telegram_bot.log for details, and double-check your token/chat ID.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
