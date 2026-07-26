"""
engine/event_bus.py

Phase 1, Step 10 of the ICT Engineering Rulebook build order:
  Step 10 - Event bus (synchronous first)

Not an ICT concept, so it doesn't live in engine/rules/ (which the Master
Doc reserves for "one file per ICT PD array concept"). Every event
dataclass across engine/rules/ already carries a canonical `event_type`
string tag (e.g. "FVG_CREATED", "BOS_CONFIRMED") purely so it can be used
as a dispatch key - that's what this module does with it.

Synchronous by design (per the rulebook's own phrasing, "synchronous
first"): publish() calls handlers in-process, in registration order, and
propagates the first handler exception rather than swallowing it. An async
version is a future decision, not a default.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List

Handler = Callable[[object], None]


class EventBus:
    """A minimal synchronous pub/sub bus keyed on `event.event_type`."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Handler]] = {}
        self._wildcard_subscribers: List[Handler] = []

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Register `handler` to be called for every event whose
        `event_type` equals `event_type` (e.g. "FVG_MITIGATED").
        """
        self._subscribers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """Register `handler` to be called for every event, regardless of
        `event_type`.
        """
        self._wildcard_subscribers.append(handler)

    def publish(self, event: object) -> None:
        """Dispatch a single event to its type-specific subscribers, then
        to the wildcard subscribers.
        """
        for handler in self._subscribers.get(getattr(event, "event_type", None), []):
            handler(event)
        for handler in self._wildcard_subscribers:
            handler(event)

    def publish_many(self, events: Iterable[object]) -> None:
        for event in events:
            self.publish(event)
