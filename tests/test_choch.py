from engine.rules.bos import BOSEvent, TrendState
from engine.rules.choch import CHOCHEvent, classify_choch_confidence, classify_structure_break, detect_structure_break
from engine.rules.swings import SwingPointEvent

ATR14 = 1.0


def _swing(mk_candle, swing_type, price_level, degree):
    pivot = mk_candle(0, 99, 100, 98, 99.5)
    return SwingPointEvent(candle=pivot, swing_type=swing_type, price_level=price_level, strength=5 if degree == "MAJOR" else 2, degree=degree, confirmed_at=pivot.timestamp)


def test_classify_structure_break():
    assert classify_structure_break("bullish", "UNDEFINED") == "BOS"
    assert classify_structure_break("bearish", "UNDEFINED") == "BOS"
    assert classify_structure_break("bullish", "BULLISH") == "BOS"
    assert classify_structure_break("bearish", "BEARISH") == "BOS"
    assert classify_structure_break("bullish", "BEARISH") == "CHOCH"
    assert classify_structure_break("bearish", "BULLISH") == "CHOCH"


def test_classify_choch_confidence():
    assert classify_choch_confidence(True, 0.9, True, True) == "HIGH"
    assert classify_choch_confidence(True, 0.9, False, None) == "MEDIUM"
    assert classify_choch_confidence(False, 0.3, False, None) == "LOW"


def test_full_pipeline_first_break_establishes_bos(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    ts = TrendState(symbol="TEST", timeframe="M5")
    breaker = mk_candle(10, 99.8, 101.5, 99.7, 101.3)
    result = detect_structure_break(sh, breaker, ts, ATR14, timeframe="M5", symbol="TEST")
    assert isinstance(result, BOSEvent)
    assert ts.current_trend == "BULLISH"
    assert ts.higher_highs == 1


def test_opposite_break_after_established_trend_is_choch(mk_candle):
    sh = _swing(mk_candle, "HIGH", 102, "MAJOR")
    sl = _swing(mk_candle, "LOW", 90, "MINOR")
    ts = TrendState(symbol="TEST", timeframe="M5")

    breaker = mk_candle(10, 99.8, 103.5, 99.7, 103.3)
    detect_structure_break(sh, breaker, ts, ATR14, timeframe="M5", symbol="TEST")
    assert ts.current_trend == "BULLISH"

    breaker3 = mk_candle(30, 90.5, 90.6, 87, 87.2)
    result = detect_structure_break(sl, breaker3, ts, ATR14, timeframe="M5", symbol="TEST", preceded_by_sweep=True, aligned_with_htf_bias=True)
    assert isinstance(result, CHOCHEvent)
    assert result.prior_trend == "BULLISH"
    assert result.new_bias == "BEARISH"
    assert ts.current_trend == "BEARISH"
    assert ts.higher_highs == 0 and ts.lower_lows == 0


def test_no_break_returns_none(mk_candle):
    sh = _swing(mk_candle, "HIGH", 102, "MAJOR")
    ts = TrendState(symbol="TEST", timeframe="M5")
    no_break = mk_candle(40, 100, 100.1, 99.9, 100.05)
    assert detect_structure_break(sh, no_break, ts, ATR14, timeframe="M5", symbol="TEST") is None
