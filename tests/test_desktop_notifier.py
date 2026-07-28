"""
Tests for engine/desktop_notifier.py. Never fires a real Windows toast -
the transport is always injected, matching every other integration
module in this project.
"""

from datetime import datetime, timezone

from engine.ai_evaluator import Verdict
from engine.desktop_notifier import MAX_BODY_LENGTH, DesktopNotifier


def _sample_verdict(reasoning="Clean bullish BOS off a major swing.") -> Verdict:
    return Verdict(
        verdict="BUY",
        confidence="HIGH",
        reasoning=reasoning,
        symbol="USTEC",
        timeframe="M5",
        triggered_by="[14:00] Break of Structure - BULLISH continuation at 28500.00",
        created_at=datetime.now(timezone.utc),
    )


def test_notify_calls_transport_with_title_and_body():
    calls = []
    notifier = DesktopNotifier(transport=lambda title, body: calls.append((title, body)))

    result = notifier.notify("Title", "Body")

    assert result is True
    assert calls == [("Title", "Body")]


def test_notify_disabled_skips_transport():
    calls = []
    notifier = DesktopNotifier(transport=lambda title, body: calls.append((title, body)), enabled=False)

    result = notifier.notify("Title", "Body")

    assert result is False
    assert calls == []


def test_notify_handles_transport_exception_without_raising():
    def boom(title, body):
        raise RuntimeError("WinRT not available")

    notifier = DesktopNotifier(transport=boom)
    result = notifier.notify("Title", "Body")

    assert result is False  # should not raise


def test_notify_verdict_builds_expected_title():
    calls = []
    notifier = DesktopNotifier(transport=lambda title, body: calls.append((title, body)))

    notifier.notify_verdict(_sample_verdict())

    title, body = calls[0]
    assert title == "BUY - USTEC M5 (HIGH)"
    assert body == "Clean bullish BOS off a major swing."


def test_notify_verdict_truncates_long_reasoning():
    long_reasoning = "x" * 500
    calls = []
    notifier = DesktopNotifier(transport=lambda title, body: calls.append((title, body)))

    notifier.notify_verdict(_sample_verdict(reasoning=long_reasoning))

    _, body = calls[0]
    assert len(body) == MAX_BODY_LENGTH
    assert body.endswith("...")
