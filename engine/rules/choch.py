"""
engine/rules/choch.py

Phase 1, Step 7 of the ICT Engineering Rulebook build order:
  Step 7 - CHOCH classification

Canonical source: ICT-Engineering-Rulebook-Phase1.md, Section 6.

CHOCH and BOS are detected by the *same* underlying mechanism (Section
6.3) - this module does not re-implement break/displacement detection, it
wraps engine/rules/bos.py's detect_bos() and relabels the result based on
trend context, per the rulebook's own instruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from engine.rules.base import Candle
from engine.rules.bos import (
    BOS_REQUIRES_CLOSE,
    BOSEvent,
    BreakOfStructure,
    TrendState,
    build_bos_event,
    detect_bos,
    update_trend_state_on_bos,
)
from engine.rules.swings import SwingPointEvent

# CHOCH confidence scoring (this module's engineering decision - the
# rulebook's Section 6.4 lists the four qualifying criteria but, per
# Appendix A ("CHOCH confidence: Scored"), leaves the exact scoring
# mechanics to be resolved here rather than specifying a formula).
CHOCH_HIGH_DISPLACEMENT_THRESHOLD = 0.75


@dataclass
class CHOCHEvent:
    bos: BreakOfStructure   # same data model as BOS (Section 6.6)
    prior_trend: str         # trend before the CHOCH
    new_bias: str              # implied new direction
    confidence: str            # "HIGH" | "MEDIUM" | "LOW"
    event_type: str = "CHOCH_CONFIRMED"


# ---------------------------------------------------------------------------
# Section 6.3 - CHOCH vs BOS, the key engineering distinction
# ---------------------------------------------------------------------------


def classify_structure_break(direction: str, current_trend: str) -> str:
    """Both BOS and CHOCH are detected by the same underlying mechanism.
    The label depends entirely on trend context (Section 6.3).

    Section 6.2 only defines CHOCH against an established opposite trend
    (CHOCH_BULLISH requires current trend = BEARISH, CHOCH_BEARISH requires
    BULLISH) - it is silent on UNDEFINED. With no trend established yet
    there is nothing to reverse, so the first-ever confirmed break is
    necessarily a trend-establishing BOS (Section 5, which has no trend
    precondition at all), not a CHOCH.
    """
    if current_trend == "UNDEFINED":
        return "BOS"
    if direction == current_trend.lower():
        return "BOS"    # continuation
    return "CHOCH"       # potential reversal


# ---------------------------------------------------------------------------
# Section 6.4 - CHOCH Confidence Levels
# ---------------------------------------------------------------------------


def classify_choch_confidence(
    is_major_swing: bool,
    displacement_score: float,
    preceded_by_sweep: bool,
    aligned_with_htf_bias: Optional[bool] = None,
) -> str:
    """Section 6.4: not all CHOCHs are equal. Scored (Appendix A), not
    binary, across the four documented criteria:
      - breaks a MAJOR swing point
      - high displacement score
      - preceded by a liquidity sweep
      - aligned with HTF bias change

    `aligned_with_htf_bias=None` means "not yet evaluated" (e.g. the HTF
    bias cascade hasn't run) and is treated as neutral - it neither helps
    nor hurts the score, rather than being counted as a failure.
    """
    criteria_met = 0
    if is_major_swing:
        criteria_met += 1
    if displacement_score >= CHOCH_HIGH_DISPLACEMENT_THRESHOLD:
        criteria_met += 1
    if preceded_by_sweep:
        criteria_met += 1
    if aligned_with_htf_bias is True:
        criteria_met += 1

    if criteria_met >= 4:
        return "HIGH"
    if criteria_met >= 2:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Section 6.5 (trend state reset) + Section 6.2/6.6 - detection & dispatch
# ---------------------------------------------------------------------------


def update_trend_state_on_choch(trend_state: TrendState, choch_event: CHOCHEvent) -> None:
    """A CHOCH resets the "count since last CHOCH" counters (Section 6.5)
    and flips the trend to the new bias.
    """
    trend_state.current_trend = choch_event.new_bias
    trend_state.last_choch = choch_event
    trend_state.higher_highs = 0
    trend_state.lower_lows = 0

    if choch_event.new_bias == "BULLISH":
        trend_state.last_swing_high = choch_event.bos.broken_swing
    else:
        trend_state.last_swing_low = choch_event.bos.broken_swing


def detect_structure_break(
    swing: SwingPointEvent,
    candle: Candle,
    trend_state: TrendState,
    atr14: Optional[float],
    timeframe: str,
    symbol: str,
    already_broken: bool = False,
    preceded_by_sweep: bool = False,
    aligned_with_htf_bias: Optional[bool] = None,
    requires_close: bool = BOS_REQUIRES_CLOSE,
) -> Optional[Union[BOSEvent, CHOCHEvent]]:
    """Single entry point for Section 8.2 step 6 ("Check for BOS / CHOCH
    against last swing points"): detects a structure break, classifies it
    as BOS or CHOCH against `trend_state.current_trend` (Section 6.3), and
    updates `trend_state` accordingly. Returns None if no break is
    confirmed at all.
    """
    bos = detect_bos(
        swing,
        candle,
        atr14,
        timeframe,
        symbol,
        already_broken=already_broken,
        preceded_by_sweep=preceded_by_sweep,
        requires_close=requires_close,
    )
    if bos is None:
        return None

    label = classify_structure_break(bos.direction, trend_state.current_trend)

    if label == "BOS":
        bos_event = build_bos_event(bos)
        update_trend_state_on_bos(trend_state, bos_event)
        return bos_event

    confidence = classify_choch_confidence(
        is_major_swing=not bos.is_internal,
        displacement_score=bos.displacement_score,
        preceded_by_sweep=bos.preceded_by_sweep,
        aligned_with_htf_bias=aligned_with_htf_bias,
    )
    choch_event = CHOCHEvent(
        bos=bos,
        prior_trend=trend_state.current_trend,
        new_bias=bos.direction.upper(),
        confidence=confidence,
    )
    update_trend_state_on_choch(trend_state, choch_event)
    return choch_event
