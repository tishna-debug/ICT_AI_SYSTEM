"""
engine/rules/liquidity_sweep.py

Phase 1, Step 8 of the ICT Engineering Rulebook build order:
  Step 8 - Liquidity sweep detection

Canonical source: ICT-Engineering-Rulebook-Phase1.md, Section 7.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from engine.rules.base import Candle
from engine.rules.swings import SwingPointEvent

# Liquidity Sweep (Phase 1, Section 0)
SWEEP_WICK_RATIO = 0.30                 # Wick must be >=30% of total range
SWEEP_RECOVERY_RATIO = 0.50             # Price must recover >=50% of wick

# Section 7.3 classification threshold ("high recovery ratio (>0.70)" for CLEAN)
SWEEP_CLEAN_RECOVERY_RATIO = 0.70

# Section 7.4 - exposed for downstream confidence scoring (e.g. setup
# assembly / the AI evaluator layer); this module only exposes the
# SWEEP_FVG_COMBO signal via `fvg_created`, it does not apply the bonus.
SWEEP_FVG_COMBO_CONFIDENCE_BONUS = 0.15


@dataclass
class LiquiditySweepEvent:
    sweep_type: str           # "HIGH" | "LOW"
    swept_swing: SwingPointEvent
    sweep_candle: Candle
    wick_ratio: float
    recovery_ratio: float
    sweep_class: str           # "CLEAN" | "MESSY"
    fvg_created: bool           # True if FVG created in same sequence
    event_type: str = "LIQUIDITY_SWEEP"


def _classify_sweep(recovery_ratio: float) -> str:
    """Section 7.3: CLEAN = single wick spike, immediate close back inside,
    high recovery ratio (>0.70). Anything meeting the minimum detection
    bar (Section 7.2) but not clearing 0.70 recovery is MESSY.
    """
    return "CLEAN" if recovery_ratio > SWEEP_CLEAN_RECOVERY_RATIO else "MESSY"


def detect_sweep(
    swing: SwingPointEvent,
    candle: Candle,
    fvg_created: bool = False,
) -> Optional[LiquiditySweepEvent]:
    """Section 7.2: a Liquidity Sweep is a wick that exceeds a prior swing
    level (triggering resting orders) and then closes back inside the
    prior range, with a large-enough wick and enough recovery.

    Note (Section 7.3, "FAILED SWEEP"): if the candle instead CLOSES beyond
    the swing level, that's not a sweep at all - it's a candidate BOS
    (engine/rules/bos.py's detect_bos handles that case; the two functions
    are complementary, not overlapping - a given candle/swing pair can only
    satisfy one of them, never both, since sweep condition 2 and BOS's
    close-beyond-level condition are mutually exclusive).

    Returns None if any condition fails, or if candle.range == 0 (a flat
    candle has no wick to measure).
    """
    if candle.range == 0:
        return None

    if swing.swing_type == "HIGH":
        if not (candle.high > swing.price_level):          # condition 1
            return None
        if not (candle.close <= swing.price_level):         # condition 2
            return None
        wick_ratio = candle.upper_wick / candle.range
        if wick_ratio < SWEEP_WICK_RATIO:                    # condition 3
            return None
        recovery_ratio = (candle.high - candle.close) / (candle.high - swing.price_level)
        if recovery_ratio < SWEEP_RECOVERY_RATIO:             # condition 4
            return None
    elif swing.swing_type == "LOW":
        if not (candle.low < swing.price_level):
            return None
        if not (candle.close >= swing.price_level):
            return None
        wick_ratio = candle.lower_wick / candle.range
        if wick_ratio < SWEEP_WICK_RATIO:
            return None
        recovery_ratio = (candle.close - candle.low) / (swing.price_level - candle.low)
        if recovery_ratio < SWEEP_RECOVERY_RATIO:
            return None
    else:
        raise ValueError("swing.swing_type must be 'HIGH' or 'LOW'")

    return LiquiditySweepEvent(
        sweep_type=swing.swing_type,
        swept_swing=swing,
        sweep_candle=candle,
        wick_ratio=wick_ratio,
        recovery_ratio=recovery_ratio,
        sweep_class=_classify_sweep(recovery_ratio),
        fvg_created=fvg_created,
    )
