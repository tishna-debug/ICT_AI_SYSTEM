"""
Tests for alerts/telegram_bot.py. Never hits the real Telegram API - the
transport is always injected, matching how tests/test_mt5_bridge.py
avoids a live MT5 connection.
"""

import alerts.telegram_bot as telegram_bot
from alerts.telegram_bot import TelegramNotifier
from engine.rules.structure_state import replay


def test_not_configured_without_credentials(monkeypatch):
    # TelegramNotifier.__init__ calls load_dotenv(), which re-reads any
    # real .env file on disk regardless of delenv below - stub it out so
    # this test is deterministic even in a folder with a real .env
    # (otherwise it only "passes" by accident when no .env exists yet).
    monkeypatch.setattr(telegram_bot, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    notifier = TelegramNotifier(token=None, chat_id=None, transport=lambda url, payload: {"ok": True})

    assert notifier.is_configured() is False
    assert notifier.send("hello") is False


def test_send_success_calls_transport_with_expected_payload():
    calls = []

    def fake_transport(url, payload):
        calls.append((url, payload))
        return {"ok": True}

    notifier = TelegramNotifier(token="TOKEN123", chat_id="999", transport=fake_transport)

    assert notifier.is_configured() is True
    assert notifier.send("hello world") is True
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://api.telegram.org/botTOKEN123/sendMessage"
    assert payload == {"chat_id": "999", "text": "hello world"}


def test_send_handles_api_rejection():
    notifier = TelegramNotifier(token="T", chat_id="C", transport=lambda u, p: {"ok": False, "description": "bad chat id"})
    assert notifier.send("hi") is False


def test_send_handles_transport_exception_without_raising():
    def boom(url, payload):
        raise RuntimeError("network down")

    notifier = TelegramNotifier(token="T", chat_id="C", transport=boom)
    assert notifier.send("hi") is False


def test_notify_event_sends_plain_english_description(mk_candle):
    candles = []
    for i in range(5):
        candles.append(mk_candle(i, 50 + i, 51 + i, 49 + i, 50.5 + i))
    candles.append(mk_candle(5, 90, 100, 89, 95))
    for i in range(6, 11):
        candles.append(mk_candle(i, 60 - (i - 6), 61 - (i - 6), 59 - (i - 6), 60.3 - (i - 6)))
    _, results = replay(candles, symbol="TEST", timeframe="M5", tick_size=0.01, atr_avg50=1.0)
    swing_events = [e for r in results for e in r.events]
    assert swing_events, "expected at least one event from this sample sequence"

    sent = []
    notifier = TelegramNotifier(token="T", chat_id="C", transport=lambda u, p: sent.append(p) or {"ok": True})

    for event in swing_events:
        notifier.notify_event(event)

    assert len(sent) == len(swing_events)
    assert all("text" in payload and len(payload["text"]) > 0 for payload in sent)
