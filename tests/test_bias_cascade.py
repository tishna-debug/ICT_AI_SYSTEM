from engine.rules.base import KillZoneEvent
from engine.rules.bias_cascade import (
    FALLBACK_BIAS_TIMEFRAMES,
    PRIMARY_BIAS_TIMEFRAMES,
    evaluate_bias_cascade,
    is_setup_eligible_for_ai,
)
from engine.rules.bos import TrendState


def _trend_states(**tf_to_trend) -> dict:
    return {tf: TrendState(symbol="TEST", timeframe=tf, current_trend=trend) for tf, trend in tf_to_trend.items()}


def test_primary_alignment_gives_full_confidence():
    states = _trend_states(D="BULLISH", H4="BULLISH", H1="BULLISH", M15="BULLISH")
    event = evaluate_bias_cascade(states)
    assert event.bias == "BULLISH"
    assert event.confidence == "FULL"
    assert event.timeframes_used == PRIMARY_BIAS_TIMEFRAMES


def test_fallback_used_when_h4_disagrees():
    states = _trend_states(D="BEARISH", H4="BULLISH", H1="BEARISH", M15="BEARISH")
    event = evaluate_bias_cascade(states)
    assert event.bias == "BEARISH"
    assert event.confidence == "REDUCED"
    assert event.timeframes_used == FALLBACK_BIAS_TIMEFRAMES


def test_no_bias_when_fallback_also_disagrees():
    states = _trend_states(D="BULLISH", H4="BULLISH", H1="BEARISH", M15="BEARISH")
    event = evaluate_bias_cascade(states)
    assert event.bias is None
    assert event.confidence is None


def test_missing_timeframe_treated_as_undefined_not_a_crash():
    states = _trend_states(D="BULLISH", H1="BULLISH", M15="BULLISH")  # H4 missing entirely
    event = evaluate_bias_cascade(states)
    # primary fails (H4 undefined), fallback (D/H1/M15) all bullish -> REDUCED
    assert event.bias == "BULLISH"
    assert event.confidence == "REDUCED"


def test_all_undefined_gives_no_bias():
    event = evaluate_bias_cascade({})
    assert event.bias is None
    assert event.confidence is None


def test_eligible_requires_matching_direction_and_kill_zone():
    bias = evaluate_bias_cascade(_trend_states(D="BULLISH", H4="BULLISH", H1="BULLISH", M15="BULLISH"))
    in_kz = KillZoneEvent(timestamp=None, in_kill_zone=True, in_hot_window=False, session="NY")
    out_kz = KillZoneEvent(timestamp=None, in_kill_zone=False, in_hot_window=False, session="NONE")

    assert is_setup_eligible_for_ai("bullish", bias, in_kz) is True
    assert is_setup_eligible_for_ai("bearish", bias, in_kz) is False  # wrong direction
    assert is_setup_eligible_for_ai("bullish", bias, out_kz) is False  # outside kill zone


def test_eligible_false_when_no_bias():
    no_bias = evaluate_bias_cascade({})
    in_kz = KillZoneEvent(timestamp=None, in_kill_zone=True, in_hot_window=False, session="NY")
    assert is_setup_eligible_for_ai("bullish", no_bias, in_kz) is False
