"""
Tests for the pieces of engine/mt5_bridge.py that don't require a live
MT5 terminal connection: row-to-Candle conversion, timeframe validation,
and the MT5CandleFeed polling/de-duplication logic (via an injected fake
fetch function, so no real MT5 call happens).

connect()/fetch_recent_candles() against a REAL terminal are intentionally
not covered here - that depends on external live state (is MT5 open right
now?) which isn't something an automated test suite should assume. Use
scripts/test_mt5.py to check that by hand.
"""

from datetime import datetime, timedelta, timezone

import pytest

from engine.mt5_bridge import MT5CandleFeed, _row_to_candle, fetch_recent_candles, run_feed


def test_row_to_candle_converts_fields():
    row = {"time": 1735689600, "open": 100.1, "high": 101.5, "low": 99.8, "close": 100.9, "tick_volume": 42}
    candle = _row_to_candle(row, timeframe="M5", symbol="US100")

    assert candle.timestamp == datetime.fromtimestamp(1735689600, tz=timezone.utc)
    assert candle.open == 100.1
    assert candle.high == 101.5
    assert candle.low == 99.8
    assert candle.close == 100.9
    assert candle.volume == 42
    assert candle.timeframe == "M5"
    assert candle.symbol == "US100"
    # derived fields still compute correctly from a bridge-built Candle
    assert candle.direction == "bullish"


def test_fetch_recent_candles_rejects_unknown_timeframe():
    with pytest.raises(ValueError):
        fetch_recent_candles("ANY_SYMBOL", "BOGUS_TIMEFRAME", count=5)


def test_feed_returns_none_when_nothing_new():
    calls = {"n": 0}

    def fake_fetch(symbol, timeframe):
        calls["n"] += 1
        return None

    feed = MT5CandleFeed("US100", "M5", fetch_fn=fake_fetch)
    assert feed.poll() is None
    assert calls["n"] == 1


def test_feed_seeded_with_last_seen_timestamp_ignores_already_processed_candle(mk_candle):
    already_processed = mk_candle(0, 100, 101, 99, 100.5)

    feed = MT5CandleFeed(
        "US100", "M5", fetch_fn=lambda s, t: already_processed, last_seen_timestamp=already_processed.timestamp
    )

    assert feed.poll() is None  # would be a duplicate of what backfill already saw


def test_feed_returns_candle_once_then_dedupes(mk_candle):
    same_candle = mk_candle(0, 100, 101, 99, 100.5)

    feed = MT5CandleFeed("US100", "M5", fetch_fn=lambda s, t: same_candle)

    first = feed.poll()
    assert first is same_candle

    second = feed.poll()
    assert second is None  # same timestamp as last time - not new


def test_feed_returns_each_newer_candle(mk_candle):
    sequence = [mk_candle(0, 100, 101, 99, 100.5), mk_candle(1, 101, 102, 100, 101.5), mk_candle(2, 102, 103, 101, 102.5)]
    calls = {"i": 0}

    def fake_fetch(symbol, timeframe):
        candle = sequence[calls["i"]]
        calls["i"] = min(calls["i"] + 1, len(sequence) - 1)
        return candle

    feed = MT5CandleFeed("US100", "M5", fetch_fn=fake_fetch)
    seen = [feed.poll() for _ in range(4)]

    assert seen[0] is sequence[0]
    assert seen[1] is sequence[1]
    assert seen[2] is sequence[2]
    assert seen[3] is None  # calls["i"] stayed at the last candle -> no new one


def test_run_feed_calls_on_candle_for_each_new_candle(mk_candle):
    sequence = [mk_candle(0, 100, 101, 99, 100.5), mk_candle(1, 101, 102, 100, 101.5)]
    calls = {"i": 0}

    def fake_fetch(symbol, timeframe):
        if calls["i"] >= len(sequence):
            return None
        candle = sequence[calls["i"]]
        calls["i"] += 1
        return candle

    feed = MT5CandleFeed("US100", "M5", fetch_fn=fake_fetch)
    received = []
    run_feed([feed], on_candle=lambda f, c: received.append(c), poll_interval_seconds=0, iterations=4)

    assert received == sequence


def test_run_feed_tolerates_a_poll_error_and_keeps_going(mk_candle):
    good_candle = mk_candle(0, 100, 101, 99, 100.5)
    call_count = {"n": 0}

    def flaky_fetch(symbol, timeframe):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated MT5 hiccup")
        return good_candle if call_count["n"] == 2 else None

    feed = MT5CandleFeed("US100", "M5", fetch_fn=flaky_fetch)
    received = []
    # Should not raise, despite the first poll blowing up.
    run_feed([feed], on_candle=lambda f, c: received.append(c), poll_interval_seconds=0, iterations=3)

    assert received == [good_candle]
    assert call_count["n"] == 3
