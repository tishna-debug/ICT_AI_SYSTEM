from engine.rules.swings import (
    classify_swing_degree,
    detect_swing_point,
    find_swing_points,
    is_swing_invalidated,
    swing_strength,
)


def test_major_swing_high_full_strength(mk_candle):
    highs = [50] * 5 + [100] + [50] * 5
    candles = [mk_candle(i, h - 1, h, h - 2, h - 1) for i, h in enumerate(highs)]
    ev = detect_swing_point(5, candles, "HIGH", lookback=5, min_strength=2)
    assert ev.strength == 5
    assert ev.degree == "MAJOR"
    assert ev.confirmed_at == candles[10].timestamp


def test_minor_swing_high_partial_strength(mk_candle):
    seq = [50, 40, 130, 30, 40, 100, 40, 30, 130, 40, 50]
    candles = [mk_candle(i, h - 1, h, h - 2, h - 1) for i, h in enumerate(seq)]
    ev = detect_swing_point(5, candles, "HIGH", lookback=5, min_strength=2)
    assert ev.strength == 2
    assert ev.degree == "MINOR"


def test_below_min_strength_not_detected(mk_candle):
    seq = [50, 40, 30, 40, 200, 100, 40, 30, 40, 40, 50]
    candles = [mk_candle(i, h - 1, h, h - 2, h - 1) for i, h in enumerate(seq)]
    assert detect_swing_point(5, candles, "HIGH", lookback=5, min_strength=2) is None


def test_insufficient_lookback_near_edges(mk_candle):
    short = [mk_candle(i, 10, 20, 5, 15) for i in range(6)]
    assert detect_swing_point(2, short, "HIGH", lookback=5, min_strength=2) is None


def test_swing_low_detection(mk_candle):
    lows = [150] * 5 + [50] + [150] * 5
    candles = [mk_candle(i, l + 2, l + 3, l, l + 1) for i, l in enumerate(lows)]
    ev = detect_swing_point(5, candles, "LOW", lookback=5, min_strength=2)
    assert ev.strength == 5
    assert ev.degree == "MAJOR"
    assert ev.swing_type == "LOW"


def test_find_swing_points_scans_full_series(mk_candle):
    highs = [50] * 5 + [100] + [50] * 5
    candles = [mk_candle(i, h - 1, h, h - 2, h - 1) for i, h in enumerate(highs)]
    found = find_swing_points(candles, lookback=5, min_strength=2)
    assert len(found) == 1
    assert found[0].swing_type == "HIGH"


def test_invalidation_is_close_only(mk_candle):
    highs = [50] * 5 + [100] + [50] * 5
    candles = [mk_candle(i, h - 1, h, h - 2, h - 1) for i, h in enumerate(highs)]
    high_ev = detect_swing_point(5, candles, "HIGH", lookback=5, min_strength=2)
    assert is_swing_invalidated(high_ev, closing_price=101) is True
    assert is_swing_invalidated(high_ev, closing_price=99) is False

    lows = [150] * 5 + [50] + [150] * 5
    low_candles = [mk_candle(i, l + 2, l + 3, l, l + 1) for i, l in enumerate(lows)]
    low_ev = detect_swing_point(5, low_candles, "LOW", lookback=5, min_strength=2)
    assert is_swing_invalidated(low_ev, closing_price=49) is True
    assert is_swing_invalidated(low_ev, closing_price=51) is False


def test_invalid_swing_type_raises(mk_candle):
    candles = [mk_candle(i, 10, 20, 5, 15) for i in range(11)]
    try:
        swing_strength(5, candles, "BOGUS", 5)
        assert False, "should have raised"
    except ValueError:
        pass
