# ICT AI Trading Intelligence System — ICT Engineering Rulebook
## Phase 1 — Canonical Mathematical Definitions

**Version:** 1.0 | Phase 1 Core Concepts
**Status:** Implementation-Ready
**Concepts:** Candle · Displacement · Swing Points · FVG · BOS · CHOCH · Sweep
**Markets:** US100 · US500 · UDX · XAU/GOLD (Phase 3)

*CONFIDENTIAL — INTERNAL ENGINEERING DOCUMENTATION*

---

## ICT Engineering Rulebook — Phase 1

**Canonical Mathematical Definitions for Deterministic Market State Reconstruction**

- **Version:** 1.0
- **Scope:** Phase 1 Core Concepts Only
- **Status:** Implementation-Ready

**Engineering Rule:** Every concept here must be implementable in Python without human discretion. If a definition requires "judgment," it is not yet a definition — it is still a concept.

---

## 0. System Constants & Thresholds

These are tunable parameters. Set defaults, override per instrument.

```python
# Displacement
MIN_DISPLACEMENT_BODY_RATIO = 0.60      # Body must be >=60% of total range
MIN_DISPLACEMENT_ATR_MULTIPLIER = 1.5   # Body must be >=1.5x ATR(14)

# FVG
MIN_FVG_TICKS = 3                       # Minimum gap size in ticks
MIN_DISPLACEMENT_SCORE = 0.55           # Middle candle displacement threshold

# Swing Points
SWING_LOOKBACK = 5                      # Candles each side to confirm swing
MIN_SWING_STRENGTH = 2                  # Minimum confirming candles each side

# BOS / CHOCH
BOS_REQUIRES_CLOSE = True               # True = close beyond level; False = wick
MIN_BOS_DISPLACEMENT = 0.5              # ATR multiplier for valid BOS body

# Liquidity Sweep
SWEEP_WICK_RATIO = 0.30                 # Wick must be >=30% of total range
SWEEP_RECOVERY_RATIO = 0.50             # Price must recover >=50% of wick

# Candle Age / Invalidation
MAX_FVG_AGE_CANDLES = 50                # FVG expires after N candles
MAX_OB_AGE_CANDLES = 100                # OB expires after N candles
```

---

## 1. Candle Specification

### 1.1 Definition

A candle is the atomic unit of market data. Every analysis engine operates on candles.

```python
@dataclass
class Candle:
    timestamp: datetime   # UTC close time
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str         # "M1","M5","M15","H1","H4","D","W","MN"
    symbol: str             # e.g. "EURUSD", "ES", "BTCUSDT"

    # Derived — computed on construction
    body: float             # abs(close - open)
    range: float            # high - low
    upper_wick: float       # high - max(open, close)
    lower_wick: float       # min(open, close) - low
    direction: str          # "bullish" | "bearish" | "doji"
    body_ratio: float       # body / range (0.0 to 1.0)
    mid_price: float        # (high + low) / 2
```

### 1.2 Derived Field Rules

```
direction:
    IF close > open  -> "bullish"
    IF close < open  -> "bearish"
    IF close == open -> "doji"

body_ratio:
    IF range == 0 -> 0.0 (flat candle / no movement)
    ELSE          -> body / range

upper_wick:
    high - max(open, close)

lower_wick:
    min(open, close) - low
```

### 1.3 Data Quality Rules

A candle is valid ONLY if all of these pass:

- **RULE 1:** `high >= max(open, close)`
- **RULE 2:** `low <= min(open, close)`
- **RULE 3:** `high >= low`
- **RULE 4:** `open > 0, high > 0, low > 0, close > 0`
- **RULE 5:** `volume >= 0`
- **RULE 6:** timestamp is not null and not duplicate

**On failure:** Reject candle. Log anomaly. Do NOT pass to engines.

### 1.4 Event Output

```python
@dataclass
class CandleEvent:
    candle: Candle
    is_valid: bool
    event_type: str = "CANDLE_CLOSED"
```

---

## 2. Displacement

### 2.1 Definition

Displacement is a candle (or sequence of candles) exhibiting institutional-level momentum — strong directional intent, not noise or consolidation.

**Displacement is the prerequisite for FVG, BOS, and CHOCH validity.**

### 2.2 Detection Rules

A single candle is displaced if ALL of the following are true:

**CONDITION 1 — Body Dominance:**
```
candle.body_ratio >= MIN_DISPLACEMENT_BODY_RATIO (default 0.60)
```

**CONDITION 2 — Range Expansion:**
```
candle.range >= ATR(14) * MIN_DISPLACEMENT_ATR_MULTIPLIER (default 1.5)
```

**CONDITION 3 — Direction Clarity:**
```
candle.direction != "doji"
```

### 2.3 Displacement Score

Compute a normalized 0.0–1.0 score for use in confidence weighting:

```python
def displacement_score(candle: Candle, atr14: float) -> float:
    body_score = min(candle.body_ratio / 1.0, 1.0)
    range_score = min(candle.range / (atr14 * 2.0), 1.0)
    return round((body_score * 0.6) + (range_score * 0.4), 4)
```

### 2.4 Edge Cases

| Scenario | Rule |
|---|---|
| Candle range = 0 (flat) | `displacement_score = 0.0`, `is_displaced = False` |
| ATR not yet computable (< 14 candles) | Use range of last N candles as proxy |
| Gap open candle (overnight) | Validate gap is real; do not count gap as displacement body |

### 2.5 Event Output

```python
@dataclass
class DisplacementEvent:
    candle: Candle
    is_displaced: bool
    displacement_score: float   # 0.0 - 1.0
    direction: str               # "bullish" | "bearish"
    event_type: str = "DISPLACEMENT_DETECTED"
```

---

## 3. Swing Points

### 3.1 Definition

A **Swing High** is a local price maximum confirmed by N lower highs on each side.
A **Swing Low** is a local price minimum confirmed by N higher lows on each side.

Swing points define external market structure. They are the anchors for BOS and CHOCH.

### 3.2 Detection Algorithm

```
SWING_HIGH detected at candle[i] if:
    FOR j in range(1, SWING_LOOKBACK + 1):
        candle[i].high > candle[i-j].high (left side)
        candle[i].high > candle[i+j].high (right side)
    AND
        Number of confirming candles each side >= MIN_SWING_STRENGTH

SWING_LOW detected at candle[i] if:
    FOR j in range(1, SWING_LOOKBACK + 1):
        candle[i].low < candle[i-j].low (left side)
        candle[i].low < candle[i+j].low (right side)
    AND
        Number of confirming candles each side >= MIN_SWING_STRENGTH
```

**Important:** Swing points are confirmed only after `SWING_LOOKBACK` candles have closed to the right. They are detected in the past, not in real time.

### 3.3 Swing Strength Score

```python
def swing_strength(candle_index: int, candles: list, lookback: int) -> int:
    """
    Returns count of consecutive candles confirming the swing.
    Higher = stronger structural significance.
    Max = lookback value.
    """
```

### 3.4 Swing Classification

| Type | Price Level | Role |
|---|---|---|
| Major Swing High | Highest high in HTF context | External liquidity target |
| Minor Swing High | Local swing, lower degree | Internal liquidity |
| Major Swing Low | Lowest low in HTF context | External liquidity target |
| Minor Swing Low | Local swing, lower degree | Internal liquidity |

### 3.5 Invalidation Rules

```
A Swing High is invalidated when:
    price closes ABOVE it (BOS occurs)

A Swing Low is invalidated when:
    price closes BELOW it (BOS occurs)
```

Invalidated swing points are retained in history. They are **NOT** deleted — they become historical structure reference.

### 3.6 Edge Cases

| Scenario | Rule |
|---|---|
| Equal highs (within 1 tick) | Treat as same swing level. Tag as EQH (Equal High). |
| Consecutive same-level highs | Use rightmost as confirmed swing |
| Swing on first/last N candles of dataset | Insufficient lookback — skip, do not label |

### 3.7 Event Output

```python
@dataclass
class SwingPointEvent:
    candle: Candle
    swing_type: str        # "HIGH" | "LOW"
    price_level: float
    strength: int           # confirming candle count
    degree: str             # "MAJOR" | "MINOR"
    confirmed_at: datetime  # time of right-side confirmation
    event_type: str = "SWING_POINT_CONFIRMED"
```

---

## 4. Fair Value Gap (FVG)

### 4.1 Definition

A Fair Value Gap is a three-candle price imbalance where the market moved so fast that price did not trade in both directions through a range — leaving an inefficiency that price tends to return to.

### 4.2 Mathematical Detection

**Bullish FVG (gap above — price expected to return from below):**
```
CONDITION 1: candle[2].low > candle[0].high
CONDITION 2: gap_size = candle[2].low - candle[0].high
CONDITION 3: gap_size >= MIN_FVG_TICKS * tick_size
CONDITION 4: displacement_score(candle[1]) >= MIN_DISPLACEMENT_SCORE
```

**Bearish FVG (gap below — price expected to return from above):**
```
CONDITION 1: candle[2].high < candle[0].low
CONDITION 2: gap_size = candle[0].low - candle[2].high
CONDITION 3: gap_size >= MIN_FVG_TICKS * tick_size
CONDITION 4: displacement_score(candle[1]) >= MIN_DISPLACEMENT_SCORE
```

Where:
- `candle[0]` = first candle of the three-candle sequence
- `candle[1]` = middle candle (the displacement candle)
- `candle[2]` = third candle

### 4.3 FVG Properties

```python
@dataclass
class FairValueGap:
    fvg_id: str                       # uuid
    direction: str                    # "bullish" | "bearish"
    timeframe: str
    symbol: str
    high: float                       # top of gap
    low: float                        # bottom of gap
    mid: float                        # (high + low) / 2
    gap_size: float                   # high - low (in price)
    displacement_score: float         # 0.0 - 1.0
    created_at: datetime
    created_by_candle: Candle         # the middle displacement candle

    # State tracking
    is_mitigated: bool = False
    mitigation_type: str = None       # "FULL" | "PARTIAL" | "NONE"
    mitigated_at: datetime = None
    mitigation_candle: Candle = None
    is_violated: bool = False
    is_expired: bool = False
    age_candles: int = 0
```

### 4.4 Mitigation Rules

Our canonical engineering decision on FVG mitigation:

**PARTIAL MITIGATION:**
- Price enters the FVG zone (trades through mid-point)
- FVG remains valid as a partial zone

**FULL MITIGATION:**
- Price closes BEYOND the far edge of the FVG
  - Bullish FVG: a candle closes below `fvg.low`
  - Bearish FVG: a candle closes above `fvg.high`
- → FVG `is_mitigated = True`, `mitigation_type = "FULL"`

**VIOLATION (engineering term, not ICT term):**
- Price trades fully through the FVG with strong momentum AND closes beyond it in the same direction
- → Suggests FVG failed as support/resistance
- → `is_violated = True`

**Engineering Decision on wicks vs bodies:** For mitigation, we use candle close, not wick. Wicks inside FVG do not constitute mitigation. Only a candle body closing beyond the FVG boundary triggers state change.

### 4.5 Expiry Rule

```
Each candle that closes without touching the FVG: age_candles += 1

IF age_candles > MAX_FVG_AGE_CANDLES:
    is_expired = True
    Remove from active FVG list
    Retain in historical record
```

### 4.6 Edge Cases

| Scenario | Rule |
|---|---|
| Overlapping FVGs (same direction, adjacent candles) | Track both independently. Tag as "NESTED_FVG". |
| FVG created at session open gap | Validate gap exists on exchange (not broker interpolation) |
| Tiny FVG below MIN_FVG_TICKS | Reject. Do not create event. |
| FVG on HTF inside LTF BOS | Tag as "ALIGNED" — higher confidence score |

### 4.7 Event Output

```python
@dataclass
class FVGCreatedEvent:
    fvg: FairValueGap
    event_type: str = "FVG_CREATED"

@dataclass
class FVGMitigatedEvent:
    fvg: FairValueGap
    mitigation_type: str      # "PARTIAL" | "FULL"
    mitigation_candle: Candle
    event_type: str = "FVG_MITIGATED"
```

---

## 5. Break of Structure (BOS)

### 5.1 Definition

A Break of Structure (BOS) is the confirmed displacement of price beyond a prior swing point in the direction of the current trend — confirming trend continuation.

**BOS = continuation signal (with the prevailing trend)**

### 5.2 Detection Algorithm

```
BOS_BULLISH detected when:
    1. A prior Swing High exists at level SH
    2. Current candle.close > SH.price_level (if BOS_REQUIRES_CLOSE = True)
       OR current candle.high > SH.price_level (if BOS_REQUIRES_CLOSE = False)
    3. The breaking candle has displacement_score >= MIN_BOS_DISPLACEMENT
    4. The Swing High has NOT been previously broken

BOS_BEARISH detected when:
    1. A prior Swing Low exists at level SL
    2. Current candle.close < SL.price_level
    3. The breaking candle has displacement_score >= MIN_BOS_DISPLACEMENT
    4. The Swing Low has NOT been previously broken
```

**Our canonical engineering decision:**
```
BOS_REQUIRES_CLOSE = True
```
Wicks beyond a swing point do NOT constitute a BOS. Only candle body close.

### 5.3 BOS vs Sweep Disambiguation

This is a critical edge case where most ICT systems fail.

**Liquidity Sweep (NOT a BOS):**
- Candle wick exceeds swing level AND candle closes BACK inside prior range
- → This is a sweep, not a BOS

**True BOS:**
- Candle closes BEYOND swing level
- → Trend continuation confirmed

### 5.4 BOS Properties

```python
@dataclass
class BreakOfStructure:
    bos_id: str
    direction: str                # "bullish" | "bearish"
    timeframe: str
    symbol: str
    broken_swing: SwingPointEvent
    break_price: float             # the swing level that was broken
    breaking_candle: Candle
    displacement_score: float
    created_at: datetime

    # Context
    is_internal: bool               # True = minor swing; False = major swing
    preceded_by_sweep: bool         # Was there a liquidity sweep before break?
```

### 5.5 Invalidation Rules

A BOS event is historical — it cannot be "invalidated." It either occurred or did not.

**HOWEVER:** The trend state it implies CAN be invalidated by a subsequent BOS in the opposite direction. This creates a **CHOCH (Change of Character)**.

### 5.6 Event Output

```python
@dataclass
class BOSEvent:
    bos: BreakOfStructure
    event_type: str = "BOS_CONFIRMED"
```

---

## 6. Change of Character (CHOCH)

### 6.1 Definition

A Change of Character (CHOCH) is a BOS that occurs against the prevailing trend direction — signaling a potential trend reversal.

**CHOCH = reversal signal (against the prevailing trend)**

### 6.2 Detection Algorithm

CHOCH requires a defined current trend. Current Trend State tracks last confirmed BOS direction.

```
CHOCH_BULLISH detected when:
    1. Current trend = BEARISH (last BOS was bearish)
    2. Price breaks a prior Swing High with candle close
    3. The break has displacement_score >= MIN_BOS_DISPLACEMENT
    4. Engineering tag: this BOS is labeled CHOCH, not BOS

CHOCH_BEARISH detected when:
    1. Current trend = BULLISH (last BOS was bullish)
    2. Price breaks a prior Swing Low with candle close
    3. The break has displacement_score >= MIN_BOS_DISPLACEMENT
    4. Engineering tag: this BOS is labeled CHOCH, not BOS
```

### 6.3 CHOCH vs BOS — The Key Engineering Distinction

```python
# Both are detected by the same underlying mechanism.
# The label depends entirely on trend context.
def classify_structure_break(direction: str, current_trend: str) -> str:
    if direction == current_trend:
        return "BOS"    # continuation
    else:
        return "CHOCH"  # potential reversal
```

### 6.4 CHOCH Confidence Levels

Not all CHOCHs are equal. Classify by swing degree:

**HIGH CONFIDENCE CHOCH:**
- Breaks a MAJOR swing point
- With high displacement score
- After a liquidity sweep
- Aligned with HTF bias change

**LOW CONFIDENCE CHOCH:**
- Breaks a MINOR swing point
- Low displacement score
- No preceding sweep
- Counter to HTF bias

### 6.5 Trend State Machine

```python
class TrendState:
    """
    Tracks current structural trend per timeframe.
    Updated only on confirmed BOS or CHOCH.
    """
    current_trend: str          # "BULLISH" | "BEARISH" | "UNDEFINED"
    last_bos: BOSEvent
    last_choch: BOSEvent
    last_swing_high: SwingPointEvent
    last_swing_low: SwingPointEvent
    higher_highs: int            # count since last CHOCH
    lower_lows: int               # count since last CHOCH
```

### 6.6 Event Output

```python
@dataclass
class CHOCHEvent:
    bos: BreakOfStructure   # same data model as BOS
    prior_trend: str         # trend before the CHOCH
    new_bias: str             # implied new direction
    confidence: str           # "HIGH" | "MEDIUM" | "LOW"
    event_type: str = "CHOCH_CONFIRMED"
```

---

## 7. Liquidity Sweep

### 7.1 Definition

A Liquidity Sweep is a price movement that exceeds a prior swing point (triggering resting orders), then rapidly reverses back inside the prior range — without confirming a BOS.

Sweeps represent engineered stop-loss raids by institutional participants.

### 7.2 Detection Algorithm

```
SWEEP_HIGH detected when:
    1. candle.high > prior_swing_high.price_level (wick exceeds level)
    2. candle.close <= prior_swing_high.price_level (closes back inside)
    3. candle.upper_wick / candle.range >= SWEEP_WICK_RATIO (default 0.30)
    4. Recovery confirmed: (candle.high - candle.close) /
       (candle.high - prior_swing_high.price_level) >= SWEEP_RECOVERY_RATIO

SWEEP_LOW detected when:
    1. candle.low < prior_swing_low.price_level
    2. candle.close >= prior_swing_low.price_level
    3. candle.lower_wick / candle.range >= SWEEP_WICK_RATIO
    4. Recovery confirmed
```

### 7.3 Sweep Classification

**CLEAN SWEEP:**
- Single wick spike beyond level
- Immediate close back inside
- High recovery ratio (>0.70)
- → Strong reversal signal

**MESSY SWEEP:**
- Multiple candles near level
- Partial recovery
- → Weaker signal, flag for review

**FAILED SWEEP (becomes BOS):**
- Candle closes beyond level
- → Reclassify as BOS
- → Remove from sweep detection

### 7.4 Sweep + FVG Combination (High-Value Pattern)

When a Sweep occurs AND an FVG is created in the same 3-candle sequence:
- Tag this as `SWEEP_FVG_COMBO`
- Confidence multiplier: +0.15 on any setup forming at this zone

### 7.5 Event Output

```python
@dataclass
class LiquiditySweepEvent:
    sweep_type: str          # "HIGH" | "LOW"
    swept_swing: SwingPointEvent
    sweep_candle: Candle
    wick_ratio: float
    recovery_ratio: float
    sweep_class: str          # "CLEAN" | "MESSY"
    fvg_created: bool         # True if FVG created in same sequence
    event_type: str = "LIQUIDITY_SWEEP"
```

---

## 8. Market Structure State

### 8.1 The StructureState Object

This is the master state object for Phase 1. Updated after every candle.

```python
@dataclass
class StructureState:
    symbol: str
    timeframe: str
    timestamp: datetime          # current candle time

    # Trend
    trend: str                    # "BULLISH" | "BEARISH" | "UNDEFINED"

    # Active Swing Points
    last_swing_high: SwingPointEvent
    last_swing_low: SwingPointEvent

    # Active FVGs
    active_fvgs: List[FairValueGap]       # not yet mitigated or expired
    mitigated_fvgs: List[FairValueGap]    # historical

    # Recent Events (last 50)
    recent_bos: List[BOSEvent]
    recent_choch: List[CHOCHEvent]
    recent_sweeps: List[LiquiditySweepEvent]

    # Candle count (for expiry tracking)
    candle_count: int
```

### 8.2 State Update Rules

On every new valid candle:

1. Increment `candle_count`
2. Compute displacement score
3. Check for new swing points (delayed by `SWING_LOOKBACK`)
4. Check all active FVGs for mitigation
5. Increment FVG age; expire if exceeded
6. Check for BOS / CHOCH against last swing points
7. Check for liquidity sweeps
8. Emit all triggered events
9. Snapshot `StructureState`

### 8.3 Determinism Requirement

```
Given identical candle sequence:
    StructureState must be IDENTICAL on every run.

Verification method:
    hash(StructureState) after N candles
    must equal same hash on replay.
```

This is tested in the validation harness.

---

## 9. Validation Requirements

### 9.1 Minimum Benchmark Before Phase 2

| Concept | Required Precision | Test Count |
|---|---|---|
| FVG Detection | ≥ 90% | 200 labeled examples |
| BOS Detection | ≥ 85% | 150 labeled examples |
| CHOCH Detection | ≥ 85% | 100 labeled examples |
| Swing Point Detection | ≥ 90% | 200 labeled examples |
| Liquidity Sweep | ≥ 80% | 100 labeled examples |
| Deterministic Replay | 100% | 1,000,000 candles |

### 9.2 Labeling Protocol

1. Select 500 historical candles from chosen instrument
2. Manually identify each concept on a chart
3. Record expected output in JSON format
4. Run engine against same candles
5. Compare outputs programmatically
6. Measure precision, recall, F1

### 9.3 Regression Suite

Every time a rule changes in this rulebook:
- Re-run full validation suite
- Any metric drop > 2% triggers investigation before proceeding

---

## 10. Implementation Order

Build in exactly this sequence. Do not skip steps.

1. **Step 1:** Candle dataclass + data quality validation
2. **Step 2:** ATR(14) computation
3. **Step 3:** Displacement score computation
4. **Step 4:** Swing point detection
5. **Step 5:** FVG detection + state tracking
6. **Step 6:** BOS detection + TrendState machine
7. **Step 7:** CHOCH classification
8. **Step 8:** Liquidity sweep detection
9. **Step 9:** StructureState assembly
10. **Step 10:** Event bus (synchronous first)
11. **Step 11:** Snapshot + replay system
12. **Step 12:** Validation harness

---

## Appendix A — Open Engineering Decisions

These require explicit decisions before coding each section.

| Decision | Options | Our Choice | Reason |
|---|---|---|---|
| BOS: close vs wick | Close only / Wick allowed | **Close only** | Reduces false positives |
| FVG mitigation trigger | Body close / Any wick | **Body close** | Deterministic, less noise |
| Swing lookback N | 3, 5, 7 | **5** | Balance sensitivity/stability |
| FVG expiry | 30, 50, 100 candles | **50** | Instrument dependent |
| CHOCH confidence | Binary / Scored | **Scored** | More useful for AI layer |

---

## Appendix B — Known ICT Ambiguities Resolved

| ICT Concept | Ambiguity | Our Resolution |
|---|---|---|
| BOS | Does a wick count? | No. Candle close only. |
| OB | Which candle is the OB? | Last bearish candle before bullish displacement (and vice versa). Defined in Phase 2. |
| FVG validity | Does HTF FVG override LTF? | LTF FVG inside HTF FVG gets +0.10 confidence. Not an override. |
| CHOCH | Minor vs major swing | Classified by swing strength score, not discretion. |
| Sweep | How much wick is enough? | `wick_ratio >= 0.30` AND `recovery_ratio >= 0.50`. Both required. |

---

*End of Phase 1 ICT Engineering Rulebook v1.0*

**Next document:** Canonical Data Models (Python dataclasses + schemas)
**Next implementation:** Candle dataclass + FVG detector
