import os

from engine.rules.bos import BOSEvent
from engine.rules.fvg import FVGCreatedEvent
from engine.rules.structure_state import StructureStateEngine, load_snapshot, replay, save_snapshot, structure_state_hash
from engine.rules.swings import SwingPointEvent


def _sample_candles(mk_candle):
    """A synthetic story: consolidation -> swing high at 100 -> pullback
    forming a bullish FVG -> breakout closing back above 100 (a BOS).
    """
    candles = []
    for i in range(5):
        candles.append(mk_candle(i, 50 + i, 51 + i, 49 + i, 50.5 + i))
    candles.append(mk_candle(5, 90, 100, 89, 95))
    for i in range(6, 11):
        candles.append(mk_candle(i, 60 - (i - 6), 61 - (i - 6), 59 - (i - 6), 60.3 - (i - 6)))
    for i in range(11, 14):
        candles.append(mk_candle(i, 55, 56, 54, 55.5))
    candles.append(mk_candle(14, 55, 56, 54.5, 55.5))
    candles.append(mk_candle(15, 55.6, 62, 55.5, 61.8))
    candles.append(mk_candle(16, 62.5, 64, 62.2, 63.5))
    for i in range(17, 25):
        candles.append(mk_candle(i, 64 + (i - 17) * 4, 68 + (i - 17) * 4, 63 + (i - 17) * 4, 67 + (i - 17) * 4))
    candles.append(mk_candle(25, 98, 106, 97.5, 105))
    return candles


def test_engine_processes_full_story(mk_candle):
    candles = _sample_candles(mk_candle)
    engine, results = replay(candles, symbol="TEST", timeframe="M5", tick_size=0.01, atr_avg50=1.0)
    all_events = [e for r in results for e in r.events]

    assert engine.candle_count == len(candles)
    assert engine.last_swing_high is not None
    assert engine.last_swing_high.price_level == 100
    assert engine.trend_state.current_trend == "BULLISH"

    assert any(isinstance(e, SwingPointEvent) for e in all_events)
    assert any(isinstance(e, FVGCreatedEvent) for e in all_events)
    assert any(isinstance(e, BOSEvent) for e in all_events)


def test_determinism_across_independent_runs(mk_candle):
    candles = _sample_candles(mk_candle)
    engine1, _ = replay(candles, symbol="TEST", timeframe="M5", tick_size=0.01, atr_avg50=1.0)
    engine2, _ = replay(candles, symbol="TEST", timeframe="M5", tick_size=0.01, atr_avg50=1.0)

    h1 = structure_state_hash(engine1.snapshot(candles[-1].timestamp))
    h2 = structure_state_hash(engine2.snapshot(candles[-1].timestamp))
    assert h1 == h2


def test_invalid_candle_is_rejected_without_mutating_state(mk_candle):
    candles = _sample_candles(mk_candle)
    bad = mk_candle(100, 10, 5, 20, 12)  # high < low -> RULE 3 violation
    seq_with_bad = candles[:10] + [bad] + candles[10:]

    engine = StructureStateEngine(symbol="TEST", timeframe="M5", tick_size=0.01)
    rejected = False
    for c in seq_with_bad:
        r = engine.process_candle(c, atr_avg50=1.0)
        if r.rejected:
            rejected = True

    assert rejected is True
    assert engine.candle_count == len(candles)

    clean_engine, _ = replay(candles, symbol="TEST", timeframe="M5", tick_size=0.01, atr_avg50=1.0)
    h_clean = structure_state_hash(clean_engine.snapshot(candles[-1].timestamp))
    h_with_bad = structure_state_hash(engine.snapshot(candles[-1].timestamp))
    assert h_clean == h_with_bad


def test_snapshot_save_load_round_trip(mk_candle, tmp_path):
    candles = _sample_candles(mk_candle)
    engine, _ = replay(candles, symbol="TEST", timeframe="M5", tick_size=0.01, atr_avg50=1.0)
    state = engine.snapshot(candles[-1].timestamp)

    path = os.path.join(tmp_path, "snapshot.json")
    save_snapshot(state, path)
    loaded = load_snapshot(path)

    assert structure_state_hash(state) == structure_state_hash(loaded)
