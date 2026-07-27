"""
main.py

The always-on orchestrator: connects to MT5, runs one StructureStateEngine
per timeframe needed for the HTF Bias Cascade (Daily/H4/H1/M15) plus one
entry timeframe, and watches live. Every new candle updates its
timeframe's engine and pushes alert-worthy events to Telegram. Whenever
the ENTRY timeframe confirms a Break of Structure or Change of Character
(a "setup"), it's checked against the Kill Zone filter and HTF Bias
Cascade (Addendum A) - only if BOTH pass does it get sent to Claude for a
Buy/Sell/No-Trade verdict, which also gets logged and Telegraphed.

READ-ONLY / ADVISORY ONLY: nothing in this file (or anything it imports)
places, modifies, or closes a trade. It only detects, reasons about, and
reports - a human decides what to do with that.

Edit SYMBOL/ENTRY_TIMEFRAME below to point this at something else. Before
running, open the MT5 desktop app and log into your account (demo
recommended). Stop it any time with Ctrl+C.

Run it with:
    python main.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alerts.telegram_bot import TelegramNotifier
from engine.ai_evaluator import AIEvaluator, Verdict, log_verdict
from engine.logging_config import get_logger
from engine.mt5_bridge import (
    MT5CandleFeed,
    MT5NotAvailableError,
    connect,
    disconnect,
    fetch_recent_candles,
    get_tick_size,
    run_feed,
)
from engine.rules.base import Candle, check_kill_zone
from engine.rules.bias_cascade import BiasCascadeEvent, evaluate_bias_cascade, is_setup_eligible_for_ai
from engine.rules.bos import BOSEvent, TrendState
from engine.rules.choch import CHOCHEvent
from engine.rules.fvg import FVGCreatedEvent, compute_atr_baseline
from engine.rules.liquidity_sweep import LiquiditySweepEvent
from engine.rules.structure_state import StructureStateEngine, replay

logger = get_logger("main")

# --- Edit these to point at something else ---
SYMBOL = "USTEC"  # "US Tech 100 Index" on this broker - the US100/Nasdaq-100 CFD
ENTRY_TIMEFRAME = "M5"
# ------------------------------------------------

HTF_TIMEFRAMES = ["D", "H4", "H1", "M15"]  # bias_cascade.PRIMARY_BIAS_TIMEFRAMES
ALL_TIMEFRAMES = HTF_TIMEFRAMES + [ENTRY_TIMEFRAME]

BACKFILL_CANDLES = 100
POLL_INTERVAL_SECONDS = 5

STATUS_PATH = Path(__file__).resolve().parent / "data" / "status.json"

# Which events get pushed to Telegram at all - swing point confirmations
# and partial FVG touches are too frequent/low-signal to text a phone
# about, so they're logged (via engine/logging_config.py) but not alerted.
ALERT_WORTHY_EVENTS = (FVGCreatedEvent, BOSEvent, CHOCHEvent, LiquiditySweepEvent)

# Which events are "confirmed setups" eligible for AI evaluation at all -
# per the Master Doc, that's a structural break, not every FVG.
SETUP_EVENTS = (BOSEvent, CHOCHEvent)


def write_status(state: str, detail: str = "") -> None:
    """Master Doc Section 7: data/status.json is the heartbeat file the
    dashboard (once built) reads to show Running/Stopped/Crashed.
    """
    payload = {
        "state": state,  # "RUNNING" | "STOPPED" | "CRASHED"
        "detail": detail,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": SYMBOL,
        "entry_timeframe": ENTRY_TIMEFRAME,
    }
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        logger.exception("Failed to write status heartbeat (non-fatal, continuing).")


def build_structure_summary(engine: StructureStateEngine) -> str:
    parts = [f"Trend: {engine.trend_state.current_trend}."]
    if engine.last_swing_high:
        parts.append(f"Last swing high: {engine.last_swing_high.price_level:.2f} ({engine.last_swing_high.degree}).")
    if engine.last_swing_low:
        parts.append(f"Last swing low: {engine.last_swing_low.price_level:.2f} ({engine.last_swing_low.degree}).")
    parts.append(f"{len(engine.active_fvgs)} active FVG(s).")
    return " ".join(parts)


def build_bias_summary(bias_event: BiasCascadeEvent, kill_zone_event) -> str:
    bias_text = (
        f"HTF bias: {bias_event.bias} ({bias_event.confidence} confidence)."
        if bias_event.bias
        else "HTF bias: none (higher timeframes disagree)."
    )
    if kill_zone_event.in_kill_zone:
        hot = " (hot window)" if kill_zone_event.in_hot_window else ""
        kz_text = f"Kill Zone: {kill_zone_event.session}{hot}."
    else:
        kz_text = "Kill Zone: outside a valid session."
    return f"{bias_text} {kz_text}"


class TradingOrchestrator:
    """Owns one StructureStateEngine per tracked timeframe, plus the
    Telegram/AI integrations, and drives the live polling loop.
    """

    def __init__(
        self,
        symbol: str = SYMBOL,
        entry_timeframe: str = ENTRY_TIMEFRAME,
        htf_timeframes: Optional[List[str]] = None,
        tick_size: Optional[float] = None,
        telegram: Optional[TelegramNotifier] = None,
        ai: Optional[AIEvaluator] = None,
    ):
        self.symbol = symbol
        self.entry_timeframe = entry_timeframe
        self.htf_timeframes = list(htf_timeframes if htf_timeframes is not None else HTF_TIMEFRAMES)
        self.tick_size = tick_size
        self.telegram = telegram or TelegramNotifier()
        self.ai = ai or AIEvaluator()

        self.engines: Dict[str, StructureStateEngine] = {}
        self.feeds: Dict[str, MT5CandleFeed] = {}

    def warm_up(self, backfill_count: int = BACKFILL_CANDLES) -> None:
        for tf in [self.entry_timeframe] + self.htf_timeframes:
            history = fetch_recent_candles(self.symbol, tf, count=backfill_count)
            if history:
                engine, _ = replay(history, symbol=self.symbol, timeframe=tf, tick_size=self.tick_size)
                last_seen = history[-1].timestamp
            else:
                logger.warning(f"No history returned for {self.symbol} {tf} - starting cold.")
                engine = StructureStateEngine(symbol=self.symbol, timeframe=tf, tick_size=self.tick_size)
                last_seen = None
            self.engines[tf] = engine
            self.feeds[tf] = MT5CandleFeed(self.symbol, tf, last_seen_timestamp=last_seen)

    def trend_states(self) -> Dict[str, TrendState]:
        return {tf: engine.trend_state for tf, engine in self.engines.items()}

    def on_candle(self, feed: MT5CandleFeed, candle: Candle) -> None:
        tf = feed.timeframe
        engine = self.engines[tf]
        atr_avg50 = compute_atr_baseline(engine.candles + [candle])
        result = engine.process_candle(candle, atr_avg50=atr_avg50)

        if result.rejected:
            logger.warning(f"{tf} candle at {candle.timestamp} rejected: {result.rejection_reasons}")
            write_status("RUNNING", f"rejected candle on {tf}: {result.rejection_reasons}")
            return

        for event in result.events:
            if isinstance(event, ALERT_WORTHY_EVENTS):
                self.telegram.notify_event(event)

            if tf == self.entry_timeframe and isinstance(event, SETUP_EVENTS):
                self._handle_setup(event, candle)

        write_status("RUNNING", f"last candle: {tf} @ {candle.timestamp.isoformat()}")

    def _handle_setup(self, event, candle: Candle) -> Optional[Verdict]:
        kill_zone_event = check_kill_zone(candle.timestamp)
        bias_event = evaluate_bias_cascade(self.trend_states())
        direction = event.bos.direction

        if not is_setup_eligible_for_ai(direction, bias_event, kill_zone_event):
            logger.info(
                f"Setup not eligible for AI: direction={direction}, bias={bias_event.bias}, "
                f"in_kill_zone={kill_zone_event.in_kill_zone}"
            )
            return None

        structure_summary = build_structure_summary(self.engines[self.entry_timeframe])
        bias_summary = build_bias_summary(bias_event, kill_zone_event)

        verdict = self.ai.evaluate(
            event, self.symbol, self.entry_timeframe, structure_summary=structure_summary, bias_summary=bias_summary
        )
        log_verdict(verdict)

        message = f"AI VERDICT: {verdict.verdict} ({verdict.confidence} confidence)\n\n{verdict.reasoning}"
        self.telegram.send(message)
        return verdict

    def run(self, poll_interval_seconds: float = POLL_INTERVAL_SECONDS, iterations: Optional[int] = None) -> None:
        run_feed(list(self.feeds.values()), on_candle=self.on_candle, poll_interval_seconds=poll_interval_seconds, iterations=iterations)


def main() -> int:
    print("=" * 70)
    print(f"ICT AI TRADING SYSTEM - live orchestrator ({SYMBOL} {ENTRY_TIMEFRAME})")
    print("Advisory only. Never places a trade.")
    print("=" * 70)

    try:
        result = connect()
    except MT5NotAvailableError as e:
        print(f"\nCannot start: {e}")
        return 1

    if not result.connected:
        print(f"\n{result.message}")
        print("Open the MT5 desktop app, log into your account, and try again.")
        return 1

    print(f"\n{result.message}")
    if result.trade_mode != "DEMO":
        print(f"\n*** HEADS UP: this is a {result.trade_mode} account, not a demo account. ***")

    tick_size = get_tick_size(SYMBOL)
    if tick_size is None:
        print(f"\nCouldn't find symbol {SYMBOL!r} on this account. Run scripts/test_mt5.py to check symbol names.")
        disconnect()
        return 1

    orchestrator = TradingOrchestrator(symbol=SYMBOL, entry_timeframe=ENTRY_TIMEFRAME, tick_size=tick_size)

    if not orchestrator.telegram.is_configured():
        print("\nNote: Telegram isn't configured (see .env.example) - alerts will only be logged, not sent to your phone.")
    if not orchestrator.ai.is_configured():
        print("Note: ANTHROPIC_API_KEY isn't set - confirmed setups will log as NO_TRADE fallbacks instead of real verdicts.")

    print(f"\nWarming up on {BACKFILL_CANDLES} candles across {', '.join([ENTRY_TIMEFRAME] + HTF_TIMEFRAMES)}...")
    orchestrator.warm_up()
    print("Warm-up complete. Watching live - press Ctrl+C to stop.\n")

    write_status("RUNNING", "started")
    try:
        orchestrator.run()
    except KeyboardInterrupt:
        print("\n\nStopped by you.")
        write_status("STOPPED", "stopped by user")
    except Exception as e:
        logger.exception("Unhandled error in main loop.")
        write_status("CRASHED", str(e))
        raise
    finally:
        disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
