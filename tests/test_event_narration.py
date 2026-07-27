from engine.event_narration import describe_event
from engine.rules.bos import BOSEvent
from engine.rules.choch import CHOCHEvent
from engine.rules.fvg import FVGCreatedEvent, FVGMitigatedEvent
from engine.rules.liquidity_sweep import LiquiditySweepEvent
from engine.rules.structure_state import replay
from engine.rules.swings import SwingPointEvent


def _sample_candles(mk_candle):
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


def test_describe_event_covers_every_event_type(mk_candle):
    candles = _sample_candles(mk_candle)
    _, results = replay(candles, symbol="TEST", timeframe="M5", tick_size=0.01, atr_avg50=1.0)
    all_events = [e for r in results for e in r.events]

    seen_types = set()
    for event in all_events:
        description = describe_event(event)
        assert isinstance(description, str) and len(description) > 0
        assert "Unrecognized event" not in description
        seen_types.add(type(event))

    assert SwingPointEvent in seen_types
    assert FVGCreatedEvent in seen_types
    assert BOSEvent in seen_types


def test_describe_event_unrecognized_type_does_not_crash():
    assert "Unrecognized event" in describe_event(object())
