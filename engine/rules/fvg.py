"""
engine/rules/fvg.py

Phase 1, Step 5 of the ICT Engineering Rulebook build order:
  Step 5 - FVG detection + state tracking

Canonical sources:
  ICT-Engineering-Rulebook-Phase1.md, Section 4 (detection, mitigation,
    expiry, event output).
  ICT-Rulebook-Addendum-A.md, Section A1 (mitigation_confidence scoring
    merge + the M15/M5 HTF wick exception - additive only, does not change
    the Section 4.4 state machine).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from engine.rules.base import Candle, displacement_score, is_displaced

# FVG (Phase 1, Section 0)
MIN_FVG_TICKS = 3                       # Minimum gap size in ticks
MIN_DISPLACEMENT_SCORE = 0.55           # Middle candle displacement threshold
MAX_FVG_AGE_CANDLES = 50                # FVG expires after N candles

# FVG Confidence Scoring (Addendum A, Section A1)
FVG_STRONG_FILL_BAND_MIN = 0.50         # 50% fill floor for STRONG confidence tag
FVG_STRONG_FILL_BAND_MAX = 0.60         # 60% fill ceiling for STRONG confidence tag
ATR_BASELINE_PERIOD = 50                # rolling ATR average window for volatility scaling
FVG_HTF_WICK_EXCEPTION_TIMEFRAMES = ["M15", "M5"]


# ---------------------------------------------------------------------------
# Section 4.3 - FVG Properties
# ---------------------------------------------------------------------------


@dataclass
class FairValueGap:
    fvg_id: str                          # uuid
    direction: str                       # "bullish" | "bearish"
    timeframe: str
    symbol: str
    high: float                          # top of gap
    low: float                           # bottom of gap
    mid: float                           # (high + low) / 2
    gap_size: float                      # high - low (in price)
    displacement_score: float            # 0.0 - 1.0
    created_at: datetime
    created_by_candle: Candle            # the middle displacement candle

    # State tracking
    is_mitigated: bool = False
    mitigation_type: Optional[str] = None      # "FULL" | "PARTIAL" | None
    mitigated_at: Optional[datetime] = None
    mitigation_candle: Optional[Candle] = None
    is_violated: bool = False
    is_expired: bool = False
    age_candles: int = 0

    # Addendum A, Section A1 - additive field, does not affect the state
    # machine above.
    mitigation_confidence: str = "NONE"        # "NONE" | "STRONG" | "FULL"


@dataclass
class FVGCreatedEvent:
    fvg: FairValueGap
    event_type: str = "FVG_CREATED"


@dataclass
class FVGMitigatedEvent:
    fvg: FairValueGap
    mitigation_type: str          # "PARTIAL" | "FULL"
    mitigation_candle: Candle
    event_type: str = "FVG_MITIGATED"


# ---------------------------------------------------------------------------
# Section 4.2 - Mathematical Detection
# ---------------------------------------------------------------------------


def detect_fvg(
    candle0: Candle,
    candle1: Candle,
    candle2: Candle,
    tick_size: float,
    atr14: Optional[float],
    timeframe: str,
    symbol: str,
) -> Optional[FairValueGap]:
    """Three-candle FVG detection (Section 4.2). `candle1` is the middle
    displacement candle. `candle0`/`candle1`/`candle2` must be consecutive
    and in chronological order.

    Returns None if no valid FVG forms - including the Section 4.6 edge
    case "Tiny FVG below MIN_FVG_TICKS -> Reject. Do not create event."
    """
    if candle2.low > candle0.high:
        direction = "bullish"
        low, high = candle0.high, candle2.low
    elif candle2.high < candle0.low:
        direction = "bearish"
        low, high = candle2.high, candle0.low
    else:
        return None

    gap_size = high - low
    if gap_size < MIN_FVG_TICKS * tick_size:
        return None

    disp_score = displacement_score(candle1, atr14)
    if disp_score < MIN_DISPLACEMENT_SCORE:
        return None

    # Deterministic, not random (uuid4 would break the Section 8.3 replay
    # determinism requirement: identical candle sequences must produce
    # identical StructureState hashes, so the id must be a pure function
    # of the inputs, not a random draw).
    fvg_id = f"{symbol}-{timeframe}-{candle0.timestamp.isoformat()}-{direction}-FVG"

    return FairValueGap(
        fvg_id=fvg_id,
        direction=direction,
        timeframe=timeframe,
        symbol=symbol,
        high=high,
        low=low,
        mid=(high + low) / 2,
        gap_size=gap_size,
        displacement_score=disp_score,
        created_at=candle2.timestamp,
        created_by_candle=candle1,
    )


def build_fvg_created_event(fvg: FairValueGap) -> FVGCreatedEvent:
    return FVGCreatedEvent(fvg=fvg)


# ---------------------------------------------------------------------------
# Section 4.4 - Mitigation Rules
# ---------------------------------------------------------------------------


def _overlaps(fvg: FairValueGap, candle: Candle) -> bool:
    """Does this candle's high/low range touch the FVG zone at all."""
    return candle.low <= fvg.high and candle.high >= fvg.low


def is_full_mitigation(fvg: FairValueGap, candle: Candle) -> bool:
    """FULL: a candle body CLOSES beyond the far edge of the FVG.
    Bullish FVG -> close below fvg.low. Bearish FVG -> close above fvg.high.
    Wicks alone never trigger this (Section 4.4's explicit engineering
    decision: mitigation uses candle close, not wick).
    """
    if fvg.direction == "bullish":
        return candle.close < fvg.low
    return candle.close > fvg.high


def is_partial_mitigation(fvg: FairValueGap, candle: Candle) -> bool:
    """PARTIAL: price enters the FVG zone and trades through the midpoint.
    This is a wick/range check, not a close check - only FULL requires a
    close.
    """
    if fvg.direction == "bullish":
        return candle.low <= fvg.mid
    return candle.high >= fvg.mid


def check_fvg_violation(fvg: FairValueGap, candle: Candle, atr14: Optional[float]) -> bool:
    """VIOLATION (engineering term, not ICT term - Section 4.4): price trades
    fully through the FVG with strong momentum AND closes beyond it in the
    same direction -> the FVG failed as support/resistance.

    Engineering reading: "fully through with strong momentum" = the
    breaking candle is itself a displaced candle (Section 2) whose
    direction opposes the FVG's own direction (breaks through it rather
    than reacting off it), on top of already satisfying full mitigation.
    """
    if not is_full_mitigation(fvg, candle):
        return False
    if atr14 is None:
        return False
    breaking_direction = "bearish" if fvg.direction == "bullish" else "bullish"
    return candle.direction == breaking_direction and is_displaced(candle, atr14)


def body_close_penetration_pct(fvg: FairValueGap, candle: Candle) -> float:
    """How far the candle's CLOSE has penetrated into the FVG zone, measured
    from the edge price approaches from, as a 0.0-1.0 fraction (clamped).
    0.0 = hasn't reached the gap; 1.0 = closed at/beyond the far edge (full
    mitigation). Used by the Addendum A confidence scoring below - body
    close only, matching the original document's mitigation rule.
    """
    if fvg.high == fvg.low:
        return 0.0
    if fvg.direction == "bullish":
        pct = (fvg.high - candle.close) / (fvg.high - fvg.low)
    else:
        pct = (candle.close - fvg.low) / (fvg.high - fvg.low)
    return max(0.0, min(pct, 1.0))


# ---------------------------------------------------------------------------
# Addendum A, Section A1 - Mitigation Confidence Merge
# ---------------------------------------------------------------------------


def fvg_fill_threshold(atr14: float, atr_avg50: float) -> float:
    """Returns the fill % (as a 0.50-0.60 fraction) required for a PARTIAL
    mitigation to additionally earn the STRONG confidence tag. Scales with
    volatility relative to the 50-period ATR baseline.
    """
    volatility_ratio = atr14 / atr_avg50 if atr_avg50 > 0 else 1.0
    if volatility_ratio <= 1.0:
        return FVG_STRONG_FILL_BAND_MIN
    if volatility_ratio >= 2.0:
        return FVG_STRONG_FILL_BAND_MAX
    return FVG_STRONG_FILL_BAND_MIN + (FVG_STRONG_FILL_BAND_MAX - FVG_STRONG_FILL_BAND_MIN) * min(
        volatility_ratio - 1.0, 1.0
    )


def update_fvg_confidence(fvg: FairValueGap, candle: Candle, atr14: float, atr_avg50: float) -> None:
    """Called on every candle while fvg.is_mitigated == False (state PARTIAL
    or NONE). Does NOT change fvg.mitigation_type - only sets
    mitigation_confidence.
    """
    threshold = fvg_fill_threshold(atr14, atr_avg50)
    fill_pct = body_close_penetration_pct(fvg, candle)

    if fill_pct >= threshold:
        fvg.mitigation_confidence = "STRONG"


def check_htf_wick_exception(fvg: FairValueGap, candle: Candle) -> bool:
    """On M15/M5 only: a full wick fill through the gap is treated as
    equivalent to FULL mitigation, overriding the close-only rule for this
    specific case.
    """
    if fvg.timeframe not in FVG_HTF_WICK_EXCEPTION_TIMEFRAMES:
        return False
    return (fvg.direction == "bullish" and candle.low <= fvg.low) or (
        fvg.direction == "bearish" and candle.high >= fvg.high
    )


# ---------------------------------------------------------------------------
# Section 4.5 - Expiry Rule + combined per-candle state update
# ---------------------------------------------------------------------------


def update_fvg(
    fvg: FairValueGap,
    candle: Candle,
    atr14: Optional[float] = None,
    atr_avg50: Optional[float] = None,
) -> Optional[FVGMitigatedEvent]:
    """Advance a single FVG's state by one new candle: HTF wick exception,
    full/partial mitigation, violation, confidence scoring, and age/expiry
    (Section 4.5: "Each candle that closes without touching the FVG:
    age_candles += 1; IF age_candles > MAX_FVG_AGE_CANDLES: is_expired =
    True"). No-ops once already mitigated or expired - callers own removing
    expired FVGs from their active list per Section 4.5.
    """
    if fvg.is_mitigated or fvg.is_expired:
        return None

    if check_htf_wick_exception(fvg, candle):
        fvg.is_mitigated = True
        fvg.mitigation_type = "FULL"
        fvg.mitigated_at = candle.timestamp
        fvg.mitigation_candle = candle
        fvg.mitigation_confidence = "FULL"
        return FVGMitigatedEvent(fvg=fvg, mitigation_type="FULL", mitigation_candle=candle)

    if not _overlaps(fvg, candle):
        fvg.age_candles += 1
        if fvg.age_candles > MAX_FVG_AGE_CANDLES:
            fvg.is_expired = True
        return None

    if is_full_mitigation(fvg, candle):
        fvg.is_mitigated = True
        fvg.mitigation_type = "FULL"
        fvg.mitigated_at = candle.timestamp
        fvg.mitigation_candle = candle
        fvg.mitigation_confidence = "FULL"
        fvg.is_violated = check_fvg_violation(fvg, candle, atr14)
        return FVGMitigatedEvent(fvg=fvg, mitigation_type="FULL", mitigation_candle=candle)

    if atr14 is not None and atr_avg50 is not None:
        update_fvg_confidence(fvg, candle, atr14, atr_avg50)

    if is_partial_mitigation(fvg, candle):
        fvg.mitigation_type = "PARTIAL"
        return FVGMitigatedEvent(fvg=fvg, mitigation_type="PARTIAL", mitigation_candle=candle)

    return None
