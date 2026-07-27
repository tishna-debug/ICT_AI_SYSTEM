"""
Tests for engine/context_layer.py. Never hits the real FMP API - the
transport is always injected, matching every other integration module in
this project.
"""

from datetime import datetime, timedelta, timezone

import engine.context_layer as context_layer
from engine.context_layer import (
    ContextLayerProvider,
    NewsContext,
    SentimentContext,
    build_context_summary,
    classify_volatility,
    detect_fomo_risk,
    get_fear_greed_index,
    score_headline_sentiment,
)


def test_classify_volatility_buckets():
    assert classify_volatility(3.0, 1.0) == "EXTREME"
    assert classify_volatility(1.6, 1.0) == "HIGH"
    assert classify_volatility(1.0, 1.0) == "NORMAL"
    assert classify_volatility(0.4, 1.0) == "LOW"
    assert classify_volatility(None, 1.0) == "UNKNOWN"
    assert classify_volatility(1.0, None) == "UNKNOWN"
    assert classify_volatility(1.0, 0) == "UNKNOWN"


def test_score_headline_sentiment_bullish_bearish_neutral():
    assert score_headline_sentiment([]).label == "NEUTRAL"

    bullish = score_headline_sentiment(["Stocks rally as tech surges to record high"])
    assert bullish.label == "BULLISH"
    assert bullish.score > 0

    bearish = score_headline_sentiment(["Markets crash amid recession fears, selloff deepens"])
    assert bearish.label == "BEARISH"
    assert bearish.score < 0

    neutral = score_headline_sentiment(["Company announces quarterly meeting schedule"])
    assert neutral.label == "NEUTRAL"
    assert neutral.score == 0.0


def test_get_fear_greed_index_always_none():
    assert get_fear_greed_index() is None


def test_detect_fomo_risk_needs_two_of_three_factors(mk_candle):
    # flat, low-volume candles - no factors present
    candles = [mk_candle(i, 100, 100.5, 99.5, 100) for i in range(10)]
    result = detect_fomo_risk(candles, atr14=1.0)
    assert result.is_fomo_risk is False
    assert result.factors == []


def test_detect_fomo_risk_flags_on_extension_and_volume_spike(mk_candle):
    candles = [mk_candle(i, 100, 100.5, 99.5, 100) for i in range(9)]
    # final candle: big directional move (>2.5x ATR over lookback) + volume spike
    spike = mk_candle(9, 100, 120, 99, 119)
    spike.volume = 1000
    candles.append(spike)

    result = detect_fomo_risk(candles, atr14=1.0)
    assert result.is_fomo_risk is True
    assert len(result.factors) >= 2


def test_detect_fomo_risk_counts_sentiment_extreme(mk_candle):
    candles = [mk_candle(i, 100, 100.5, 99.5, 100) for i in range(9)]
    spike = mk_candle(9, 100, 120, 99, 119)
    candles.append(spike)  # extension only, no volume spike

    extreme_sentiment = SentimentContext(score=0.9, label="BULLISH", sample_size=5)
    result = detect_fomo_risk(candles, atr14=1.0, sentiment=extreme_sentiment)
    assert result.is_fomo_risk is True
    assert any("sentiment" in f for f in result.factors)


def test_context_layer_not_configured_returns_empty_context(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setattr(context_layer, "load_dotenv", lambda *a, **k: None)
    provider = ContextLayerProvider(api_key=None, transport=lambda url: {})

    assert provider.is_configured() is False
    news = provider.get_news_context()
    assert news.headlines == []
    assert news.upcoming_high_impact == []


def test_context_layer_parses_headlines_and_high_impact_events():
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(minutes=30)).isoformat()

    def fake_transport(url):
        if "stock_news" in url:
            return [{"title": "Stocks rally on strong earnings"}, {"no_title_field": True}, {"title": ""}]
        if "economic_calendar" in url:
            return [
                {"event": "Fed Rate Decision", "country": "US", "impact": "High", "date": soon},
                {"event": "Minor report", "country": "US", "impact": "Low", "date": soon},
                {"event": "Foreign event", "country": "DE", "impact": "High", "date": soon},
            ]
        return {}

    provider = ContextLayerProvider(api_key="fake-key", transport=fake_transport)
    news = provider.get_news_context()

    assert news.headlines == ["Stocks rally on strong earnings"]
    assert news.has_high_impact_soon is True
    assert len(news.upcoming_high_impact) == 1
    assert news.upcoming_high_impact[0].event == "Fed Rate Decision"


def test_context_layer_handles_transport_failure_gracefully():
    def boom(url):
        raise RuntimeError("network down")

    provider = ContextLayerProvider(api_key="fake-key", transport=boom)
    news = provider.get_news_context()  # should not raise
    assert news.headlines == []
    assert news.upcoming_high_impact == []


def test_get_sentiment_context_derives_from_news_headlines():
    provider = ContextLayerProvider(
        api_key="fake-key", transport=lambda url: [{"title": "Rally continues as markets surge"}] if "stock_news" in url else []
    )
    sentiment = provider.get_sentiment_context()
    assert sentiment.label == "BULLISH"


def test_build_context_summary_includes_all_pieces():
    news = NewsContext(upcoming_high_impact=[], headlines=["irrelevant"])
    sentiment = SentimentContext(score=0.0, label="NEUTRAL", sample_size=1)
    from engine.context_layer import FOMORiskResult

    fomo = FOMORiskResult(is_fomo_risk=False, factors=[])

    summary = build_context_summary("NORMAL", news, sentiment, None, fomo)
    assert "Volatility: NORMAL" in summary
    assert "No high-impact" in summary
    assert "NEUTRAL" in summary
    assert "not available" in summary
    assert "No FOMO risk" in summary
