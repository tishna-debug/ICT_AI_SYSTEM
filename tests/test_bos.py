from engine.rules.bos import TrendState, build_bos_event, detect_bos, update_trend_state_on_bos
from engine.rules.swings import SwingPointEvent

ATR14 = 1.0


def _swing(mk_candle, swing_type, price_level, degree):
    pivot = mk_candle(0, 99, 100, 98, 99.5)
    return SwingPointEvent(candle=pivot, swing_type=swing_type, price_level=price_level, strength=5 if degree == "MAJOR" else 2, degree=degree, confirmed_at=pivot.timestamp)


def test_bullish_bos_on_major_swing(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    breaker = mk_candle(10, 99.8, 101.5, 99.7, 101.3)
    bos = detect_bos(sh, breaker, ATR14, timeframe="M5", symbol="TEST")
    assert bos is not None
    assert bos.direction == "bullish"
    assert bos.is_internal is False


def test_wick_only_break_is_not_a_bos_by_default(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    wick_only = mk_candle(11, 99.5, 101.2, 99.3, 99.8)
    assert detect_bos(sh, wick_only, ATR14, timeframe="M5", symbol="TEST") is None


def test_already_broken_swing_returns_none(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    breaker = mk_candle(10, 99.8, 101.5, 99.7, 101.3)
    assert detect_bos(sh, breaker, ATR14, timeframe="M5", symbol="TEST", already_broken=True) is None


def test_insufficient_displacement_returns_none(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    weak = mk_candle(12, 99.9, 100.2, 99.8, 100.1)
    assert detect_bos(sh, weak, ATR14, timeframe="M5", symbol="TEST") is None


def test_bearish_bos_on_minor_swing(mk_candle):
    sl = _swing(mk_candle, "LOW", 90, "MINOR")
    breaker = mk_candle(20, 90.5, 90.6, 88, 88.2)
    bos = detect_bos(sl, breaker, ATR14, timeframe="M5", symbol="TEST")
    assert bos.direction == "bearish"
    assert bos.is_internal is True


def test_requires_close_false_allows_wick_break(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    wick_strong = mk_candle(13, 98.0, 102.0, 97.8, 99.9)
    assert detect_bos(sh, wick_strong, ATR14, timeframe="M5", symbol="TEST") is None
    bos = detect_bos(sh, wick_strong, ATR14, timeframe="M5", symbol="TEST", requires_close=False)
    assert bos is not None and bos.direction == "bullish"


def test_trend_state_updates_on_bos(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    sl = _swing(mk_candle, "LOW", 90, "MINOR")
    breaker = mk_candle(10, 99.8, 101.5, 99.7, 101.3)
    bos = detect_bos(sh, breaker, ATR14, timeframe="M5", symbol="TEST")
    ev = build_bos_event(bos)
    assert ev.event_type == "BOS_CONFIRMED"

    ts = TrendState(symbol="TEST", timeframe="M5")
    assert ts.current_trend == "UNDEFINED"
    update_trend_state_on_bos(ts, ev)
    assert ts.current_trend == "BULLISH"
    assert ts.higher_highs == 1

    breaker_bear = mk_candle(20, 90.5, 90.6, 88, 88.2)
    bos_bear = detect_bos(sl, breaker_bear, ATR14, timeframe="M5", symbol="TEST")
    update_trend_state_on_bos(ts, build_bos_event(bos_bear))
    assert ts.current_trend == "BEARISH"
    assert ts.lower_lows == 1
