"""
engine/rules/bos.py

Phase 1, Step 6 of the ICT Engineering Rulebook build order:
  Step 6 - BOS detection + TrendState machine

Canonical sources:
  ICT-Engineering-Rulebook-Phase1.md, Section 5 (BOS detection, properties,
    event output) and Section 6.5 (TrendState - the Master Doc maps this
    machine to bos.py since both BOS and CHOCH share it).

Note (Section 5.3): a wick that exceeds a swing level and closes back
inside the prior range is a Liquidity Sweep, not a BOS - that detection
lives in engine/rules/liquidity_sweep.py (its own concept, its own file),
not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from engine.rules.base import Candle, displacement_score
from engine.rules.swings import SwingPointEvent

# BOS / CHOCH (Phase 1, Section 0)
BOS_REQUIRES_CLOSE = True               # True = close beyond level; False = wick
MIN_BOS_DISPLACEMENT = 0.5              # ATR multiplier for valid BOS body


# ---------------------------------------------------------------------------
# Section 5.4 - BOS Properties
# ---------------------------------------------------------------------------


@dataclass
class BreakOfStructure:
    bos_id: str
    direction: str                 # "bullish" | "bearish"
    timeframe: str
    symbol: str
    broken_swing: SwingPointEvent
    break_price: float              # the swing level that was broken
    breaking_candle: Candle
    displacement_score: float
    created_at: datetime

    # Context
    is_internal: bool               # True = minor swing; False = major swing
    preceded_by_sweep: bool = False  # Was there a liquidity sweep before break?


@dataclass
class BOSEvent:
    bos: BreakOfStructure
    event_type: str = "BOS_CONFIRMED"


# ---------------------------------------------------------------------------
# Section 5.2 - Detection Algorithm
# ---------------------------------------------------------------------------


def _breaks_swing(swing: SwingPointEvent, candle: Candle, requires_close: bool = BOS_REQUIRES_CLOSE) -> bool:
    """Does `candle` break the given swing level, per Section 5.2/5.3?

    BOS_REQUIRES_CLOSE = True (our canonical decision): only a candle body
    CLOSE beyond the level counts. A wick alone (requires_close=False) is
    the alternate, non-canonical config option the rulebook documents but
    does not choose.
    """
    price = candle.close if requires_close else (
        candle.high if swing.swing_type == "HIGH" else candle.low
    )
    if swing.swing_type == "HIGH":
        return price > swing.price_level
    return price < swing.price_level


def detect_bos(
    swing: SwingPointEvent,
    candle: Candle,
    atr14: Optional[float],
    timeframe: str,
    symbol: str,
    already_broken: bool = False,
    preceded_by_sweep: bool = False,
    requires_close: bool = BOS_REQUIRES_CLOSE,
) -> Optional[BreakOfStructure]:
    """Section 5.2: a swing high breaking bullish (or swing low breaking
    bearish) with sufficient displacement confirms a BOS.

    `already_broken` is condition 4 ("the swing has NOT been previously
    broken") - this function is stateless, so the caller tracks which
    swings have already produced a BOS (e.g. via a StructureState) and
    passes that in; it is not inferred here.

    Returns None if no BOS is confirmed - including a swing that's already
    been broken, insufficient displacement, or price hasn't closed (or
    wicked, per `requires_close`) beyond the level.
    """
    if already_broken:
        return None
    if not _breaks_swing(swing, candle, requires_close):
        return None

    score = displacement_score(candle, atr14)
    if score < MIN_BOS_DISPLACEMENT:
        return None

    direction = "bullish" if swing.swing_type == "HIGH" else "bearish"

    return BreakOfStructure(
        bos_id=f"{symbol}-{timeframe}-{candle.timestamp.isoformat()}-{direction}",
        direction=direction,
        timeframe=timeframe,
        symbol=symbol,
        broken_swing=swing,
        break_price=swing.price_level,
        breaking_candle=candle,
        displacement_score=score,
        created_at=candle.timestamp,
        is_internal=(swing.degree == "MINOR"),
        preceded_by_sweep=preceded_by_sweep,
    )


def build_bos_event(bos: BreakOfStructure) -> BOSEvent:
    return BOSEvent(bos=bos)


# ---------------------------------------------------------------------------
# Section 6.5 - Trend State Machine
# ---------------------------------------------------------------------------


@dataclass
class TrendState:
    """Tracks current structural trend per timeframe. Updated only on
    confirmed BOS or CHOCH (Section 6.5). This module owns continuation
    (BOS) updates; engine/rules/choch.py (Step 7) owns the reversal
    (CHOCH) relabeling and counter reset, operating on the same object.
    """

    symbol: str
    timeframe: str
    current_trend: str = "UNDEFINED"    # "BULLISH" | "BEARISH" | "UNDEFINED"
    last_bos: Optional[BOSEvent] = None
    last_choch: Optional["object"] = None    # CHOCHEvent, set by choch.py (Step 7)
    last_swing_high: Optional[SwingPointEvent] = None
    last_swing_low: Optional[SwingPointEvent] = None
    higher_highs: int = 0                # count since last CHOCH
    lower_lows: int = 0                   # count since last CHOCH


def update_trend_state_on_bos(trend_state: TrendState, bos_event: BOSEvent) -> None:
    """Apply a confirmed BOS to the trend state (Section 8.2 step 6: "Check
    for BOS / CHOCH against last swing points"). Within this module every
    BOS is by definition a continuation in `bos.direction` - a break that
    goes the *other* way against an established trend is a CHOCH, not a
    BOS (Section 6.3), and is relabeled/handled by choch.py rather than
    passed to this function.
    """
    bos = bos_event.bos
    new_bullish = bos.direction == "bullish"

    trend_state.current_trend = "BULLISH" if new_bullish else "BEARISH"
    trend_state.last_bos = bos_event

    if new_bullish:
        trend_state.last_swing_high = bos.broken_swing
        trend_state.higher_highs += 1
    else:
        trend_state.last_swing_low = bos.broken_swing
        trend_state.lower_lows += 1
