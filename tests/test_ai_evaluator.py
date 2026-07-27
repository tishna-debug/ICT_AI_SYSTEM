"""
Tests for engine/ai_evaluator.py. Never hits the real Anthropic API - the
transport is always injected, matching how tests/test_mt5_bridge.py and
tests/test_telegram_bot.py avoid live external calls.
"""

import json
import os

import engine.ai_evaluator as ai_evaluator
from engine.ai_evaluator import AIEvaluator, log_verdict
from engine.rules.bos import BOSEvent, BreakOfStructure
from engine.rules.swings import SwingPointEvent


def _sample_bos_event(mk_candle):
    pivot = mk_candle(0, 99, 100, 98, 99.5)
    swing = SwingPointEvent(candle=pivot, swing_type="HIGH", price_level=100.0, strength=5, degree="MAJOR", confirmed_at=pivot.timestamp)
    breaker = mk_candle(5, 99.8, 101.5, 99.7, 101.3)
    bos = BreakOfStructure(
        bos_id="sample-bos",
        direction="bullish",
        timeframe="M5",
        symbol="TEST",
        broken_swing=swing,
        break_price=100.0,
        breaking_candle=breaker,
        displacement_score=0.86,
        created_at=breaker.timestamp,
        is_internal=False,
    )
    return BOSEvent(bos=bos)


def test_not_configured_returns_no_trade_fallback(monkeypatch, mk_candle):
    # See tests/test_telegram_bot.py for why load_dotenv() needs stubbing
    # here too - it re-reads any real .env file regardless of delenv.
    monkeypatch.setattr(ai_evaluator, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    evaluator = AIEvaluator(api_key=None, transport=lambda p, k, m: "{}")

    assert evaluator.is_configured() is False
    verdict = evaluator.evaluate(_sample_bos_event(mk_candle), symbol="TEST", timeframe="M5")
    assert verdict.verdict == "NO_TRADE"
    assert "not configured" in verdict.reasoning.lower()


def test_successful_verdict_parses_response(mk_candle):
    def fake_transport(prompt, api_key, model):
        assert "Break of Structure" in prompt
        return json.dumps({"verdict": "buy", "confidence": "high", "reasoning": "Strong bullish BOS off a major swing."})

    evaluator = AIEvaluator(api_key="sk-test", transport=fake_transport)
    verdict = evaluator.evaluate(_sample_bos_event(mk_candle), symbol="TEST", timeframe="M5")

    assert verdict.verdict == "BUY"
    assert verdict.confidence == "HIGH"
    assert "bullish" in verdict.reasoning.lower()
    assert verdict.symbol == "TEST"
    assert verdict.timeframe == "M5"


def test_transport_exception_falls_back_to_no_trade(mk_candle):
    def boom(prompt, api_key, model):
        raise RuntimeError("network down")

    evaluator = AIEvaluator(api_key="sk-test", transport=boom)
    verdict = evaluator.evaluate(_sample_bos_event(mk_candle), symbol="TEST", timeframe="M5")

    assert verdict.verdict == "NO_TRADE"
    assert "AI call failed" in verdict.reasoning


def test_malformed_json_falls_back_to_no_trade(mk_candle):
    evaluator = AIEvaluator(api_key="sk-test", transport=lambda p, k, m: "not json at all")
    verdict = evaluator.evaluate(_sample_bos_event(mk_candle), symbol="TEST", timeframe="M5")

    assert verdict.verdict == "NO_TRADE"
    assert "expected format" in verdict.reasoning


def test_unrecognized_verdict_falls_back_to_no_trade(mk_candle):
    bad_response = json.dumps({"verdict": "MAYBE", "confidence": "HIGH", "reasoning": "unsure"})
    evaluator = AIEvaluator(api_key="sk-test", transport=lambda p, k, m: bad_response)
    verdict = evaluator.evaluate(_sample_bos_event(mk_candle), symbol="TEST", timeframe="M5")

    assert verdict.verdict == "NO_TRADE"
    assert "unrecognized verdict" in verdict.reasoning.lower()


def test_invalid_confidence_defaults_to_low(mk_candle):
    response = json.dumps({"verdict": "SELL", "confidence": "SUPER_SURE", "reasoning": "..."})
    evaluator = AIEvaluator(api_key="sk-test", transport=lambda p, k, m: response)
    verdict = evaluator.evaluate(_sample_bos_event(mk_candle), symbol="TEST", timeframe="M5")

    assert verdict.verdict == "SELL"
    assert verdict.confidence == "LOW"


def test_log_verdict_round_trips_through_json_file(mk_candle, tmp_path):
    evaluator = AIEvaluator(
        api_key="sk-test",
        transport=lambda p, k, m: json.dumps({"verdict": "BUY", "confidence": "MEDIUM", "reasoning": "test"}),
    )
    verdict = evaluator.evaluate(_sample_bos_event(mk_candle), symbol="TEST", timeframe="M5")

    path = os.path.join(tmp_path, "verdicts.json")
    log_verdict(verdict, path=path)
    log_verdict(verdict, path=path)  # second call should append, not overwrite

    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)

    assert len(records) == 2
    assert records[0]["verdict"] == "BUY"
    assert records[0]["symbol"] == "TEST"
