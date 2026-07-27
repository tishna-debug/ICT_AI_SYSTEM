"""
scripts/test_ai_evaluator.py

Diagnostic script - sends one made-up sample setup to Claude and prints
the verdict, to confirm your Anthropic API key works end to end.

Before running this, add to your .env file (see .env.example):
    ANTHROPIC_API_KEY=sk-ant-...

Then run:
    python scripts/test_ai_evaluator.py

This costs a small amount on your Anthropic account (one short API call)
- that's expected, this is what confirms the key and billing are set up
correctly.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.ai_evaluator import AIEvaluator
from engine.rules.base import Candle
from engine.rules.bos import BOSEvent, BreakOfStructure
from engine.rules.swings import SwingPointEvent


def _sample_bos_event() -> BOSEvent:
    ts = datetime(2026, 1, 1, 14, 45)
    pivot = Candle(timestamp=ts - timedelta(minutes=25), open=99, high=100, low=98, close=99.5, volume=10, timeframe="M5", symbol="USTEC")
    swing = SwingPointEvent(candle=pivot, swing_type="HIGH", price_level=100.0, strength=5, degree="MAJOR", confirmed_at=ts)
    breaker = Candle(timestamp=ts, open=99.8, high=101.5, low=99.7, close=101.3, volume=15, timeframe="M5", symbol="USTEC")
    bos = BreakOfStructure(
        bos_id="sample-bos",
        direction="bullish",
        timeframe="M5",
        symbol="USTEC",
        broken_swing=swing,
        break_price=100.0,
        breaking_candle=breaker,
        displacement_score=0.86,
        created_at=ts,
        is_internal=False,
        preceded_by_sweep=True,
    )
    return BOSEvent(bos=bos)


def main() -> int:
    print("=" * 70)
    print("AI evaluator test")
    print("=" * 70)

    evaluator = AIEvaluator()
    if not evaluator.is_configured():
        print("\nANTHROPIC_API_KEY is missing from your .env file.")
        print("Get one at https://console.anthropic.com, add it to .env, and try again.")
        return 1

    print("\nSending a sample setup to Claude for a verdict...")
    verdict = evaluator.evaluate(
        _sample_bos_event(),
        symbol="USTEC",
        timeframe="M5",
        structure_summary="Trend: BULLISH. Last swing high: 100.00 (MAJOR). 1 active bullish FVG (56.00-62.20, STRONG confidence).",
        bias_summary="HTF bias: BULLISH (FULL confidence, D/H4/H1/M15 aligned). In NY Kill Zone hot window.",
    )

    print(f"\nVerdict:    {verdict.verdict}")
    print(f"Confidence: {verdict.confidence}")
    print(f"Reasoning:  {verdict.reasoning}")

    if verdict.verdict == "NO_TRADE" and "defaulting to NO_TRADE" in verdict.reasoning and "AI" in verdict.reasoning:
        print("\nThat looks like a fallback response, not a real Claude answer - check logs/ai_evaluator.log for details.")
        return 1

    print("\nWorking! Check logs/ai_evaluator.log for details if anything looks off.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
