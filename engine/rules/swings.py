"""
engine/rules/swings.py

Phase 1, Step 4 of the ICT Engineering Rulebook build order:
  Step 4 - Swing point detection

Canonical source: ICT-Engineering-Rulebook-Phase1.md, Section 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from engine.rules.base import Candle

# Swing Points (Section 0)
SWING_LOOKBACK = 5          # Candles each side to confirm swing
MIN_SWING_STRENGTH = 2      # Minimum confirming candles each side


@dataclass
class SwingPointEvent:
    candle: Candle
    swing_type: str         # "HIGH" | "LOW"
    price_level: float
    strength: int            # confirming candle count
    degree: str               # "MAJOR" | "MINOR"
    confirmed_at: datetime   # time of right-side confirmation
    event_type: str = "SWING_POINT_CONFIRMED"


def swing_strength(
    candle_index: int,
    candles: List[Candle],
    swing_type: str,
    lookback: int = SWING_LOOKBACK,
) -> int:
    """Count of consecutive candles confirming candle_index as a swing point
    (Section 3.3), moving outward from the pivot one step at a time.

    A step j confirms only if BOTH the left neighbor (index - j) and the
    right neighbor (index + j) satisfy the swing condition; the count stops
    at the first j where either side fails, and is capped at `lookback`
    ("Max = lookback value"). Returns 0 if the full lookback window isn't
    available on both sides (Section 3.6: insufficient lookback at the
    edges of the dataset -> not evaluable, not zero-strength-but-valid).
    """
    if swing_type not in ("HIGH", "LOW"):
        raise ValueError("swing_type must be 'HIGH' or 'LOW'")
    if candle_index - lookback < 0 or candle_index + lookback >= len(candles):
        return 0

    pivot = candles[candle_index]
    pivot_value = pivot.high if swing_type == "HIGH" else pivot.low

    run = 0
    for j in range(1, lookback + 1):
        left = candles[candle_index - j]
        right = candles[candle_index + j]
        if swing_type == "HIGH":
            confirms = pivot_value > left.high and pivot_value > right.high
        else:
            confirms = pivot_value < left.low and pivot_value < right.low
        if not confirms:
            break
        run += 1
    return run


def classify_swing_degree(strength: int, lookback: int = SWING_LOOKBACK) -> str:
    """Section 3.4 / Appendix B: swing degree must be "classified by swing
    strength score, not discretion." Our engineering decision (the rulebook
    states the principle but not an exact cutoff): a swing confirmed for the
    FULL lookback window is MAJOR; anything meeting the minimum bar but not
    the full window is MINOR.
    """
    return "MAJOR" if strength >= lookback else "MINOR"


def detect_swing_point(
    candle_index: int,
    candles: List[Candle],
    swing_type: str,
    lookback: int = SWING_LOOKBACK,
    min_strength: int = MIN_SWING_STRENGTH,
) -> Optional[SwingPointEvent]:
    """Section 3.2 detection for a single candle index/type. Returns None if
    candle_index is not a confirmed swing point of that type (below
    min_strength, or too close to either end of the dataset per Section 3.6).
    """
    strength = swing_strength(candle_index, candles, swing_type, lookback)
    if strength < min_strength:
        return None

    pivot = candles[candle_index]
    price_level = pivot.high if swing_type == "HIGH" else pivot.low
    # "Swing points are confirmed only after SWING_LOOKBACK candles have
    # closed to the right. They are detected in the past, not real time."
    confirmed_at = candles[candle_index + lookback].timestamp

    return SwingPointEvent(
        candle=pivot,
        swing_type=swing_type,
        price_level=price_level,
        strength=strength,
        degree=classify_swing_degree(strength, lookback),
        confirmed_at=confirmed_at,
    )


def find_swing_points(
    candles: List[Candle],
    lookback: int = SWING_LOOKBACK,
    min_strength: int = MIN_SWING_STRENGTH,
) -> List[SwingPointEvent]:
    """Scan a full chronological candle series and return every confirmed
    swing high/low as a SwingPointEvent, in candle order (pivot time, not
    confirmation time).
    """
    events: List[SwingPointEvent] = []
    for i in range(len(candles)):
        for swing_type in ("HIGH", "LOW"):
            event = detect_swing_point(i, candles, swing_type, lookback, min_strength)
            if event is not None:
                events.append(event)
    return events


def is_swing_invalidated(swing: SwingPointEvent, closing_price: float) -> bool:
    """Section 3.5: a Swing High is invalidated when price CLOSES above it;
    a Swing Low is invalidated when price CLOSES below it (close-only, same
    as the BOS rule in Section 5 - wicks don't count).

    Invalidated swings are historical structure, not deleted (Section 3.5)
    - this function only answers the query; callers own retention.
    """
    if swing.swing_type == "HIGH":
        return closing_price > swing.price_level
    return closing_price < swing.price_level
