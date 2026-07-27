"""
engine/rules/base.py

Phase 1, Steps 1-3 of the ICT Engineering Rulebook build order, plus the
Kill Zone Filter from Addendum A (Section A2):
  Step 1 - Candle dataclass + data quality validation
  Step 2 - ATR(14) computation
  Step 3 - Displacement score computation
  Kill Zone Filter - session-window gating for the AI reasoning layer

Canonical sources: ICT-Engineering-Rulebook-Phase1.md, Sections 1-2;
ICT-Rulebook-Addendum-A.md, Section A2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import List, Optional
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# System constants (Section 0 of the rulebook)
# ---------------------------------------------------------------------------

ATR_PERIOD = 14

# Displacement
MIN_DISPLACEMENT_BODY_RATIO = 0.60      # Body must be >=60% of total range
MIN_DISPLACEMENT_ATR_MULTIPLIER = 1.5   # Body must be >=1.5x ATR(14)

# Kill Zones (Addendum A, Section A2) - all times are US Eastern local time
# (what the rulebook calls "EST"; this uses America/New_York so DST is
# handled automatically rather than assuming a fixed UTC offset)
LONDON_KILL_ZONE_START = time(2, 0)
LONDON_KILL_ZONE_END = time(5, 0)
NY_KILL_ZONE_START = time(8, 0)
NY_KILL_ZONE_END = time(11, 0)
NY_HOT_WINDOW_START = time(9, 30)
NY_HOT_WINDOW_END = time(10, 0)
KILL_ZONE_MODE = "filter"  # "filter" = drop setups outside window; "downweight" = tag low confidence instead

_EASTERN = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Section 1 - Candle Specification
# ---------------------------------------------------------------------------


@dataclass
class Candle:
    """The atomic unit of market data. Every analysis engine operates on candles.

    `body`, `range`, `upper_wick`, `lower_wick`, `direction`, `body_ratio`,
    and `mid_price` are derived fields computed on construction (rulebook
    Section 1.2) - callers only need to supply the raw OHLCV fields.
    """

    timestamp: datetime   # UTC close time
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str         # "M1","M5","M15","H1","H4","D","W","MN"
    symbol: str             # e.g. "EURUSD", "ES", "BTCUSDT"

    # Derived - computed on construction, not passed in by callers
    body: float = field(init=False)
    range: float = field(init=False)
    upper_wick: float = field(init=False)
    lower_wick: float = field(init=False)
    direction: str = field(init=False)
    body_ratio: float = field(init=False)
    mid_price: float = field(init=False)

    def __post_init__(self) -> None:
        self.body = abs(self.close - self.open)
        self.range = self.high - self.low
        self.upper_wick = self.high - max(self.open, self.close)
        self.lower_wick = min(self.open, self.close) - self.low
        self.mid_price = (self.high + self.low) / 2

        if self.close > self.open:
            self.direction = "bullish"
        elif self.close < self.open:
            self.direction = "bearish"
        else:
            self.direction = "doji"

        # body_ratio: IF range == 0 -> 0.0 (flat candle / no movement)
        self.body_ratio = 0.0 if self.range == 0 else self.body / self.range


@dataclass
class CandleEvent:
    candle: Candle
    is_valid: bool
    event_type: str = "CANDLE_CLOSED"


# ---------------------------------------------------------------------------
# Section 1.3 - Data Quality Rules
# ---------------------------------------------------------------------------


def validate_candle(candle: Candle, seen_timestamps: Optional[set] = None) -> List[str]:
    """Check a candle against the rulebook's Data Quality Rules (Section 1.3).

    Returns a list of failure reasons (RULE 1..RULE 6). An empty list means
    the candle is valid. `seen_timestamps`, if provided, is used to detect
    duplicate timestamps (RULE 6) against a caller-maintained history; it is
    not mutated here.
    """
    failures: List[str] = []

    if not (candle.high >= max(candle.open, candle.close)):
        failures.append("RULE 1: high >= max(open, close) violated")

    if not (candle.low <= min(candle.open, candle.close)):
        failures.append("RULE 2: low <= min(open, close) violated")

    if not (candle.high >= candle.low):
        failures.append("RULE 3: high >= low violated")

    if not (candle.open > 0 and candle.high > 0 and candle.low > 0 and candle.close > 0):
        failures.append("RULE 4: open/high/low/close must all be > 0")

    if not (candle.volume >= 0):
        failures.append("RULE 5: volume >= 0 violated")

    if candle.timestamp is None:
        failures.append("RULE 6: timestamp is null")
    elif seen_timestamps is not None and candle.timestamp in seen_timestamps:
        failures.append("RULE 6: duplicate timestamp")

    return failures


def is_valid_candle(candle: Candle, seen_timestamps: Optional[set] = None) -> bool:
    """Convenience boolean wrapper around validate_candle."""
    return len(validate_candle(candle, seen_timestamps)) == 0


def build_candle_event(candle: Candle, seen_timestamps: Optional[set] = None) -> CandleEvent:
    """Validate a candle and wrap it in a CandleEvent (Section 1.4).

    On failure the rulebook says: reject candle, log anomaly, do NOT pass to
    engines. This function performs the validation and tagging; the caller
    is responsible for logging and for not forwarding invalid candles.
    """
    return CandleEvent(candle=candle, is_valid=is_valid_candle(candle, seen_timestamps))


# ---------------------------------------------------------------------------
# Section 2.2 / 2.4 - ATR(14)
# ---------------------------------------------------------------------------


def true_range(candle: Candle, prior_close: Optional[float]) -> float:
    """True Range for a single candle.

    TR = max(high - low, abs(high - prior_close), abs(low - prior_close))

    If there is no prior close (first candle in a series), TR falls back to
    the candle's own high-low range.
    """
    if prior_close is None:
        return candle.range
    return max(
        candle.high - candle.low,
        abs(candle.high - prior_close),
        abs(candle.low - prior_close),
    )


def atr(candles: List[Candle], period: int = ATR_PERIOD) -> Optional[float]:
    """Average True Range over `period` candles (default 14), Wilder's method.

    `candles` must be in chronological order (oldest first). Returns None if
    there are fewer than `period + 1` candles, since the first candle only
    contributes a prior close and has no TR of its own to average.

    Per rulebook Section 2.4: "ATR not yet computable (< 14 candles) -> use
    range of last N candles as proxy" — callers needing that fallback should
    use `atr_or_range_proxy` below.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if len(candles) < period + 1:
        return None

    window = candles[-(period + 1):]
    true_ranges = [
        true_range(window[i], window[i - 1].close) for i in range(1, len(window))
    ]

    # Wilder's smoothing: seed with a simple average, then smooth forward.
    atr_value = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr_value = ((atr_value * (period - 1)) + tr) / period

    return atr_value


def atr_series(candles: List[Candle], period: int = ATR_PERIOD) -> List[Optional[float]]:
    """ATR(period) computed at every index of `candles` (chronological order).

    Returns a list the same length as `candles`; entries before ATR becomes
    computable are None.
    """
    result: List[Optional[float]] = [None] * len(candles)
    for i in range(len(candles)):
        result[i] = atr(candles[: i + 1], period)
    return result


def atr_or_range_proxy(candles: List[Candle], period: int = ATR_PERIOD) -> Optional[float]:
    """ATR(period), falling back to the average range of the last N candles
    when there isn't yet enough history for a true ATR (rulebook Section 2.4
    edge case: "ATR not yet computable (< 14 candles) -> use range of last N
    candles as proxy").
    """
    value = atr(candles, period)
    if value is not None:
        return value
    if not candles:
        return None
    window = candles[-period:]
    return sum(c.range for c in window) / len(window)


# ---------------------------------------------------------------------------
# Section 2 - Displacement
# ---------------------------------------------------------------------------


@dataclass
class DisplacementEvent:
    candle: Candle
    is_displaced: bool
    displacement_score: float   # 0.0 - 1.0
    direction: str               # "bullish" | "bearish"
    event_type: str = "DISPLACEMENT_DETECTED"


def displacement_score(candle: Candle, atr14: Optional[float]) -> float:
    """Normalized 0.0-1.0 displacement score (rulebook Section 2.3).

    Edge case (Section 2.4): a flat candle (range == 0) always scores 0.0.
    A missing/zero ATR (not yet computable) is treated the same way as a
    zero range contribution, so callers should pass `atr_or_range_proxy()`
    when fewer than ATR_PERIOD+1 candles exist rather than relying on this
    fallback alone.
    """
    if candle.range == 0:
        return 0.0

    body_score = min(candle.body_ratio / 1.0, 1.0)
    range_score = 0.0 if not atr14 else min(candle.range / (atr14 * 2.0), 1.0)
    return round((body_score * 0.6) + (range_score * 0.4), 4)


def is_displaced(candle: Candle, atr14: Optional[float]) -> bool:
    """Detection rules (Section 2.2) - a candle is displaced iff ALL hold:

    CONDITION 1 - Body Dominance:   body_ratio >= MIN_DISPLACEMENT_BODY_RATIO
    CONDITION 2 - Range Expansion:  range >= ATR(14) * MIN_DISPLACEMENT_ATR_MULTIPLIER
    CONDITION 3 - Direction Clarity: direction != "doji"
    """
    if candle.direction == "doji":
        return False
    if candle.body_ratio < MIN_DISPLACEMENT_BODY_RATIO:
        return False
    if not atr14:
        return False
    return candle.range >= atr14 * MIN_DISPLACEMENT_ATR_MULTIPLIER


def build_displacement_event(candle: Candle, atr14: Optional[float]) -> DisplacementEvent:
    """Evaluate displacement for a candle and wrap it in a DisplacementEvent."""
    return DisplacementEvent(
        candle=candle,
        is_displaced=is_displaced(candle, atr14),
        displacement_score=displacement_score(candle, atr14),
        direction=candle.direction,
    )


# ---------------------------------------------------------------------------
# Addendum A, Section A2 - Kill Zone Filter
# ---------------------------------------------------------------------------


@dataclass
class KillZoneEvent:
    timestamp: datetime
    in_kill_zone: bool
    in_hot_window: bool
    session: str  # "LONDON" | "NY" | "NONE"
    event_type: str = "KILL_ZONE_CHECKED"


def is_in_kill_zone(local_time: time) -> tuple[bool, bool]:
    """Section A2.3. `local_time` must already be in US Eastern local time
    (what the rulebook calls "EST") - see check_kill_zone() below for the
    UTC-candle-timestamp-in, KillZoneEvent-out convenience wrapper.

    Returns (in_kill_zone, in_hot_window). in_hot_window is only
    meaningful when in_kill_zone is True.
    """
    in_london = LONDON_KILL_ZONE_START <= local_time <= LONDON_KILL_ZONE_END
    in_ny = NY_KILL_ZONE_START <= local_time <= NY_KILL_ZONE_END
    in_hot = NY_HOT_WINDOW_START <= local_time <= NY_HOT_WINDOW_END
    return (in_london or in_ny), in_hot


def check_kill_zone(timestamp_utc: datetime) -> KillZoneEvent:
    """Section A2.1/A2.4: takes a candle's UTC timestamp, converts it to US
    Eastern local time (DST-aware), and reports which session (if any) it
    falls in. Outside a Kill Zone, setups are still detected/logged (per
    A2.1, "for the historical record") - it's the caller's job to decide
    whether to withhold them from the AI layer based on `in_kill_zone`
    (KILL_ZONE_MODE = "filter" is the canonical choice; "downweight" is
    the documented alternative, not implemented as a separate code path
    here since it's just a different caller-side policy on the same flag).
    """
    if timestamp_utc.tzinfo is None:
        timestamp_utc = timestamp_utc.replace(tzinfo=ZoneInfo("UTC"))
    local_time = timestamp_utc.astimezone(_EASTERN).time()

    in_kill_zone, in_hot_window = is_in_kill_zone(local_time)
    in_london = LONDON_KILL_ZONE_START <= local_time <= LONDON_KILL_ZONE_END

    if in_london:
        session = "LONDON"
    elif in_kill_zone:
        session = "NY"
    else:
        session = "NONE"

    return KillZoneEvent(
        timestamp=timestamp_utc,
        in_kill_zone=in_kill_zone,
        in_hot_window=in_hot_window,
        session=session,
    )
