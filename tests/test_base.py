import random
from datetime import datetime, timedelta

from engine.rules.base import (
    Candle,
    atr,
    atr_or_range_proxy,
    atr_series,
    build_candle_event,
    build_displacement_event,
    displacement_score,
    is_displaced,
    is_valid_candle,
    validate_candle,
)


def test_candle_derived_fields(mk_candle):
    c = mk_candle(0, 100, 105, 98, 103)
    assert c.body == 3
    assert c.range == 7
    assert c.upper_wick == 2
    assert c.lower_wick == 2
    assert c.direction == "bullish"
    assert c.mid_price == 101.5
    assert round(c.body_ratio, 4) == round(3 / 7, 4)


def test_flat_candle_is_doji_with_zero_body_ratio(mk_candle):
    c = mk_candle(0, 100, 100, 100, 100)
    assert c.direction == "doji"
    assert c.body_ratio == 0.0


def test_validate_candle_catches_each_rule(mk_candle):
    bad_high = mk_candle(0, 100, 95, 98, 103)
    failures = validate_candle(bad_high)
    assert any("RULE 1" in f for f in failures)
    assert any("RULE 3" in f for f in failures)

    negative_price = mk_candle(0, -1, 5, 1, 2)
    assert any("RULE 4" in f for f in validate_candle(negative_price))

    good = mk_candle(0, 100, 105, 98, 103)
    assert is_valid_candle(good)


def test_validate_candle_duplicate_timestamp(mk_candle):
    c = mk_candle(0, 100, 105, 98, 103)
    seen = {c.timestamp}
    assert any("RULE 6" in f for f in validate_candle(c, seen))


def test_build_candle_event(mk_candle):
    ev = build_candle_event(mk_candle(0, 100, 105, 98, 103))
    assert ev.is_valid is True
    assert ev.event_type == "CANDLE_CLOSED"


def test_atr_needs_period_plus_one_candles(mk_candle):
    random.seed(1)
    candles = []
    price = 100.0
    for i in range(20):
        o = price
        h = o + random.uniform(0.5, 2)
        l = o - random.uniform(0.5, 2)
        cl = random.uniform(l, h)
        candles.append(mk_candle(i, o, h, l, cl))
        price = cl

    assert atr(candles[:10]) is None
    value = atr(candles)
    assert value is not None and value > 0

    series = atr_series(candles)
    assert series[13] is None
    assert series[14] is not None

    proxy = atr_or_range_proxy(candles[:5])
    assert proxy is not None


def test_displacement_detects_strong_candle(mk_candle):
    atr14 = 2.0
    strong = mk_candle(0, 100, 110, 99.5, 109.5)
    assert is_displaced(strong, atr14) is True
    assert displacement_score(strong, atr14) > 0.8

    weak = mk_candle(0, 100, 105, 95, 101)
    assert is_displaced(weak, atr14) is False

    doji = mk_candle(0, 100, 110, 90, 100)
    assert is_displaced(doji, atr14) is False

    flat = mk_candle(0, 100, 100, 100, 100)
    assert displacement_score(flat, atr14) == 0.0

    ev = build_displacement_event(strong, atr14)
    assert ev.event_type == "DISPLACEMENT_DETECTED"
    assert ev.is_displaced is True
