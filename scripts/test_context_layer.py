"""
scripts/test_context_layer.py

Diagnostic script - fetches real news/economic calendar data from
Financial Modeling Prep (FMP) and prints what the Context Layer would
feed into an AI verdict prompt, to confirm your FMP key works.

Before running this, add to your .env file (see .env.example):
    FMP_API_KEY=...
(sign up free at https://financialmodelingprep.com)

Then run:
    python scripts/test_context_layer.py

Volatility and the FOMO heuristic need real candle data to be meaningful,
so this script uses a small made-up price story for those two (same
pattern as scripts/demo_run.py) - only the news/sentiment portion hits a
real API.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.context_layer import (
    ContextLayerProvider,
    build_context_summary,
    classify_volatility,
    detect_fomo_risk,
    get_fear_greed_index,
)
from engine.rules.base import Candle


def _sample_candles() -> list[Candle]:
    base = datetime(2026, 1, 1)
    candles = []
    price = 100.0
    for i in range(20):
        o, h, l, c = price, price + 1, price - 1, price + 0.5
        candles.append(Candle(timestamp=base + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c, volume=100, timeframe="M5", symbol="DEMO"))
        price = c
    return candles


def main() -> int:
    print("=" * 70)
    print("Context layer test")
    print("=" * 70)

    provider = ContextLayerProvider()
    if not provider.is_configured():
        print("\nFMP_API_KEY is missing from your .env file.")
        print("Sign up free at https://financialmodelingprep.com, add the key to .env, and try again.")
        return 1

    print("\nFetching news + economic calendar from FMP...")
    news = provider.get_news_context()
    print(f"  Headlines fetched: {len(news.headlines)}")
    for h in news.headlines[:5]:
        print(f"    - {h}")
    print(f"  High-impact US events in the next hour: {len(news.upcoming_high_impact)}")
    for e in news.upcoming_high_impact:
        print(f"    - {e.event} at {e.date}")

    sentiment = provider.get_sentiment_context(news)
    print(f"\n  Sentiment: {sentiment.label} (score {sentiment.score}, from {sentiment.sample_size} headlines)")

    candles = _sample_candles()
    volatility = classify_volatility(atr14=1.0, atr_baseline=1.0)
    fomo = detect_fomo_risk(candles, atr14=1.0, sentiment=sentiment)
    fear_greed = get_fear_greed_index()

    summary = build_context_summary(volatility, news, sentiment, fear_greed, fomo)
    print("\nFull context summary (what the AI would see):")
    print(f"  {summary}")

    if not news.headlines:
        print("\nGot 0 headlines back - double-check your FMP_API_KEY and that your plan includes the stock_news endpoint.")
        return 1

    print("\nWorking!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
