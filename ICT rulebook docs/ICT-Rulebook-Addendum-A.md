# ICT Engineering Rulebook — Addendum A

**Companion to:** `ICT_Engineering_Rulebook_Phase1.pdf` (v1.0, the canonical Phase 1 document)
**Status:** Implementation-ready
**Purpose:** This addendum does **not** replace or restate the original rulebook. It adds (1) a confidence-scoring merge on top of the original's FVG mitigation logic, and (2) two new sections — Kill Zone Filtering and HTF Bias Cascade — that the original Phase 1 document does not cover, since they came from later scope decisions (entry timing and multi-timeframe bias).

Engineering Rule (inherited from the original): every concept here must be implementable in Python without human discretion.

---

## A1. FVG Mitigation — Confidence Merge (patches Section 4.4 of the original)

**No change to state transitions.** `PARTIAL`, `FULL`, and `VIOLATED` remain exactly as defined in the original document (Section 4.4): partial = price trades through the gap's midpoint; full = a candle **closes** beyond the gap's far edge; wicks never count toward mitigation on their own.

**New field added to `FairValueGap` dataclass:**

```python
# Added field on the existing FairValueGap dataclass (Section 4.3 of the original)
mitigation_confidence: str = "NONE"  # "NONE" | "STRONG" | "FULL"
```

**New constants (add to Section 0 of the original, alongside existing FVG constants):**

```python
# FVG Confidence Scoring (Addendum A)
FVG_STRONG_FILL_BAND_MIN = 0.50      # 50% fill floor for STRONG confidence tag
FVG_STRONG_FILL_BAND_MAX = 0.60      # 60% fill ceiling for STRONG confidence tag
ATR_BASELINE_PERIOD = 50             # rolling ATR average window for volatility scaling
FVG_HTF_WICK_EXCEPTION_TIMEFRAMES = ["M15", "M5"]
```

**Detection logic:**

```python
def fvg_fill_threshold(atr14: float, atr_avg50: float) -> float:
    """
    Returns the fill % (as a 0.50-0.60 fraction) required for a
    PARTIAL mitigation to additionally earn the STRONG confidence tag.
    Scales with volatility relative to the 50-period ATR baseline.
    """
    volatility_ratio = atr14 / atr_avg50 if atr_avg50 > 0 else 1.0
    if volatility_ratio <= 1.0:
        return FVG_STRONG_FILL_BAND_MIN
    if volatility_ratio >= 2.0:
        return FVG_STRONG_FILL_BAND_MAX
    return FVG_STRONG_FILL_BAND_MIN + (FVG_STRONG_FILL_BAND_MAX - FVG_STRONG_FILL_BAND_MIN) * min(volatility_ratio - 1.0, 1.0)


def update_fvg_confidence(fvg: FairValueGap, candle: Candle, atr14: float, atr_avg50: float) -> None:
    """
    Called on every candle while fvg.is_mitigated == False (state PARTIAL or NONE).
    Does NOT change fvg.mitigation_type — only sets mitigation_confidence.
    """
    threshold = fvg_fill_threshold(atr14, atr_avg50)
    fill_pct = body_close_penetration_pct(fvg, candle)  # existing helper, body close only

    if fill_pct >= threshold:
        fvg.mitigation_confidence = "STRONG"
```

**HTF wick exception (new, does not exist in the original):**

```python
def check_htf_wick_exception(fvg: FairValueGap, candle: Candle) -> bool:
    """
    On M15/M5 only: a full wick fill through the gap is treated as
    equivalent to FULL mitigation, overriding the close-only rule
    for this specific case.
    """
    if fvg.timeframe not in FVG_HTF_WICK_EXCEPTION_TIMEFRAMES:
        return False
    wick_fills_gap = (
        (fvg.direction == "bullish" and candle.low <= fvg.low) or
        (fvg.direction == "bearish" and candle.high >= fvg.high)
    )
    return wick_fills_gap
```

If `check_htf_wick_exception()` returns `True`, set `fvg.is_mitigated = True`, `fvg.mitigation_type = "FULL"`, `fvg.mitigation_confidence = "FULL"` — same event (`FVGMitigatedEvent`) as any other full mitigation, just triggered by a different condition.

**Why this merge preserves the original's integrity:** the state machine, dataclass shape (aside from one added field), and event bus are untouched. `mitigation_confidence` is purely additive information the AI reasoning layer can use — exactly the same pattern the original already uses for CHOCH's `confidence: "HIGH"|"MEDIUM"|"LOW"` field.

---

## A2. Kill Zone Filter (new — not in the original document)

### A2.1 Definition

A Kill Zone is a defined session window during which setups are considered valid for entry evaluation. Outside these windows, setups are still detected and logged (for the historical record, consistent with the original's principle of retaining invalidated structure) but are not passed to the AI reasoning layer.

### A2.2 Constants

```python
# Kill Zones (Addendum A) — all times in EST
LONDON_KILL_ZONE_START = "02:00"
LONDON_KILL_ZONE_END = "05:00"
NY_KILL_ZONE_START = "08:00"
NY_KILL_ZONE_END = "11:00"
NY_HOT_WINDOW_START = "09:30"
NY_HOT_WINDOW_END = "10:00"
KILL_ZONE_MODE = "filter"  # "filter" = drop setups outside window; "downweight" = tag low confidence instead
```

### A2.3 Detection

```python
def is_in_kill_zone(timestamp_est: time) -> tuple[bool, bool]:
    """
    Returns (in_kill_zone, in_hot_window).
    in_hot_window is only meaningful when in_kill_zone is True.
    """
    in_london = LONDON_KILL_ZONE_START <= timestamp_est <= LONDON_KILL_ZONE_END
    in_ny = NY_KILL_ZONE_START <= timestamp_est <= NY_KILL_ZONE_END
    in_hot = NY_HOT_WINDOW_START <= timestamp_est <= NY_HOT_WINDOW_END
    return (in_london or in_ny), in_hot
```

### A2.4 Event Output

```python
@dataclass
class KillZoneEvent:
    timestamp: datetime
    in_kill_zone: bool
    in_hot_window: bool
    session: str  # "LONDON" | "NY" | "NONE"
    event_type: str = "KILL_ZONE_CHECKED"
```

---

## A3. HTF Bias Cascade (new — not in the original document)

### A3.1 Definition

The HTF Bias Cascade determines whether an entry-timeframe setup (M5/M3/M1) is aligned with the prevailing higher-timeframe trend, using the same `TrendState` machine the original document already defines per-timeframe (Section 6.5).

### A3.2 Constants

```python
# HTF Bias Cascade (Addendum A)
PRIMARY_BIAS_TIMEFRAMES = ["D", "H4", "H1", "M15"]
FALLBACK_BIAS_TIMEFRAMES = ["D", "H1", "M15"]   # used only if primary fails
ENTRY_TIMEFRAMES = ["M5", "M3", "M1"]
```

### A3.3 Detection

```python
def evaluate_bias_cascade(trend_states: dict[str, TrendState]) -> dict:
    """
    trend_states: maps timeframe string -> TrendState (from Section 6.5 of the original)
    Returns: { "bias": "BULLISH"|"BEARISH"|None, "confidence": "FULL"|"REDUCED"|None }
    """
    primary_trends = [trend_states[tf].current_trend for tf in PRIMARY_BIAS_TIMEFRAMES]
    if len(set(primary_trends)) == 1 and primary_trends[0] != "UNDEFINED":
        return {"bias": primary_trends[0], "confidence": "FULL"}

    fallback_trends = [trend_states[tf].current_trend for tf in FALLBACK_BIAS_TIMEFRAMES]
    if len(set(fallback_trends)) == 1 and fallback_trends[0] != "UNDEFINED":
        return {"bias": fallback_trends[0], "confidence": "REDUCED"}

    return {"bias": None, "confidence": None}
```

### A3.4 Entry Filtering

Once `evaluate_bias_cascade()` returns a non-`None` bias, entry-timeframe setups (FVG/BOS/CHOCH/Sweep, per the original document's Sections 4–7) are only forwarded to the AI reasoning layer if their direction matches the returned bias, and the setup's candle falls within a valid Kill Zone (Section A2).

### A3.5 Event Output

```python
@dataclass
class BiasCascadeEvent:
    bias: str          # "BULLISH" | "BEARISH"
    confidence: str    # "FULL" | "REDUCED"
    timeframes_used: list[str]
    event_type: str = "BIAS_CASCADE_EVALUATED"
```

---

## A4. Verification

| Item | Conflicts with original? | Resolution |
|---|---|---|
| FVG PARTIAL/FULL state definitions | No — unchanged | Original governs |
| FVG confidence scoring (STRONG tag) | No — additive field only | New, does not alter state transitions |
| 15M/5M wick exception | Technically overrides "close only" — but scoped narrowly to two timeframes, documented as an explicit named exception | Acceptable, consistent with the original's own pattern of documented exceptions (e.g., Appendix B) |
| Kill Zone Filter | Not covered by original | New section, no conflict |
| HTF Bias Cascade | Not covered by original | New section, reuses original's existing `TrendState` machine — no duplicate logic |

---

*This addendum should be uploaded to the project alongside the original `ICT_Engineering_Rulebook_Phase1.pdf` — not in place of it. Together they form the complete rule reference.*
