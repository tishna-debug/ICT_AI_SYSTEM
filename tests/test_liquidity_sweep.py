from engine.rules.bos import detect_bos
from engine.rules.liquidity_sweep import _classify_sweep, detect_sweep
from engine.rules.swings import SwingPointEvent


def _swing(mk_candle, swing_type, price_level, degree):
    pivot = mk_candle(0, 99, 100, 98, 99.5)
    return SwingPointEvent(candle=pivot, swing_type=swing_type, price_level=price_level, strength=5 if degree == "MAJOR" else 2, degree=degree, confirmed_at=pivot.timestamp)


def test_clean_sweep_high(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    clean = mk_candle(10, 99.8, 102, 99.7, 99.9)
    ev = detect_sweep(sh, clean, fvg_created=True)
    assert ev is not None
    assert ev.sweep_class == "CLEAN"
    assert ev.fvg_created is True
    # structural property of the literal Section 7.2 formula given condition 2
    assert ev.recovery_ratio >= 1.0


def test_wick_ratio_too_small_is_not_a_sweep(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    small_wick = mk_candle(12, 99, 100.3, 95, 99.5)
    assert detect_sweep(sh, small_wick) is None


def test_close_beyond_level_is_bos_not_sweep(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    becomes_bos = mk_candle(14, 99.8, 102, 99.7, 101.5)
    assert detect_sweep(sh, becomes_bos) is None
    bos = detect_bos(sh, becomes_bos, atr14=1.0, timeframe="M5", symbol="TEST")
    assert bos is not None and bos.direction == "bullish"


def test_sweep_low(mk_candle):
    sl = _swing(mk_candle, "LOW", 90, "MINOR")
    clean_low = mk_candle(20, 90.2, 90.3, 88, 90.1)
    ev = detect_sweep(sl, clean_low)
    assert ev is not None
    assert ev.sweep_type == "LOW"
    assert ev.sweep_class == "CLEAN"


def test_flat_candle_guard(mk_candle):
    sh = _swing(mk_candle, "HIGH", 100, "MAJOR")
    flat = mk_candle(30, 100, 100, 100, 100)
    assert detect_sweep(sh, flat) is None


def test_classify_sweep_boundary():
    assert _classify_sweep(0.95) == "CLEAN"
    assert _classify_sweep(0.60) == "MESSY"
    assert _classify_sweep(0.70) == "MESSY"  # strictly > required for CLEAN


def test_invalid_swing_type_raises(mk_candle):
    bad = SwingPointEvent(candle=mk_candle(0, 99, 100, 98, 99.5), swing_type="BOGUS", price_level=100, strength=5, degree="MAJOR", confirmed_at=None)
    try:
        detect_sweep(bad, mk_candle(10, 99.8, 102, 99.7, 99.9))
        assert False, "should have raised"
    except ValueError:
        pass
