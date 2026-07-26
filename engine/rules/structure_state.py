"""
engine/rules/structure_state.py

Phase 1, Step 9 of the ICT Engineering Rulebook build order:
  Step 9 - StructureState assembly

Canonical source: ICT-Engineering-Rulebook-Phase1.md, Section 8.

This module is the per-symbol/timeframe orchestrator that wires together
every concept built in Steps 1-8 (base.py, swings.py, fvg.py, bos.py,
choch.py, liquidity_sweep.py) into the single master state object the
rulebook defines. It is deliberately its own file rather than bolted onto
any single concept file, since StructureState is the aggregate of all of
them, not a concept in its own right.

Note on Section 8.2's 9-step list: it does not explicitly list "detect a
new FVG" as one of the steps, even though Section 4 requires it and the
Master Doc's build order expects FVGs to be live by this point. Treated as
an omission in that summary list and filled in here (see the comment at
its call site below), consistent with how Appendix A/B resolve other
under-specified points in this rulebook.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from engine.event_bus import EventBus

from engine.rules.base import ATR_PERIOD, Candle, atr_or_range_proxy, displacement_score, validate_candle
from engine.rules.bos import BOSEvent, TrendState
from engine.rules.choch import CHOCHEvent, detect_structure_break
from engine.rules.fvg import FairValueGap, FVGCreatedEvent, FVGMitigatedEvent, build_fvg_created_event, detect_fvg, update_fvg
from engine.rules.liquidity_sweep import LiquiditySweepEvent, detect_sweep
from engine.rules.swings import MIN_SWING_STRENGTH, SWING_LOOKBACK, SwingPointEvent, detect_swing_point

# Section 8.1 comment: "Recent Events (last 50)"
MAX_RECENT_EVENTS = 50

StructureEvent = Union[SwingPointEvent, FVGCreatedEvent, FVGMitigatedEvent, BOSEvent, CHOCHEvent, LiquiditySweepEvent]


# ---------------------------------------------------------------------------
# Section 8.1 - The StructureState Object
# ---------------------------------------------------------------------------


@dataclass
class StructureState:
    symbol: str
    timeframe: str
    timestamp: datetime          # current candle time

    # Trend
    trend: str                    # "BULLISH" | "BEARISH" | "UNDEFINED"

    # Active Swing Points
    last_swing_high: Optional[SwingPointEvent]
    last_swing_low: Optional[SwingPointEvent]

    # Active FVGs
    active_fvgs: List[FairValueGap]       # not yet mitigated or expired
    mitigated_fvgs: List[FairValueGap]    # historical

    # Recent Events (last 50)
    recent_bos: List[BOSEvent]
    recent_choch: List[CHOCHEvent]
    recent_sweeps: List[LiquiditySweepEvent]

    # Candle count (for expiry tracking)
    candle_count: int


@dataclass
class UpdateResult:
    """Not part of the rulebook's dataclass vocabulary - the return shape
    of `StructureStateEngine.process_candle()`, bundling the Section 8.2
    step 8 ("Emit all triggered events") output with the step 9 snapshot,
    plus the Section 1.3 reject/log outcome for invalid candles.
    """
    state: StructureState
    events: List[StructureEvent] = field(default_factory=list)
    rejected: bool = False
    rejection_reasons: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Section 8.2 - State Update Rules
# ---------------------------------------------------------------------------


class StructureStateEngine:
    """Maintains the rolling candle history and per-concept state for one
    symbol/timeframe, and advances it one candle at a time per Section 8.2.
    """

    def __init__(self, symbol: str, timeframe: str, tick_size: float, event_bus: Optional["EventBus"] = None):
        self.symbol = symbol
        self.timeframe = timeframe
        self.tick_size = tick_size
        # Step 10 - optional: if provided, every event produced by
        # process_candle is also published here (Section 8.2 step 8,
        # "Emit all triggered events"), in addition to being returned in
        # UpdateResult.events. Decoupled/optional so this module has no
        # hard dependency on engine/event_bus.py for its own tests.
        self.event_bus = event_bus

        self.candles: List[Candle] = []
        self.seen_timestamps: set = set()
        self.candle_count = 0

        self.trend_state = TrendState(symbol=symbol, timeframe=timeframe)

        self.last_swing_high: Optional[SwingPointEvent] = None
        self.last_swing_low: Optional[SwingPointEvent] = None
        self._swing_high_broken = False
        self._swing_low_broken = False

        # A sweep on a prior candle "precedes" a later break of the same
        # swing (Section 5.4's preceded_by_sweep) - tracked here until the
        # next break of that swing consumes it, or a new swing replaces it.
        self._pending_sweep_high = False
        self._pending_sweep_low = False

        self.active_fvgs: List[FairValueGap] = []
        self.mitigated_fvgs: List[FairValueGap] = []
        self.expired_fvgs: List[FairValueGap] = []  # retained per Section 4.5; no slot in StructureState itself

        self.recent_bos: List[BOSEvent] = []
        self.recent_choch: List[CHOCHEvent] = []
        self.recent_sweeps: List[LiquiditySweepEvent] = []

    def process_candle(self, candle: Candle, atr_avg50: Optional[float] = None) -> UpdateResult:
        """Advance state by exactly one new candle (Section 8.2)."""
        failures = validate_candle(candle, self.seen_timestamps)
        if failures:
            # Section 1.3: reject candle, log anomaly, do NOT pass to engines.
            return UpdateResult(state=self.snapshot(candle.timestamp), rejected=True, rejection_reasons=failures)

        self.seen_timestamps.add(candle.timestamp)
        self.candles.append(candle)
        self.candle_count += 1                                        # step 1

        events: List[StructureEvent] = []
        atr14 = atr_or_range_proxy(self.candles, ATR_PERIOD)
        displacement_score(candle, atr14)                              # step 2 (value consumed by steps below)

        events.extend(self._update_swings())                           # step 3

        new_fvg = self._detect_new_fvg(atr14)                          # gap-fill: FVG creation (see module docstring)
        if new_fvg is not None:
            events.append(build_fvg_created_event(new_fvg))

        events.extend(self._update_active_fvgs(candle, atr14, atr_avg50, new_fvg))  # steps 4-5

        events.extend(self._check_structure_breaks(candle, atr14))     # step 6

        events.extend(self._check_sweeps(candle, fvg_created=new_fvg is not None))  # step 7

        if self.event_bus is not None:                                  # step 8
            self.event_bus.publish_many(events)

        state = self.snapshot(candle.timestamp)                        # step 9
        return UpdateResult(state=state, events=events)

    def _update_swings(self) -> List[SwingPointEvent]:
        confirmed: List[SwingPointEvent] = []
        confirm_index = len(self.candles) - 1 - SWING_LOOKBACK
        if confirm_index < 0:
            return confirmed
        for swing_type in ("HIGH", "LOW"):
            swing = detect_swing_point(confirm_index, self.candles, swing_type, SWING_LOOKBACK, MIN_SWING_STRENGTH)
            if swing is None:
                continue
            if swing_type == "HIGH":
                self.last_swing_high = swing
                self._swing_high_broken = False
                self._pending_sweep_high = False
            else:
                self.last_swing_low = swing
                self._swing_low_broken = False
                self._pending_sweep_low = False
            confirmed.append(swing)
        return confirmed

    def _detect_new_fvg(self, atr14: Optional[float]) -> Optional[FairValueGap]:
        if len(self.candles) < 3:
            return None
        c0, c1, c2 = self.candles[-3], self.candles[-2], self.candles[-1]
        fvg = detect_fvg(c0, c1, c2, self.tick_size, atr14, self.timeframe, self.symbol)
        if fvg is not None:
            self.active_fvgs.append(fvg)
        return fvg

    def _update_active_fvgs(
        self,
        candle: Candle,
        atr14: Optional[float],
        atr_avg50: Optional[float],
        skip: Optional[FairValueGap],
    ) -> List[StructureEvent]:
        events: List[StructureEvent] = []
        still_active = []
        for fvg in self.active_fvgs:
            if fvg is skip:
                # just created this candle - nothing to mitigate/age yet
                still_active.append(fvg)
                continue
            mit_event = update_fvg(fvg, candle, atr14, atr_avg50)
            if mit_event is not None:
                events.append(mit_event)
            if fvg.is_mitigated:
                self.mitigated_fvgs.append(fvg)
            elif fvg.is_expired:
                self.expired_fvgs.append(fvg)
            else:
                still_active.append(fvg)
        self.active_fvgs = still_active
        return events

    def _check_structure_breaks(self, candle: Candle, atr14: Optional[float]) -> List[StructureEvent]:
        events: List[StructureEvent] = []
        for swing_type in ("HIGH", "LOW"):
            swing = self.last_swing_high if swing_type == "HIGH" else self.last_swing_low
            already_broken = self._swing_high_broken if swing_type == "HIGH" else self._swing_low_broken
            if swing is None or already_broken:
                continue

            preceded = self._pending_sweep_high if swing_type == "HIGH" else self._pending_sweep_low
            result = detect_structure_break(
                swing,
                candle,
                self.trend_state,
                atr14,
                self.timeframe,
                self.symbol,
                already_broken=already_broken,
                preceded_by_sweep=preceded,
            )
            if result is None:
                continue

            if swing_type == "HIGH":
                self._swing_high_broken = True
                self._pending_sweep_high = False
            else:
                self._swing_low_broken = True
                self._pending_sweep_low = False

            events.append(result)
            if isinstance(result, CHOCHEvent):
                self.recent_choch = (self.recent_choch + [result])[-MAX_RECENT_EVENTS:]
            else:
                self.recent_bos = (self.recent_bos + [result])[-MAX_RECENT_EVENTS:]
        return events

    def _check_sweeps(self, candle: Candle, fvg_created: bool) -> List[StructureEvent]:
        events: List[StructureEvent] = []
        for swing_type in ("HIGH", "LOW"):
            swing = self.last_swing_high if swing_type == "HIGH" else self.last_swing_low
            already_broken = self._swing_high_broken if swing_type == "HIGH" else self._swing_low_broken
            if swing is None or already_broken:
                continue

            sweep = detect_sweep(swing, candle, fvg_created=fvg_created)
            if sweep is None:
                continue

            events.append(sweep)
            self.recent_sweeps = (self.recent_sweeps + [sweep])[-MAX_RECENT_EVENTS:]
            if swing_type == "HIGH":
                self._pending_sweep_high = True
            else:
                self._pending_sweep_low = True
        return events

    def snapshot(self, timestamp: datetime) -> StructureState:
        return StructureState(
            symbol=self.symbol,
            timeframe=self.timeframe,
            timestamp=timestamp,
            trend=self.trend_state.current_trend,
            last_swing_high=self.last_swing_high,
            last_swing_low=self.last_swing_low,
            active_fvgs=list(self.active_fvgs),
            mitigated_fvgs=list(self.mitigated_fvgs),
            recent_bos=list(self.recent_bos),
            recent_choch=list(self.recent_choch),
            recent_sweeps=list(self.recent_sweeps),
            candle_count=self.candle_count,
        )


# ---------------------------------------------------------------------------
# Section 8.3 - Determinism Requirement
# ---------------------------------------------------------------------------


def _to_jsonable(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def structure_state_hash(state: StructureState) -> str:
    """Section 8.3: "Given identical candle sequence: StructureState must
    be IDENTICAL on every run... hash(StructureState) after N candles must
    equal same hash on replay." Python's built-in `hash()` isn't stable
    across dataclasses containing lists/other dataclasses (and isn't even
    process-stable for strings), so this builds a canonical JSON
    representation and hashes that instead.
    """
    payload = json.dumps(_to_jsonable(state), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Step 11 - Snapshot + Replay System
# ---------------------------------------------------------------------------
#
# "Snapshot" = persist a StructureState to JSON (Master Doc Section 7: all
# data is plain JSON files, no database) so it can be reloaded without
# reprocessing full candle history. "Replay" = rebuild a StructureState
# from scratch by reprocessing a full candle history through a fresh
# engine - the mechanism Section 8.3's determinism check depends on, and
# also how offline backtesting against Master Doc's data/price_logs/ works.


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _candle_from_dict(d: dict) -> Candle:
    # Only the raw constructor fields are needed - body/range/direction/etc.
    # are derived fields recomputed by Candle.__post_init__, not trusted
    # from the serialized payload.
    return Candle(
        timestamp=_dt(d["timestamp"]),
        open=d["open"],
        high=d["high"],
        low=d["low"],
        close=d["close"],
        volume=d["volume"],
        timeframe=d["timeframe"],
        symbol=d["symbol"],
    )


def _swing_from_dict(d: Optional[dict]) -> Optional[SwingPointEvent]:
    if d is None:
        return None
    return SwingPointEvent(
        candle=_candle_from_dict(d["candle"]),
        swing_type=d["swing_type"],
        price_level=d["price_level"],
        strength=d["strength"],
        degree=d["degree"],
        confirmed_at=_dt(d["confirmed_at"]),
    )


def _fvg_from_dict(d: dict) -> FairValueGap:
    return FairValueGap(
        fvg_id=d["fvg_id"],
        direction=d["direction"],
        timeframe=d["timeframe"],
        symbol=d["symbol"],
        high=d["high"],
        low=d["low"],
        mid=d["mid"],
        gap_size=d["gap_size"],
        displacement_score=d["displacement_score"],
        created_at=_dt(d["created_at"]),
        created_by_candle=_candle_from_dict(d["created_by_candle"]),
        is_mitigated=d["is_mitigated"],
        mitigation_type=d["mitigation_type"],
        mitigated_at=_dt(d["mitigated_at"]),
        mitigation_candle=_candle_from_dict(d["mitigation_candle"]) if d["mitigation_candle"] else None,
        is_violated=d["is_violated"],
        is_expired=d["is_expired"],
        age_candles=d["age_candles"],
        mitigation_confidence=d["mitigation_confidence"],
    )


def _bos_from_dict(d: dict) -> "BreakOfStructure":
    from engine.rules.bos import BreakOfStructure

    return BreakOfStructure(
        bos_id=d["bos_id"],
        direction=d["direction"],
        timeframe=d["timeframe"],
        symbol=d["symbol"],
        broken_swing=_swing_from_dict(d["broken_swing"]),
        break_price=d["break_price"],
        breaking_candle=_candle_from_dict(d["breaking_candle"]),
        displacement_score=d["displacement_score"],
        created_at=_dt(d["created_at"]),
        is_internal=d["is_internal"],
        preceded_by_sweep=d["preceded_by_sweep"],
    )


def _bos_event_from_dict(d: dict) -> BOSEvent:
    return BOSEvent(bos=_bos_from_dict(d["bos"]))


def _choch_event_from_dict(d: dict) -> CHOCHEvent:
    return CHOCHEvent(
        bos=_bos_from_dict(d["bos"]),
        prior_trend=d["prior_trend"],
        new_bias=d["new_bias"],
        confidence=d["confidence"],
    )


def _sweep_from_dict(d: dict) -> LiquiditySweepEvent:
    return LiquiditySweepEvent(
        sweep_type=d["sweep_type"],
        swept_swing=_swing_from_dict(d["swept_swing"]),
        sweep_candle=_candle_from_dict(d["sweep_candle"]),
        wick_ratio=d["wick_ratio"],
        recovery_ratio=d["recovery_ratio"],
        sweep_class=d["sweep_class"],
        fvg_created=d["fvg_created"],
    )


def structure_state_from_dict(d: dict) -> StructureState:
    """Inverse of `_to_jsonable(state)` - reconstructs a StructureState
    (with real nested dataclass instances, not plain dicts) from its JSON
    representation.
    """
    return StructureState(
        symbol=d["symbol"],
        timeframe=d["timeframe"],
        timestamp=_dt(d["timestamp"]),
        trend=d["trend"],
        last_swing_high=_swing_from_dict(d["last_swing_high"]),
        last_swing_low=_swing_from_dict(d["last_swing_low"]),
        active_fvgs=[_fvg_from_dict(x) for x in d["active_fvgs"]],
        mitigated_fvgs=[_fvg_from_dict(x) for x in d["mitigated_fvgs"]],
        recent_bos=[_bos_event_from_dict(x) for x in d["recent_bos"]],
        recent_choch=[_choch_event_from_dict(x) for x in d["recent_choch"]],
        recent_sweeps=[_sweep_from_dict(x) for x in d["recent_sweeps"]],
        candle_count=d["candle_count"],
    )


def save_snapshot(state: StructureState, path: str) -> None:
    """Persist a StructureState to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_to_jsonable(state), f, sort_keys=True, default=str, indent=2)


def load_snapshot(path: str) -> StructureState:
    """Load a StructureState previously written by `save_snapshot`."""
    with open(path, "r", encoding="utf-8") as f:
        return structure_state_from_dict(json.load(f))


def replay(
    candles: List[Candle],
    symbol: str,
    timeframe: str,
    tick_size: float,
    atr_avg50: Optional[float] = None,
) -> Tuple[StructureStateEngine, List[UpdateResult]]:
    """Rebuild a StructureState from scratch by reprocessing a full candle
    history through a fresh engine, in order. This is the mechanism behind
    both offline backtesting (Master Doc's data/price_logs/) and the
    Section 8.3 determinism check (replay the same sequence twice, compare
    `structure_state_hash` on the resulting snapshots).
    """
    engine = StructureStateEngine(symbol=symbol, timeframe=timeframe, tick_size=tick_size)
    results = [engine.process_candle(candle, atr_avg50=atr_avg50) for candle in candles]
    return engine, results
