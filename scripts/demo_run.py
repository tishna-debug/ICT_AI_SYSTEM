"""
scripts/demo_run.py

Run this to SEE the rule engine working, with plain-English narration, on
a small made-up price story. It needs no real market data and no broker
connection - it's here so you can watch the engine detect things without
having to read Python code or write a script yourself.

Run it with:
    python scripts/demo_run.py

What the made-up story does (all invented numbers, not real prices):
  1. Price consolidates for a bit.
  2. It pushes up to a high, then pulls back - that high becomes a
     "swing point," a landmark the engine will later compare price against.
  3. The pullback leaves a gap in price (a "Fair Value Gap") that the
     engine flags as a zone price may want to revisit.
  4. Price later pushes back up and closes above that original high with
     strong momentum - a "Break of Structure," confirming the trend.

Everything printed below is the engine's own real output - nothing here
is scripted or faked.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.event_bus import EventBus
from engine.rules.base import Candle
from engine.rules.bos import BOSEvent
from engine.rules.choch import CHOCHEvent
from engine.rules.fvg import FVGCreatedEvent, FVGMitigatedEvent
from engine.rules.liquidity_sweep import LiquiditySweepEvent
from engine.rules.structure_state import StructureStateEngine
from engine.rules.swings import SwingPointEvent

SYMBOL = "DEMO"
TIMEFRAME = "M5"
TICK_SIZE = 0.01
BASE_TS = datetime(2026, 1, 1, 9, 0)


def _candle(i: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(
        timestamp=BASE_TS + timedelta(minutes=5 * i),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=100,
        timeframe=TIMEFRAME,
        symbol=SYMBOL,
    )


def build_sample_story() -> list[Candle]:
    candles = []
    # 1. Quiet consolidation
    for i in range(5):
        candles.append(_candle(i, 50 + i, 51 + i, 49 + i, 50.5 + i))
    # 2. Push up to a high of 100, then pull back
    candles.append(_candle(5, 90, 100, 89, 95))
    for i in range(6, 11):
        candles.append(_candle(i, 60 - (i - 6), 61 - (i - 6), 59 - (i - 6), 60.3 - (i - 6)))
    for i in range(11, 14):
        candles.append(_candle(i, 55, 56, 54, 55.5))
    # 3. A fast 3-candle move that leaves a price gap behind
    candles.append(_candle(14, 55, 56, 54.5, 55.5))
    candles.append(_candle(15, 55.6, 62, 55.5, 61.8))
    candles.append(_candle(16, 62.5, 64, 62.2, 63.5))
    # 4. Grind back up toward the old high
    for i in range(17, 25):
        candles.append(_candle(i, 64 + (i - 17) * 4, 68 + (i - 17) * 4, 63 + (i - 17) * 4, 67 + (i - 17) * 4))
    # 5. Strong breakout candle, closing back above the old high (100)
    candles.append(_candle(25, 98, 106, 97.5, 105))
    return candles


def describe(event) -> str:
    ts = None
    if isinstance(event, SwingPointEvent):
        ts = event.confirmed_at
        return (
            f"[{ts:%H:%M}] Swing {event.swing_type} confirmed at {event.price_level:.2f} "
            f"({event.degree}, strength {event.strength})"
        )
    if isinstance(event, FVGCreatedEvent):
        fvg = event.fvg
        ts = fvg.created_at
        return f"[{ts:%H:%M}] {fvg.direction.upper()} Fair Value Gap created: {fvg.low:.2f} - {fvg.high:.2f}"
    if isinstance(event, FVGMitigatedEvent):
        ts = event.mitigation_candle.timestamp
        return f"[{ts:%H:%M}] Fair Value Gap {event.mitigation_type} mitigation (price revisited the gap)"
    if isinstance(event, CHOCHEvent):
        ts = event.bos.created_at
        return (
            f"[{ts:%H:%M}] CHANGE OF CHARACTER - trend flips to {event.new_bias} "
            f"at {event.bos.break_price:.2f} (confidence: {event.confidence})"
        )
    if isinstance(event, BOSEvent):
        ts = event.bos.created_at
        return f"[{ts:%H:%M}] Break of Structure - {event.bos.direction.upper()} continuation at {event.bos.break_price:.2f}"
    if isinstance(event, LiquiditySweepEvent):
        ts = event.sweep_candle.timestamp
        return f"[{ts:%H:%M}] Liquidity Sweep ({event.sweep_class}) at {event.swept_swing.price_level:.2f}"
    return f"Unrecognized event: {event}"


def main() -> None:
    print("=" * 70)
    print("ICT AI Trading System - engine demo (sample data, not real prices)")
    print("=" * 70)

    candles = build_sample_story()
    bus = EventBus()
    bus.subscribe_all(lambda event: print("  " + describe(event)))

    engine = StructureStateEngine(symbol=SYMBOL, timeframe=TIMEFRAME, tick_size=TICK_SIZE, event_bus=bus)

    print(f"\nFeeding {len(candles)} candles through the engine, one at a time...\n")
    for candle in candles:
        result = engine.process_candle(candle, atr_avg50=1.0)
        if result.rejected:
            print(f"  [{candle.timestamp:%H:%M}] REJECTED (bad data): {result.rejection_reasons}")

    print("\n" + "=" * 70)
    print("Final state after all candles:")
    print("=" * 70)
    print(f"  Trend:              {engine.trend_state.current_trend}")
    print(f"  Candles processed:  {engine.candle_count}")
    if engine.last_swing_high:
        print(f"  Last swing high:    {engine.last_swing_high.price_level:.2f} ({engine.last_swing_high.degree})")
    if engine.last_swing_low:
        print(f"  Last swing low:     {engine.last_swing_low.price_level:.2f} ({engine.last_swing_low.degree})")
    print(f"  Active FVGs:        {len(engine.active_fvgs)}")
    print(f"  Mitigated FVGs:     {len(engine.mitigated_fvgs)}")
    print(f"  BOS events:         {len(engine.recent_bos)}")
    print(f"  CHOCH events:       {len(engine.recent_choch)}")
    print(f"  Sweep events:       {len(engine.recent_sweeps)}")
    print()


if __name__ == "__main__":
    main()
