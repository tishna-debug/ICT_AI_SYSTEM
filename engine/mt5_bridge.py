"""
engine/mt5_bridge.py

Build Step 1 (README / Master Doc): live price connection to MetaTrader5.

This module ONLY reads price data. It never places, modifies, or closes a
trade - there is no order-sending code anywhere in this file, on purpose,
matching the system's "advisory only, human places every trade" design.

Connection model (owner's choice): this attaches to whatever MT5 desktop
terminal is ALREADY OPEN AND LOGGED IN on this machine - the owner logs in
by hand via the normal MT5 app, the same way they always would. No account
number or password is ever read, stored, or requested by this code or by
.env. If you want unattended/automatic login instead, that's a deliberate
future change, not something this module does by default.

MetaTrader5 only installs/works on Windows, and only works when the MT5
terminal app is actually running. Both of those are treated as expected,
recoverable failure conditions (per CLAUDE.md's "graceful degradation"
rule) - every function here fails with a clear message and a log entry,
never a crash.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

from engine.logging_config import get_logger
from engine.rules.base import Candle

logger = get_logger("mt5_bridge")

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # expected on non-Windows machines; every function below checks for this

# Only the timeframes the rulebook uses (Candle.timeframe: "M1","M5","M15","H1","H4","D","W","MN")
TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D": "TIMEFRAME_D1",
    "W": "TIMEFRAME_W1",
    "MN": "TIMEFRAME_MN1",
}

# mt5.ACCOUNT_TRADE_MODE_DEMO / _CONTEST / _REAL
TRADE_MODE_LABELS = {0: "DEMO", 1: "CONTEST", 2: "REAL"}


class MT5NotAvailableError(RuntimeError):
    """Raised when the MetaTrader5 package isn't installed (not on Windows,
    or not yet pip-installed) - a normal, expected condition on some
    machines, not a bug.
    """


def _require_mt5() -> None:
    if mt5 is None:
        raise MT5NotAvailableError(
            "The MetaTrader5 package isn't available. It only installs on Windows "
            "(pip install -r requirements.txt handles this automatically there). "
            "On any other OS, this module simply can't run - that's expected."
        )


def _resolve_timeframe(timeframe: str):
    _require_mt5()
    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(f"Unsupported timeframe {timeframe!r}. Supported: {sorted(TIMEFRAME_MAP)}")
    return getattr(mt5, TIMEFRAME_MAP[timeframe])


@dataclass
class ConnectionResult:
    connected: bool
    message: str
    trade_mode: Optional[str] = None
    login: Optional[int] = None
    server: Optional[str] = None
    balance: Optional[float] = None


def connect() -> ConnectionResult:
    """Attach to the already-running, already-logged-in MT5 terminal.

    Does NOT log in itself - if this fails, the fix is almost always
    "open the MT5 desktop app and log into your account first."
    """
    if mt5 is None:
        message = "MetaTrader5 package not installed (expected on non-Windows machines)."
        logger.error(message)
        return ConnectionResult(connected=False, message=message)

    if not mt5.initialize():
        code, description = mt5.last_error()
        message = (
            f"Could not connect to MetaTrader5 (error {code}: {description}). "
            "Make sure the MT5 desktop app is open and logged into an account, then try again."
        )
        logger.error(message)
        return ConnectionResult(connected=False, message=message)

    info = mt5.account_info()
    if info is None:
        message = "Connected to the MT5 terminal, but no account is logged in yet."
        logger.warning(message)
        return ConnectionResult(connected=False, message=message)

    trade_mode = TRADE_MODE_LABELS.get(info.trade_mode, f"UNKNOWN({info.trade_mode})")
    message = f"Connected: {trade_mode} account #{info.login} on server {info.server!r}, balance {info.balance} {info.currency}."
    logger.info(message)
    return ConnectionResult(
        connected=True,
        message=message,
        trade_mode=trade_mode,
        login=info.login,
        server=info.server,
        balance=info.balance,
    )


def disconnect() -> None:
    if mt5 is not None:
        mt5.shutdown()
        logger.info("Disconnected from MT5.")


def find_symbols(search: Optional[str] = None) -> List[str]:
    """List symbol names available on the connected broker, optionally
    filtered (e.g. find_symbols("US100") to find your broker's exact name
    for an instrument - brokers name the same instrument differently,
    e.g. "US100.cash", "NAS100", "USTEC").
    """
    _require_mt5()
    pattern = f"*{search}*" if search else None
    symbols = mt5.symbols_get(group=pattern) if pattern else mt5.symbols_get()
    if symbols is None:
        return []
    return sorted(s.name for s in symbols)


def ensure_symbol_selected(symbol: str) -> bool:
    """MT5 needs a symbol "selected" (visible in Market Watch) before it
    will reliably return historical data for it.
    """
    _require_mt5()
    return bool(mt5.symbol_select(symbol, True))


def get_tick_size(symbol: str) -> Optional[float]:
    """The broker's minimum price increment for this symbol - what
    engine.rules.fvg.detect_fvg's `tick_size` argument expects
    (MIN_FVG_TICKS is measured in units of this). Returns None if the
    symbol isn't known to the broker.
    """
    _require_mt5()
    ensure_symbol_selected(symbol)
    info = mt5.symbol_info(symbol)
    return info.point if info is not None else None


def _row_to_candle(row, timeframe: str, symbol: str) -> Candle:
    # MT5's `time` field is UTC seconds-since-epoch on the broker's server
    # clock. Most brokers align this to UTC, but a few run a fixed offset
    # (commonly UTC+2/UTC+3) - worth checking against your broker if you
    # ever see timestamps that look shifted by a couple of hours.
    return Candle(
        timestamp=datetime.fromtimestamp(int(row["time"]), tz=timezone.utc),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["tick_volume"]),
        timeframe=timeframe,
        symbol=symbol,
    )


def fetch_recent_candles(symbol: str, timeframe: str, count: int = 500) -> List[Candle]:
    """The last `count` fully CLOSED candles, oldest first - ready to feed
    straight into engine.rules.structure_state.StructureStateEngine (or
    .replay()). The still-forming current candle is deliberately excluded
    (start_pos=1 skips it) since the rule engine only ever reacts to
    candle close, never a mid-formation bar.
    """
    _require_mt5()
    mt5_timeframe = _resolve_timeframe(timeframe)
    ensure_symbol_selected(symbol)

    rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 1, count)
    if rates is None:
        code, description = mt5.last_error()
        logger.error(f"copy_rates_from_pos failed for {symbol} {timeframe}: {code} {description}")
        return []

    return [_row_to_candle(row, timeframe, symbol) for row in rates]


def fetch_latest_closed_candle(symbol: str, timeframe: str) -> Optional[Candle]:
    """The single most recently CLOSED candle (excludes the still-forming
    current one). Used for live polling - see MT5CandleFeed below.
    """
    candles = fetch_recent_candles(symbol, timeframe, count=1)
    return candles[0] if candles else None


class MT5CandleFeed:
    """Polls one symbol/timeframe for newly closed candles.

    `fetch_fn` defaults to `fetch_latest_closed_candle` (the real MT5
    call) but can be swapped out in tests, so the de-duplication logic
    below is verifiable without a live MT5 connection.

    Pass `last_seen_timestamp` if you've already processed history up to
    some point (e.g. a backfill via engine.rules.structure_state.replay())
    - otherwise the very first poll() will re-return that same last
    historical candle as if it were new, and the engine will correctly
    (but confusingly) reject it as a duplicate.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        fetch_fn: Optional[Callable[[str, str], Optional[Candle]]] = None,
        last_seen_timestamp: Optional[datetime] = None,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self._fetch_fn = fetch_fn or fetch_latest_closed_candle
        self._last_seen_timestamp: Optional[datetime] = last_seen_timestamp

    def poll(self) -> Optional[Candle]:
        """Returns the newly closed candle if one has appeared since the
        last call to poll(), else None. Cheap to call on a timer even when
        nothing new has happened.
        """
        candle = self._fetch_fn(self.symbol, self.timeframe)
        if candle is None:
            return None
        if self._last_seen_timestamp is not None and candle.timestamp <= self._last_seen_timestamp:
            return None
        self._last_seen_timestamp = candle.timestamp
        return candle


def run_feed(
    feeds: List[MT5CandleFeed],
    on_candle: Callable[[MT5CandleFeed, Candle], None],
    poll_interval_seconds: float = 5.0,
    iterations: Optional[int] = None,
) -> None:
    """Polls every feed in a loop, calling `on_candle(feed, candle)` for
    each newly closed candle found. A failure on one feed (or one poll
    cycle) is logged and skipped, never crashes the loop - per CLAUDE.md's
    "a failure in one module must never crash the whole engine."

    `iterations`: run forever by default (None); pass a number to run that
    many polling cycles then return (used by the test suite).
    """
    count = 0
    while iterations is None or count < iterations:
        for feed in feeds:
            try:
                candle = feed.poll()
                if candle is not None:
                    on_candle(feed, candle)
            except Exception:
                logger.exception(f"Error polling {feed.symbol} {feed.timeframe} - skipping this cycle.")
        count += 1
        if iterations is None or count < iterations:
            time.sleep(poll_interval_seconds)
