"""
scripts/test_mt5.py

Diagnostic script - checks that this computer can talk to your MetaTrader5
terminal, and shows you the exact symbol names your broker uses for the
instruments this system watches (US100, US500, Gold/XAU).

Before running this:
  1. Open the MetaTrader5 desktop app.
  2. Log into your account (demo is fine, and recommended while testing).
  3. Leave it open.

Then run:
    python scripts/test_mt5.py

This never places a trade - it only reads connection status, account
info, and price history.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.mt5_bridge import MT5NotAvailableError, connect, disconnect, fetch_recent_candles, find_symbols

# What the system is designed to watch (per CLAUDE.md Section 1) - used
# here just to help you find your broker's exact symbol spelling for each.
INSTRUMENTS_TO_LOOK_FOR = ["100", "500", "GOLD", "XAU"]


def main() -> int:
    print("=" * 70)
    print("MT5 connection test")
    print("=" * 70)

    try:
        result = connect()
    except MT5NotAvailableError as e:
        print(f"\nCannot run this test: {e}")
        return 1

    if not result.connected:
        print(f"\n{result.message}")
        print("\nMost common fix: open the MT5 desktop app, log into your account, and run this again.")
        return 1

    print(f"\n{result.message}")
    if result.trade_mode != "DEMO":
        print(f"\n*** HEADS UP: this is a {result.trade_mode} account, not a demo account. ***")

    print("\nLooking for your broker's symbol names for US100 / US500 / Gold...")
    seen = set()
    for term in INSTRUMENTS_TO_LOOK_FOR:
        matches = find_symbols(term)
        for m in matches:
            if m not in seen:
                seen.add(m)
                print(f"  - {m}")
    if not seen:
        print("  (no matches found - try opening Market Watch in MT5 and adding the symbols you want, then rerun)")

    if seen:
        example_symbol = sorted(seen)[0]
        print(f"\nFetching the last 5 closed M5 candles for {example_symbol!r} as a live data check...")
        candles = fetch_recent_candles(example_symbol, "M5", count=5)
        if not candles:
            print("  No candles returned - that symbol may need to be added to Market Watch in MT5 first.")
        else:
            for c in candles:
                print(f"  {c.timestamp:%Y-%m-%d %H:%M} UTC  O:{c.open}  H:{c.high}  L:{c.low}  C:{c.close}  V:{c.volume}")

    disconnect()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
