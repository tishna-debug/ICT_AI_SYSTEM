"""
engine/rules/bias_cascade.py

Addendum A, Section A3: HTF Bias Cascade - determines whether an
entry-timeframe setup (M5/M3/M1) is aligned with the prevailing
higher-timeframe trend, reusing the TrendState machine engine/rules/bos.py
already defines per-timeframe (Section 6.5).

Canonical source: ICT-Rulebook-Addendum-A.md, Section A3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from engine.rules.base import KillZoneEvent
from engine.rules.bos import TrendState

# HTF Bias Cascade (Addendum A, Section A3.2)
PRIMARY_BIAS_TIMEFRAMES = ["D", "H4", "H1", "M15"]
FALLBACK_BIAS_TIMEFRAMES = ["D", "H1", "M15"]   # used only if primary fails
ENTRY_TIMEFRAMES = ["M5", "M3", "M1"]


@dataclass
class BiasCascadeEvent:
    bias: Optional[str]          # "BULLISH" | "BEARISH" | None
    confidence: Optional[str]    # "FULL" | "REDUCED" | None
    timeframes_used: List[str]
    event_type: str = "BIAS_CASCADE_EVALUATED"


def evaluate_bias_cascade(trend_states: Dict[str, TrendState]) -> BiasCascadeEvent:
    """Section A3.3. `trend_states` maps timeframe string -> TrendState.

    Primary check: bias aligned across PRIMARY_BIAS_TIMEFRAMES (D/H4/H1/M15)
    -> FULL confidence. Fallback: drop H4 and check
    FALLBACK_BIAS_TIMEFRAMES (D/H1/M15) -> REDUCED confidence. Neither
    aligned (or a required timeframe simply isn't tracked yet) -> no bias.

    A missing timeframe (not yet in `trend_states`) is treated the same as
    an UNDEFINED trend for that tier - the rulebook's pseudocode assumes
    every timeframe key is always present, which won't be true early in a
    session before enough history has built up on the higher timeframes.
    """

    def trend_of(tf: str) -> str:
        state = trend_states.get(tf)
        return state.current_trend if state is not None else "UNDEFINED"

    primary_trends = [trend_of(tf) for tf in PRIMARY_BIAS_TIMEFRAMES]
    if len(set(primary_trends)) == 1 and primary_trends[0] != "UNDEFINED":
        return BiasCascadeEvent(bias=primary_trends[0], confidence="FULL", timeframes_used=PRIMARY_BIAS_TIMEFRAMES)

    fallback_trends = [trend_of(tf) for tf in FALLBACK_BIAS_TIMEFRAMES]
    if len(set(fallback_trends)) == 1 and fallback_trends[0] != "UNDEFINED":
        return BiasCascadeEvent(bias=fallback_trends[0], confidence="REDUCED", timeframes_used=FALLBACK_BIAS_TIMEFRAMES)

    return BiasCascadeEvent(bias=None, confidence=None, timeframes_used=[])


def is_setup_eligible_for_ai(direction: str, bias_event: BiasCascadeEvent, kill_zone_event: KillZoneEvent) -> bool:
    """Section A3.4 - Entry Filtering: once the bias cascade has a
    non-None bias, an entry-timeframe setup only gets forwarded to the AI
    reasoning layer if BOTH:
      1. its direction matches the cascade's bias, and
      2. its candle falls within a valid Kill Zone (Section A2)

    `direction` is "bullish"/"bearish" (as used throughout engine/rules/);
    `bias_event.bias` is "BULLISH"/"BEARISH" (TrendState's convention) -
    compared case-insensitively here rather than forcing every caller to
    remember the casing mismatch between the two.
    """
    if bias_event.bias is None:
        return False
    if direction.upper() != bias_event.bias:
        return False
    return kill_zone_event.in_kill_zone
