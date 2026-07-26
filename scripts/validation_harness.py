"""
scripts/validation_harness.py

Phase 1, Step 12 of the ICT Engineering Rulebook build order:
  Step 12 - Validation harness

Canonical source: ICT-Engineering-Rulebook-Phase1.md, Section 9.

This is a TOOL, not a dataset. Section 9.2's labeling protocol is a manual
process - reviewing real historical candles on a real chart and recording
what a human sees - that has to be done by a person, not fabricated here.
This script only compares the engine's actual output against whatever
labeled JSON you supply, and reports precision/recall/F1 per concept
against the Section 9.1 thresholds.

Usage:
    python scripts/validation_harness.py <candles.json> <labels.json>
    python scripts/validation_harness.py <candles.json> <labels.json> --save results.json
    python scripts/validation_harness.py <candles.json> <labels.json> --baseline previous_results.json

candles.json - a flat JSON list of OHLCV records for one symbol/timeframe,
    oldest first:
    [
      {"timestamp": "2026-01-01T00:00:00", "open": 1.234, "high": 1.236,
       "low": 1.233, "close": 1.235, "volume": 120,
       "timeframe": "M5", "symbol": "EURUSD"},
      ...
    ]

labels.json - the hand-labeled expected output, per Section 9.2:
    {
      "symbol": "EURUSD",
      "timeframe": "M5",
      "tick_size": 0.0001,
      "labels": {
        "swing": [{"swing_type": "HIGH", "price_level": 1.2345,
                    "confirmed_at": "2026-01-01T00:25:00"}, ...],
        "fvg":   [{"direction": "bullish", "low": 1.2340, "high": 1.2350,
                    "created_at": "2026-01-01T00:15:00"}, ...],
        "bos":   [{"direction": "bullish", "break_price": 1.2345,
                    "created_at": "2026-01-01T00:40:00"}, ...],
        "choch": [{"new_bias": "BEARISH", "break_price": 1.2300,
                    "created_at": "2026-01-01T01:10:00"}, ...],
        "sweep": [{"sweep_type": "HIGH", "price_level": 1.2345,
                    "sweep_at": "2026-01-01T00:30:00"}, ...]
      }
    }

A label's timestamp field must match the candle timestamp at which the
engine confirms/creates that event (swing: right-side confirmation
candle; FVG: the third candle; BOS/CHOCH: the breaking candle; sweep: the
sweeping candle) - detection is deterministic per candle close, so this is
an exact match, not a fuzzy window.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, __file__.rsplit("scripts", 1)[0] or ".")

from engine.rules.base import Candle
from engine.rules.bos import BOSEvent
from engine.rules.choch import CHOCHEvent
from engine.rules.fvg import FVGCreatedEvent
from engine.rules.liquidity_sweep import LiquiditySweepEvent
from engine.rules.structure_state import replay
from engine.rules.swings import SwingPointEvent

# Section 9.1 - Minimum Benchmark Before Phase 2 (precision targets)
VALIDATION_THRESHOLDS = {
    "fvg": 0.90,
    "bos": 0.85,
    "choch": 0.85,
    "swing": 0.90,
    "sweep": 0.80,
}

# Section 9.3: "Any metric drop > 2% triggers investigation before proceeding."
REGRESSION_DROP_THRESHOLD = 0.02


def load_candles(path: str) -> List[Candle]:
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)
    return [
        Candle(
            timestamp=datetime.fromisoformat(r["timestamp"]),
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            timeframe=r["timeframe"],
            symbol=r["symbol"],
        )
        for r in records
    ]


def load_labels(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_actual(events: List[object]) -> Dict[str, List[dict]]:
    """Flatten the engine's raw event objects into the same comparable
    shape as a labels.json file's `labels` section.
    """
    actual: Dict[str, List[dict]] = {"swing": [], "fvg": [], "bos": [], "choch": [], "sweep": []}

    for event in events:
        if isinstance(event, SwingPointEvent):
            actual["swing"].append(
                {
                    "swing_type": event.swing_type,
                    "price_level": event.price_level,
                    "confirmed_at": event.confirmed_at.isoformat(),
                }
            )
        elif isinstance(event, FVGCreatedEvent):
            actual["fvg"].append(
                {
                    "direction": event.fvg.direction,
                    "low": event.fvg.low,
                    "high": event.fvg.high,
                    "created_at": event.fvg.created_at.isoformat(),
                }
            )
        elif isinstance(event, CHOCHEvent):
            actual["choch"].append(
                {
                    "new_bias": event.new_bias,
                    "break_price": event.bos.break_price,
                    "created_at": event.bos.created_at.isoformat(),
                }
            )
        elif isinstance(event, BOSEvent):
            actual["bos"].append(
                {
                    "direction": event.bos.direction,
                    "break_price": event.bos.break_price,
                    "created_at": event.bos.created_at.isoformat(),
                }
            )
        elif isinstance(event, LiquiditySweepEvent):
            actual["sweep"].append(
                {
                    "sweep_type": event.sweep_type,
                    "price_level": event.swept_swing.price_level,
                    "sweep_at": event.sweep_candle.timestamp.isoformat(),
                }
            )

    return actual


@dataclass
class CategoryScore:
    category: str
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _match_category(
    actual: List[dict],
    expected: List[dict],
    time_field: str,
    match_fields: List[str],
    price_field: Optional[str] = None,
    price_tolerance: float = 0.0,
) -> Tuple[int, int, int]:
    """Greedy one-to-one matching: an expected label is satisfied by the
    first not-yet-claimed actual detection with the same timestamp, the
    same value on every field in `match_fields`, and (if `price_field` is
    given) a price within `price_tolerance`.
    """
    matched_actual = set()
    matched_expected = set()

    for ei, exp in enumerate(expected):
        for ai, act in enumerate(actual):
            if ai in matched_actual:
                continue
            if act[time_field] != exp[time_field]:
                continue
            if any(act.get(field) != exp.get(field) for field in match_fields):
                continue
            if price_field is not None and abs(act[price_field] - exp[price_field]) > price_tolerance:
                continue
            matched_actual.add(ai)
            matched_expected.add(ei)
            break

    tp = len(matched_expected)
    fp = len(actual) - len(matched_actual)
    fn = len(expected) - len(matched_expected)
    return tp, fp, fn


CATEGORY_MATCH_RULES = {
    "swing": dict(time_field="confirmed_at", match_fields=["swing_type"], price_field="price_level"),
    "fvg": dict(time_field="created_at", match_fields=["direction"], price_field="low"),
    "bos": dict(time_field="created_at", match_fields=["direction"], price_field="break_price"),
    "choch": dict(time_field="created_at", match_fields=["new_bias"], price_field="break_price"),
    "sweep": dict(time_field="sweep_at", match_fields=["sweep_type"], price_field="price_level"),
}


def run_validation(
    candles: List[Candle],
    labels: dict,
    price_tolerance: float = 0.0,
) -> Dict[str, CategoryScore]:
    """Section 9: run the engine over `candles`, compare its actual output
    against `labels["labels"]`, and return per-concept precision/recall/F1.
    """
    tick_size = labels.get("tick_size", 0.0001)
    _, results = replay(
        candles,
        symbol=labels["symbol"],
        timeframe=labels["timeframe"],
        tick_size=tick_size,
    )
    all_events = [event for result in results for event in result.events]
    actual = _extract_actual(all_events)
    expected = labels.get("labels", {})

    scores: Dict[str, CategoryScore] = {}
    for category, rule in CATEGORY_MATCH_RULES.items():
        tp, fp, fn = _match_category(
            actual.get(category, []),
            expected.get(category, []),
            price_tolerance=price_tolerance,
            **rule,
        )
        scores[category] = CategoryScore(category, tp, fp, fn)
    return scores


def compare_to_baseline(current: Dict[str, CategoryScore], baseline: dict) -> List[str]:
    """Section 9.3 regression suite: flag any category whose precision
    dropped by more than REGRESSION_DROP_THRESHOLD versus the baseline run.
    """
    regressions = []
    for category, score in current.items():
        prior = baseline.get(category, {}).get("precision")
        if prior is None:
            continue
        drop = prior - score.precision
        if drop > REGRESSION_DROP_THRESHOLD:
            regressions.append(
                f"{category}: precision dropped {drop:.1%} (baseline {prior:.1%} -> now {score.precision:.1%})"
            )
    return regressions


def _print_report(scores: Dict[str, CategoryScore]) -> bool:
    all_passed = True
    print(f"{'Category':<10} {'TP':>4} {'FP':>4} {'FN':>4} {'Precision':>10} {'Recall':>8} {'F1':>8} {'Threshold':>10} {'Result':>8}")
    for category, score in scores.items():
        threshold = VALIDATION_THRESHOLDS[category]
        passed = score.precision >= threshold
        all_passed = all_passed and passed
        print(
            f"{category:<10} {score.true_positives:>4} {score.false_positives:>4} {score.false_negatives:>4} "
            f"{score.precision:>10.1%} {score.recall:>8.1%} {score.f1:>8.1%} {threshold:>10.0%} "
            f"{'PASS' if passed else 'FAIL':>8}"
        )
    return all_passed


def _scores_to_dict(scores: Dict[str, CategoryScore]) -> dict:
    return {
        category: {
            "true_positives": s.true_positives,
            "false_positives": s.false_positives,
            "false_negatives": s.false_negatives,
            "precision": s.precision,
            "recall": s.recall,
            "f1": s.f1,
        }
        for category, s in scores.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1 Section 9 validation harness")
    parser.add_argument("candles", help="Path to candles.json")
    parser.add_argument("labels", help="Path to labels.json")
    parser.add_argument("--price-tolerance", type=float, default=0.0, help="Allowed price difference for a match")
    parser.add_argument("--save", help="Write per-category results to this JSON path")
    parser.add_argument("--baseline", help="Compare against a previous --save output; flag >2%% precision drops")
    args = parser.parse_args()

    candles = load_candles(args.candles)
    labels = load_labels(args.labels)

    scores = run_validation(candles, labels, price_tolerance=args.price_tolerance)
    all_passed = _print_report(scores)

    if args.baseline:
        with open(args.baseline, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        regressions = compare_to_baseline(scores, baseline)
        if regressions:
            print("\nRegressions vs baseline:")
            for r in regressions:
                print(f"  - {r}")
            all_passed = False

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(_scores_to_dict(scores), f, indent=2)
        print(f"\nResults saved to {args.save}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
