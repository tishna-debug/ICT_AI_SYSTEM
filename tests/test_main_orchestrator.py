"""
Tests for main.py's TradingOrchestrator. Never touches MT5, Telegram, or
Anthropic - the entry-timeframe engine is built for real via
engine.rules.structure_state.replay() (pure Python, no I/O), HTF
timeframes are stubbed with a minimal fake exposing just `.trend_state`,
and Telegram/AI use injected fakes (same pattern as their own test files).
"""

import json
from datetime import datetime

import pytest

import main as main_module
from alerts.telegram_bot import TelegramNotifier
from engine.ai_evaluator import AIEvaluator
from engine.context_layer import ContextLayerProvider
from engine.mt5_bridge import MT5CandleFeed
from engine.rules.base import Candle, KillZoneEvent
from engine.rules.bias_cascade import BiasCascadeEvent
from engine.rules.bos import BOSEvent, TrendState
from engine.rules.fvg import FVGCreatedEvent
from engine.rules.structure_state import replay


@pytest.fixture(autouse=True)
def _no_real_status_file(tmp_path, monkeypatch):
    # write_status()/log_setup() default to the real data/status.json and
    # data/setups.json - every on_candle() call triggers both, so this
    # must be redirected for every test in this file, not just the ones
    # that check their content.
    monkeypatch.setattr(main_module, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(main_module, "SETUPS_PATH", tmp_path / "setups.json")


@pytest.fixture(autouse=True)
def _no_real_env_credentials(monkeypatch):
    # ContextLayerProvider/TelegramNotifier/AIEvaluator all call
    # load_dotenv() on construction, which re-reads any real .env file
    # regardless of api_key=None being passed explicitly (see
    # tests/test_telegram_bot.py for the same issue). Stub every module's
    # load_dotenv so these tests behave identically with or without the
    # owner's real .env present.
    import engine.ai_evaluator as ai_evaluator
    import engine.context_layer as context_layer
    import alerts.telegram_bot as telegram_bot

    for module in (ai_evaluator, context_layer, telegram_bot):
        monkeypatch.setattr(module, "load_dotenv", lambda *a, **k: None)
    for var in ("ANTHROPIC_API_KEY", "FMP_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)


class _FakeHTFEngine:
    def __init__(self, trend):
        self.trend_state = TrendState(symbol="TEST", timeframe="X", current_trend=trend)


def _sample_candles(mk_candle):
    """Same story as tests/test_structure_state.py, stopping just before
    the breakout candle so tests can feed it manually via on_candle().
    """
    candles = []
    for i in range(5):
        candles.append(mk_candle(i, 50 + i, 51 + i, 49 + i, 50.5 + i))
    candles.append(mk_candle(5, 90, 100, 89, 95))
    for i in range(6, 11):
        candles.append(mk_candle(i, 60 - (i - 6), 61 - (i - 6), 59 - (i - 6), 60.3 - (i - 6)))
    for i in range(11, 14):
        candles.append(mk_candle(i, 55, 56, 54, 55.5))
    candles.append(mk_candle(14, 55, 56, 54.5, 55.5))
    candles.append(mk_candle(15, 55.6, 62, 55.5, 61.8))
    candles.append(mk_candle(16, 62.5, 64, 62.2, 63.5))
    for i in range(17, 25):
        candles.append(mk_candle(i, 64 + (i - 17) * 4, 68 + (i - 17) * 4, 63 + (i - 17) * 4, 67 + (i - 17) * 4))
    return candles


def _breakout_candle(timestamp=None):
    return Candle(
        timestamp=timestamp or datetime(2026, 1, 1, 2, 5),
        open=98,
        high=106,
        low=97.5,
        close=105,
        volume=10,
        timeframe="M5",
        symbol="TEST",
    )


def _orchestrator(mk_candle, telegram, ai, htf_trend="BULLISH"):
    candles = _sample_candles(mk_candle)
    entry_engine, _ = replay(candles, symbol="TEST", timeframe="M5", tick_size=0.01, atr_avg50=1.0)

    # api_key=None + a transport that would raise if ever called: this
    # must never touch a real .env's FMP_API_KEY, even after the owner
    # sets one up for real (same test-isolation lesson as
    # tests/test_telegram_bot.py's load_dotenv() issue).
    context = ContextLayerProvider(api_key=None, transport=lambda url: (_ for _ in ()).throw(AssertionError("should not call FMP in tests")))

    orch = main_module.TradingOrchestrator(
        symbol="TEST", entry_timeframe="M5", tick_size=0.01, telegram=telegram, ai=ai, context=context
    )
    orch.engines["M5"] = entry_engine
    for tf in main_module.HTF_TIMEFRAMES:
        orch.engines[tf] = _FakeHTFEngine(htf_trend)
    return orch


def _feed(tf):
    return MT5CandleFeed("TEST", tf, fetch_fn=lambda s, t: None)


def test_log_setup_appends_records(tmp_path, monkeypatch):
    path = tmp_path / "setups.json"
    monkeypatch.setattr(main_module, "SETUPS_PATH", path)

    candle = _breakout_candle()
    from engine.rules.bos import BreakOfStructure

    bos = BreakOfStructure(
        bos_id="x",
        direction="bullish",
        timeframe="M5",
        symbol="TEST",
        broken_swing=None,
        break_price=100.0,
        breaking_candle=candle,
        displacement_score=0.8,
        created_at=candle.timestamp,
        is_internal=False,
    )
    event = BOSEvent(bos=bos)

    main_module.log_setup(event, "TEST", "M5")
    main_module.log_setup(event, "TEST", "M5")

    records = json.loads(path.read_text())
    assert len(records) == 2
    assert records[0]["symbol"] == "TEST"
    assert records[0]["event_type"] == "BOS_CONFIRMED"
    assert "Break of Structure" in records[0]["description"]


def test_log_setup_caps_at_max_logged(tmp_path, monkeypatch):
    path = tmp_path / "setups.json"
    monkeypatch.setattr(main_module, "SETUPS_PATH", path)
    monkeypatch.setattr(main_module, "MAX_LOGGED_SETUPS", 3)

    candle = _breakout_candle()
    from engine.rules.bos import BreakOfStructure

    for i in range(5):
        bos = BreakOfStructure(
            bos_id=str(i),
            direction="bullish",
            timeframe="M5",
            symbol="TEST",
            broken_swing=None,
            break_price=100.0,
            breaking_candle=candle,
            displacement_score=0.8,
            created_at=candle.timestamp,
            is_internal=False,
        )
        main_module.log_setup(BOSEvent(bos=bos), "TEST", "M5")

    records = json.loads(path.read_text())
    assert len(records) == 3


def test_write_status_writes_expected_json(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    monkeypatch.setattr(main_module, "STATUS_PATH", path)

    main_module.write_status("RUNNING", "test detail")

    data = json.loads(path.read_text())
    assert data["state"] == "RUNNING"
    assert data["detail"] == "test detail"
    assert "updated_at" in data
    assert data["symbol"] == main_module.SYMBOL


def test_build_structure_summary_mentions_trend_and_fvgs(mk_candle):
    candles = _sample_candles(mk_candle)
    engine, _ = replay(candles, symbol="TEST", timeframe="M5", tick_size=0.01, atr_avg50=1.0)
    summary = main_module.build_structure_summary(engine)
    assert "Trend:" in summary
    assert "active FVG" in summary


def test_build_bias_summary_reports_no_bias_and_outside_kill_zone():
    bias = BiasCascadeEvent(bias=None, confidence=None, timeframes_used=[])
    kz = KillZoneEvent(timestamp=None, in_kill_zone=False, in_hot_window=False, session="NONE")
    summary = main_module.build_bias_summary(bias, kz)
    assert "none" in summary.lower()
    assert "outside" in summary.lower()


def test_on_candle_alerts_telegram_for_bos_and_evaluates_setup(mk_candle, tmp_path, monkeypatch):
    # log_verdict() defaults to the real data/verdicts.json - redirect it
    # so this test can't ever pollute the owner's real verdict log.
    logged = []
    monkeypatch.setattr(main_module, "log_verdict", lambda v: logged.append(v))

    sent = []
    telegram = TelegramNotifier(token="T", chat_id="C", transport=lambda u, p: sent.append(p) or {"ok": True})
    ai_calls = []

    def fake_transport(prompt, key, model):
        ai_calls.append(prompt)
        return json.dumps({"verdict": "BUY", "confidence": "HIGH", "reasoning": "test reasoning"})

    ai = AIEvaluator(api_key="sk-test", transport=fake_transport)

    # in NY Kill Zone (14:00 UTC -> 09:00 EST in winter) + HTF all bullish -> eligible
    orch = _orchestrator(mk_candle, telegram, ai, htf_trend="BULLISH")
    orch.on_candle(_feed("M5"), _breakout_candle(timestamp=datetime(2026, 1, 2, 14, 0)))

    bos_alerts = [p for p in sent if "text" in p and "Break of Structure" in p["text"]]
    verdict_alerts = [p for p in sent if "text" in p and "AI VERDICT" in p["text"]]
    assert len(bos_alerts) == 1
    assert len(verdict_alerts) == 1
    assert "BUY" in verdict_alerts[0]["text"]
    assert len(ai_calls) == 1
    assert len(logged) == 1
    assert logged[0].verdict == "BUY"


def test_on_candle_skips_ai_when_outside_kill_zone(mk_candle):
    sent = []
    telegram = TelegramNotifier(token="T", chat_id="C", transport=lambda u, p: sent.append(p) or {"ok": True})
    ai_calls = []
    ai = AIEvaluator(api_key="sk-test", transport=lambda p, k, m: ai_calls.append(p) or "{}")

    orch = _orchestrator(mk_candle, telegram, ai, htf_trend="BULLISH")
    # default timestamp (02:05 UTC on Jan 1 -> 21:05 EST previous day) falls outside both Kill Zones
    orch.on_candle(_feed("M5"), _breakout_candle())

    assert len(ai_calls) == 0
    verdict_alerts = [p for p in sent if "text" in p and "AI VERDICT" in p["text"]]
    assert len(verdict_alerts) == 0
    # the raw BOS signal should still have gone out
    bos_alerts = [p for p in sent if "text" in p and "Break of Structure" in p["text"]]
    assert len(bos_alerts) == 1


def test_on_candle_skips_ai_when_htf_bias_disagrees(mk_candle):
    sent = []
    telegram = TelegramNotifier(token="T", chat_id="C", transport=lambda u, p: sent.append(p) or {"ok": True})
    ai_calls = []
    ai = AIEvaluator(api_key="sk-test", transport=lambda p, k, m: ai_calls.append(p) or "{}")

    orch = _orchestrator(mk_candle, telegram, ai, htf_trend="BEARISH")  # disagrees with the bullish BOS
    orch.on_candle(_feed("M5"), _breakout_candle(timestamp=datetime(2026, 1, 2, 14, 0)))

    assert len(ai_calls) == 0
    verdict_alerts = [p for p in sent if "text" in p and "AI VERDICT" in p["text"]]
    assert len(verdict_alerts) == 0


def test_on_candle_handles_rejected_candle_without_crashing(mk_candle):
    telegram = TelegramNotifier(token="T", chat_id="C", transport=lambda u, p: {"ok": True})
    ai = AIEvaluator(api_key="sk-test", transport=lambda p, k, m: "{}")

    orch = _orchestrator(mk_candle, telegram, ai)
    bad_candle = Candle(timestamp=datetime(2026, 1, 1, 2, 5), open=10, high=5, low=20, close=12, volume=1, timeframe="M5", symbol="TEST")

    orch.on_candle(_feed("M5"), bad_candle)  # should not raise
