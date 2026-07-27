"""
engine/event_narration.py

Turns the raw event objects produced by engine.rules.structure_state into
one-line, plain-English descriptions. Shared by scripts/demo_run.py and
scripts/watch_live.py so both print things the same, readable way -
nothing ICT-jargon-only, per CLAUDE.md's "plain language" communication
rule.
"""

from __future__ import annotations

from engine.rules.bos import BOSEvent
from engine.rules.choch import CHOCHEvent
from engine.rules.fvg import FVGCreatedEvent, FVGMitigatedEvent
from engine.rules.liquidity_sweep import LiquiditySweepEvent
from engine.rules.swings import SwingPointEvent


def describe_event(event: object) -> str:
    if isinstance(event, SwingPointEvent):
        ts = event.confirmed_at
        return (
            f"[{ts:%H:%M}] Swing {event.swing_type} confirmed at {event.price_level:.2f} "
            f"({event.degree}, strength {event.strength})"
        )
    if isinstance(event, FVGCreatedEvent):
        fvg = event.fvg
        ts = fvg.created_at
        return f"[{ts:%H:%M}] {fvg.direction.upper()} Fair Value Gap created: {fvg.low:.2f} - {fvg.high:.2f}"
    if isinstance(event, FVGMitigatedEvent):
        ts = event.mitigation_candle.timestamp
        return f"[{ts:%H:%M}] Fair Value Gap {event.mitigation_type} mitigation (price revisited the gap)"
    if isinstance(event, CHOCHEvent):
        ts = event.bos.created_at
        return (
            f"[{ts:%H:%M}] CHANGE OF CHARACTER - trend flips to {event.new_bias} "
            f"at {event.bos.break_price:.2f} (confidence: {event.confidence})"
        )
    if isinstance(event, BOSEvent):
        ts = event.bos.created_at
        return f"[{ts:%H:%M}] Break of Structure - {event.bos.direction.upper()} continuation at {event.bos.break_price:.2f}"
    if isinstance(event, LiquiditySweepEvent):
        ts = event.sweep_candle.timestamp
        return f"[{ts:%H:%M}] Liquidity Sweep ({event.sweep_class}) at {event.swept_swing.price_level:.2f}"
    return f"Unrecognized event: {event}"
