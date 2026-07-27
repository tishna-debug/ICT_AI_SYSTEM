"""
scripts/watch_live.py

Watches ONE real symbol/timeframe on your MT5 account and prints detected
ICT patterns (Fair Value Gaps, Break of Structure, swing points, etc.) to
this terminal in real time, as candles actually close. This is the same
rule engine as scripts/demo_run.py - just fed by real live prices instead
of a made-up story.

READ-ONLY: this never places, modifies, or closes a trade. It's a
watcher, not a trader. There is no order-sending code anywhere in this
file or anything it imports.

Before running:
  1. Open the MT5 desktop app and log into your account (demo recommended
     while testing).
  2. Make sure SYMBOL below is visible in your broker's Market Watch -
     run `python scripts/test_mt5.py` first if you're not sure of the
     exact name your broker uses.

To watch a different symbol/timeframe, edit the two constants below.

Run it with:
    python scripts/watch_live.py

Stop it any time with Ctrl+C.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.event_bus import EventBus
from engine.event_narration import describe_event
from engine.mt5_bridge import MT5CandleFeed, MT5NotAvailableError, connect, disconnect, fetch_recent_candles, get_tick_size, run_feed
from engine.rules.base import Candle
from engine.rules.fvg import compute_atr_baseline
from engine.rules.structure_state import StructureStateEngine, replay

# --- Edit these two to watch something else ---
SYMBOL = "USTEC"  # "US Tech 100 Index" on this broker - the US100/Nasdaq-100 CFD
TIMEFRAME = "M5"
# ------------------------------------------------

BACKFILL_CANDLES = 100      # history to load first, so ATR/swings are ready immediately
POLL_INTERVAL_SECONDS = 5   # how often to check MT5 for a newly closed candle


def print_state_summary(engine: StructureStateEngine) -> None:
    print(f"  Trend:              {engine.trend_state.current_trend}")
    print(f"  Candles seen:       {engine.candle_count}")
    if engine.last_swing_high:
        print(f"  Last swing high:    {engine.last_swing_high.price_level:.2f} ({engine.last_swing_high.degree})")
    if engine.last_swing_low:
        print(f"  Last swing low:     {engine.last_swing_low.price_level:.2f} ({engine.last_swing_low.degree})")
    print(f"  Active FVGs:        {len(engine.active_fvgs)}")


def main() -> int:
    print("=" * 70)
    print(f"LIVE WATCH - {SYMBOL} {TIMEFRAME} (read-only, no trades placed)")
    print("=" * 70)

    try:
        result = connect()
    except MT5NotAvailableError as e:
        print(f"\nCannot start: {e}")
        return 1

    if not result.connected:
        print(f"\n{result.message}")
        print("\nMost common fix: open the MT5 desktop app, log into your account, and run this again.")
        return 1

    print(f"\n{result.message}")
    if result.trade_mode != "DEMO":
        print(f"\n*** HEADS UP: this is a {result.trade_mode} account, not a demo account. ***")

    tick_size = get_tick_size(SYMBOL)
    if tick_size is None:
        print(f"\nCouldn't find symbol {SYMBOL!r} on this account.")
        print("Run `python scripts/test_mt5.py` to see the exact symbol names your broker uses.")
        disconnect()
        return 1

    print(f"\nLoading the last {BACKFILL_CANDLES} closed candles to warm up the engine...")
    history = fetch_recent_candles(SYMBOL, TIMEFRAME, count=BACKFILL_CANDLES)
    if not history:
        print("No historical data returned - is this symbol actively trading?")
        disconnect()
        return 1

    engine, _ = replay(history, symbol=SYMBOL, timeframe=TIMEFRAME, tick_size=tick_size)
    print(f"Warmed up on {len(history)} candles. Current state:")
    print_state_summary(engine)

    bus = EventBus()
    bus.subscribe_all(lambda event: print("  " + describe_event(event)))
    engine.event_bus = bus  # only NEW events from here on get narrated - backfill stays quiet

    feed = MT5CandleFeed(SYMBOL, TIMEFRAME, last_seen_timestamp=history[-1].timestamp)

    def on_new_candle(_feed: MT5CandleFeed, candle: Candle) -> None:
        atr_avg50 = compute_atr_baseline(engine.candles + [candle])
        outcome = engine.process_candle(candle, atr_avg50=atr_avg50)
        if outcome.rejected:
            print(f"  [{candle.timestamp:%H:%M}] REJECTED (bad data): {outcome.rejection_reasons}")
        elif not outcome.events:
            print(f"  [{candle.timestamp:%H:%M}] candle closed - close {candle.close}, no new signal")

    print(f"\nWatching live. Checking every {POLL_INTERVAL_SECONDS}s for a new closed candle. Press Ctrl+C to stop.\n")
    try:
        run_feed([feed], on_candle=on_new_candle, poll_interval_seconds=POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\nStopped by you.")
    finally:
        print("\nFinal state:")
        print_state_summary(engine)
        disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
