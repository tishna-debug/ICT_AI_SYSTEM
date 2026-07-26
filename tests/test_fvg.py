from engine.rules.base import Candle
from engine.rules.fvg import (
    MAX_FVG_AGE_CANDLES,
    body_close_penetration_pct,
    check_htf_wick_exception,
    detect_fvg,
    fvg_fill_threshold,
    update_fvg,
)

TICK = 0.01
ATR14 = 1.0


def test_bullish_fvg_detection(mk_candle):
    c0 = mk_candle(0, 99, 100, 98.5, 99.8)
    c1 = mk_candle(1, 100, 103, 99.9, 102.8)
    c2 = mk_candle(2, 103.2, 104, 103, 103.5)
    fvg = detect_fvg(c0, c1, c2, tick_size=TICK, atr14=ATR14, timeframe="M5", symbol="TEST")
    assert fvg is not None
    assert fvg.direction == "bullish"
    assert fvg.low == 100 and fvg.high == 103


def test_fvg_id_is_deterministic(mk_candle):
    c0 = mk_candle(0, 99, 100, 98.5, 99.8)
    c1 = mk_candle(1, 100, 103, 99.9, 102.8)
    c2 = mk_candle(2, 103.2, 104, 103, 103.5)
    fvg1 = detect_fvg(c0, c1, c2, tick_size=TICK, atr14=ATR14, timeframe="M5", symbol="TEST")
    fvg2 = detect_fvg(c0, c1, c2, tick_size=TICK, atr14=ATR14, timeframe="M5", symbol="TEST")
    assert fvg1.fvg_id == fvg2.fvg_id


def test_rejects_tiny_gap_and_weak_displacement(mk_candle):
    c0 = mk_candle(0, 99, 100, 98.5, 99.8)
    c1 = mk_candle(1, 100, 103, 99.9, 102.8)
    tiny = mk_candle(2, 100.01, 100.02, 100.005, 100.015)
    assert detect_fvg(c0, c1, tiny, tick_size=TICK, atr14=ATR14, timeframe="M5", symbol="TEST") is None

    weak_c1 = mk_candle(1, 100, 100.5, 99.9, 100.2)
    c2 = mk_candle(2, 103.2, 104, 103, 103.5)
    assert detect_fvg(c0, weak_c1, c2, tick_size=TICK, atr14=ATR14, timeframe="M5", symbol="TEST") is None


def test_bearish_fvg_detection(mk_candle):
    b0 = mk_candle(0, 100, 100.5, 99, 99.2)
    b1 = mk_candle(1, 99.2, 99.3, 96, 96.3)
    b2 = mk_candle(2, 96, 96.2, 95, 95.5)
    fvg = detect_fvg(b0, b1, b2, tick_size=TICK, atr14=ATR14, timeframe="M5", symbol="TEST")
    assert fvg.direction == "bearish"
    assert fvg.low == 96.2 and fvg.high == 99


def test_mitigation_lifecycle_close_only(mk_candle):
    c0 = mk_candle(0, 99, 100, 98.5, 99.8)
    c1 = mk_candle(1, 100, 103, 99.9, 102.8)
    c2 = mk_candle(2, 103.2, 104, 103, 103.5)
    # H1 isolates close-only behavior from the M5/M15 HTF wick exception
    fvg = detect_fvg(c0, c1, c2, tick_size=TICK, atr14=ATR14, timeframe="H1", symbol="TEST")

    touch = mk_candle(3, 103.4, 103.6, fvg.mid - 0.1, 103.5)
    ev = update_fvg(fvg, touch, atr14=ATR14, atr_avg50=1.0)
    assert ev.mitigation_type == "PARTIAL"
    assert fvg.is_mitigated is False

    far = mk_candle(4, 110, 111, 109, 110.5)
    assert update_fvg(fvg, far) is None
    assert fvg.age_candles == 1

    close_below = mk_candle(5, 100.5, 100.6, 99.5, 99.8)
    ev2 = update_fvg(fvg, close_below, atr14=ATR14, atr_avg50=1.0)
    assert ev2.mitigation_type == "FULL"
    assert fvg.is_mitigated is True

    assert update_fvg(fvg, mk_candle(6, 99, 99.2, 98.9, 99.1)) is None


def test_violation_flag_on_displaced_close_through(mk_candle):
    c0 = mk_candle(0, 99, 100, 98.5, 99.8)
    c1 = mk_candle(1, 100, 103, 99.9, 102.8)
    c2 = mk_candle(2, 103.2, 104, 103, 103.5)
    fvg = detect_fvg(c0, c1, c2, tick_size=TICK, atr14=ATR14, timeframe="H1", symbol="TEST")

    violent = mk_candle(3, 100.5, 100.6, 96, 96.5)
    ev = update_fvg(fvg, violent, atr14=ATR14)
    assert ev.mitigation_type == "FULL"
    assert fvg.is_violated is True


def test_expiry_after_max_age(mk_candle):
    c0 = mk_candle(0, 99, 100, 98.5, 99.8)
    c1 = mk_candle(1, 100, 103, 99.9, 102.8)
    c2 = mk_candle(2, 103.2, 104, 103, 103.5)
    fvg = detect_fvg(c0, c1, c2, tick_size=TICK, atr14=ATR14, timeframe="H1", symbol="TEST")

    far = mk_candle(100, 200, 201, 199, 200)
    for _ in range(MAX_FVG_AGE_CANDLES):
        update_fvg(fvg, far)
    assert fvg.is_expired is False
    update_fvg(fvg, far)
    assert fvg.is_expired is True


def test_htf_wick_exception_scoped_to_m5_m15(mk_candle):
    c0 = mk_candle(0, 99, 100, 98.5, 99.8)
    c1 = mk_candle(1, 100, 103, 99.9, 102.8)
    c2 = mk_candle(2, 103.2, 104, 103, 103.5)
    wick_only = mk_candle(3, 103.4, 103.6, 99.5, 103.5)

    fvg_m5 = detect_fvg(c0, c1, c2, tick_size=TICK, atr14=ATR14, timeframe="M5", symbol="TEST")
    assert check_htf_wick_exception(fvg_m5, wick_only) is True
    ev = update_fvg(fvg_m5, wick_only)
    assert ev.mitigation_type == "FULL"
    assert fvg_m5.mitigation_confidence == "FULL"

    fvg_h1 = detect_fvg(c0, c1, c2, tick_size=TICK, atr14=ATR14, timeframe="H1", symbol="TEST")
    assert check_htf_wick_exception(fvg_h1, wick_only) is False


def test_fill_threshold_scales_with_volatility():
    assert fvg_fill_threshold(1.0, 2.0) == 0.50
    assert fvg_fill_threshold(4.0, 2.0) == 0.60
    assert 0.50 < fvg_fill_threshold(3.0, 2.0) < 0.60


def test_body_close_penetration_bounded(mk_candle):
    c0 = mk_candle(0, 99, 100, 98.5, 99.8)
    c1 = mk_candle(1, 100, 103, 99.9, 102.8)
    c2 = mk_candle(2, 103.2, 104, 103, 103.5)
    fvg = detect_fvg(c0, c1, c2, tick_size=TICK, atr14=ATR14, timeframe="M5", symbol="TEST")
    p = body_close_penetration_pct(fvg, mk_candle(4, 101, 101.2, 100.8, 101.5))
    assert 0.0 <= p <= 1.0
