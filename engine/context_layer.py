"""
engine/context_layer.py

Build Step 4: the Context Layer (Master Doc Section 5) - factors beyond
raw price action that can downgrade a technically-valid setup to
No-Trade, or add color to the AI's reasoning. Feeds into
engine/ai_evaluator.py's verdict prompt as an additional summary string,
the same pattern as structure_summary/bias_summary in main.py.

Provider choices (owner's decision):
- News + economic calendar: Financial Modeling Prep (FMP) free tier.
  Sign up at https://financialmodelingprep.com, add FMP_API_KEY to .env.
  NOTE: FMP's free-tier limits/endpoints have changed over time in the
  past and may change again - if a call here starts failing with a 401
  or 403, check your FMP dashboard for what's actually included in your
  current plan. Every failure here degrades gracefully (empty context),
  it never crashes the rest of the system.
- Sentiment: derived from the same FMP headlines via simple bullish/
  bearish keyword scoring - deliberately not a real NLP model, and not a
  second API/signup.
- Fear & Greed: explicitly skipped (owner's decision - no reliable free
  official API for the US equity index version, unlike crypto).
  get_fear_greed_index() always returns None. The rulebook itself says
  this factor is "contextual, not a hard veto," so a permanently-None
  value degrades gracefully by design, not as a workaround.

Volatility state and the FOMO heuristic need no external provider at all
- both are derived from price data already flowing through the engine.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from dotenv import load_dotenv

from engine.logging_config import get_logger
from engine.rules.base import Candle

logger = get_logger("context_layer")

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
REQUEST_TIMEOUT_SECONDS = 10

# Volatility state thresholds (ratio of current ATR14 to the
# ATR_BASELINE_PERIOD rolling average - the same baseline Addendum A's
# FVG confidence scoring already uses).
VOLATILITY_EXTREME_RATIO = 2.0
VOLATILITY_HIGH_RATIO = 1.5
VOLATILITY_LOW_RATIO = 0.5

# FOMO heuristic thresholds (Section 5: "rapid extension + volume spike +
# sentiment extreme together")
FOMO_EXTENSION_ATR_MULTIPLE = 2.5   # price moved this many ATRs over the lookback window
FOMO_EXTENSION_LOOKBACK = 6         # candles back to measure the move from
FOMO_VOLUME_SPIKE_RATIO = 2.0       # candle volume vs recent average volume
FOMO_SENTIMENT_EXTREME_THRESHOLD = 0.6  # abs(sentiment.score) at/above this counts as "extreme"

# Deliberately basic keyword lists for headline sentiment scoring - a real
# NLP sentiment model is future scope, not this build step's job.
BULLISH_KEYWORDS = [
    "rally", "surge", "soar", "beat expectations", "beats estimates", "upgrade", "bullish",
    "record high", "strong growth", "outperform", "rebound", "optimis",
]
BEARISH_KEYWORDS = [
    "crash", "plunge", "selloff", "sell-off", "miss expectations", "misses estimates",
    "downgrade", "bearish", "record low", "recession", "underperform", "slump", "pessimis",
]


@dataclass
class NewsEvent:
    event: str
    country: str
    impact: str  # "Low" | "Medium" | "High"
    date: datetime


@dataclass
class NewsContext:
    upcoming_high_impact: List[NewsEvent] = field(default_factory=list)
    headlines: List[str] = field(default_factory=list)

    @property
    def has_high_impact_soon(self) -> bool:
        return len(self.upcoming_high_impact) > 0


@dataclass
class SentimentContext:
    score: float   # -1.0 (very bearish) to +1.0 (very bullish)
    label: str      # "BULLISH" | "BEARISH" | "NEUTRAL"
    sample_size: int


@dataclass
class FOMORiskResult:
    is_fomo_risk: bool
    factors: List[str]


def classify_volatility(atr14: Optional[float], atr_baseline: Optional[float]) -> str:
    """Section 5: "Volatility state - derived from live price data (no
    extra cost)." Ratio of current ATR(14) to the rolling baseline.
    """
    if not atr14 or not atr_baseline:
        return "UNKNOWN"
    ratio = atr14 / atr_baseline
    if ratio >= VOLATILITY_EXTREME_RATIO:
        return "EXTREME"
    if ratio >= VOLATILITY_HIGH_RATIO:
        return "HIGH"
    if ratio <= VOLATILITY_LOW_RATIO:
        return "LOW"
    return "NORMAL"


def detect_fomo_risk(
    candles: List[Candle],
    atr14: Optional[float],
    sentiment: Optional[SentimentContext] = None,
) -> FOMORiskResult:
    """Section 5: "FOMO/crowd behavior risk - rapid extension + volume
    spike + sentiment extreme together." `sentiment` is optional - without
    it, this can still flag on extension + volume alone (two of three
    factors); it just can't confirm the strongest "all three aligned" case.
    Flags as FOMO risk once at least 2 of the 3 factors are present.
    """
    factors: List[str] = []

    if len(candles) >= FOMO_EXTENSION_LOOKBACK + 1 and atr14:
        recent = candles[-1]
        reference = candles[-(FOMO_EXTENSION_LOOKBACK + 1)]
        move = abs(recent.close - reference.close)
        if move >= atr14 * FOMO_EXTENSION_ATR_MULTIPLE:
            factors.append(f"rapid extension ({move:.2f} over {FOMO_EXTENSION_LOOKBACK} candles, {move / atr14:.1f}x ATR)")

    if len(candles) >= 2:
        window = candles[-21:-1]
        recent_volume = candles[-1].volume
        avg_volume = sum(c.volume for c in window) / len(window) if window else 0
        if avg_volume > 0 and recent_volume >= avg_volume * FOMO_VOLUME_SPIKE_RATIO:
            factors.append(f"volume spike ({recent_volume:.0f} vs {avg_volume:.0f} avg)")

    if sentiment is not None and abs(sentiment.score) >= FOMO_SENTIMENT_EXTREME_THRESHOLD:
        factors.append(f"sentiment extreme ({sentiment.label}, score {sentiment.score:.2f})")

    return FOMORiskResult(is_fomo_risk=len(factors) >= 2, factors=factors)


def score_headline_sentiment(headlines: List[str]) -> SentimentContext:
    """Deliberately simple bullish/bearish keyword scoring over recent
    headlines. Good enough as a directional signal for the AI's reasoning
    (Section 5: "contributes to reasoning, not a hard veto"), not meant
    to be precise.
    """
    if not headlines:
        return SentimentContext(score=0.0, label="NEUTRAL", sample_size=0)

    bull_hits = 0
    bear_hits = 0
    for headline in headlines:
        lower = headline.lower()
        bull_hits += sum(1 for kw in BULLISH_KEYWORDS if kw in lower)
        bear_hits += sum(1 for kw in BEARISH_KEYWORDS if kw in lower)

    total = bull_hits + bear_hits
    score = 0.0 if total == 0 else (bull_hits - bear_hits) / total
    label = "NEUTRAL"
    if score >= 0.2:
        label = "BULLISH"
    elif score <= -0.2:
        label = "BEARISH"

    return SentimentContext(score=round(score, 2), label=label, sample_size=len(headlines))


def get_fear_greed_index() -> Optional[str]:
    """Explicitly not implemented - see module docstring. Always returns
    None; callers must already treat a missing reading as "no data,"
    matching the rulebook's "contextual, not a hard veto" framing.
    """
    return None


def _default_transport(url: str) -> object:
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


class ContextLayerProvider:
    """Fetches news + economic calendar from FMP and derives sentiment
    from the same headlines. `transport` defaults to the real HTTP call
    but can be swapped out in tests, same pattern as every other
    integration module in this project (MT5CandleFeed, TelegramNotifier,
    AIEvaluator).
    """

    def __init__(self, api_key: Optional[str] = None, transport: Optional[Callable[[str], object]] = None):
        load_dotenv()
        self.api_key = api_key or os.environ.get("FMP_API_KEY")
        self._transport = transport or _default_transport

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def get_news_context(self, high_impact_window_hours: float = 1.0, headline_limit: int = 20) -> NewsContext:
        if not self.is_configured():
            logger.warning("FMP_API_KEY missing - news context unavailable.")
            return NewsContext()

        headlines: List[str] = []
        upcoming: List[NewsEvent] = []

        try:
            news_url = f"{FMP_BASE_URL}/stock_news?limit={headline_limit}&apikey={self.api_key}"
            news_data = self._transport(news_url)
            headlines = [item.get("title", "") for item in news_data if item.get("title")]
        except Exception:
            logger.exception("Failed to fetch news headlines from FMP.")

        try:
            today = datetime.now(timezone.utc).date().isoformat()
            calendar_url = f"{FMP_BASE_URL}/economic_calendar?from={today}&to={today}&apikey={self.api_key}"
            calendar_data = self._transport(calendar_url)
            now = datetime.now(timezone.utc)
            window_end = now + timedelta(hours=high_impact_window_hours)
            for item in calendar_data:
                if item.get("impact") != "High" or item.get("country") != "US":
                    continue
                try:
                    event_time = datetime.fromisoformat(item["date"]).replace(tzinfo=timezone.utc)
                except (KeyError, ValueError, TypeError):
                    continue
                if now <= event_time <= window_end:
                    upcoming.append(
                        NewsEvent(
                            event=item.get("event", "Unknown"),
                            country=item.get("country", ""),
                            impact=item.get("impact", ""),
                            date=event_time,
                        )
                    )
        except Exception:
            logger.exception("Failed to fetch economic calendar from FMP.")

        return NewsContext(upcoming_high_impact=upcoming, headlines=headlines)

    def get_sentiment_context(self, news_context: Optional[NewsContext] = None) -> SentimentContext:
        news_context = news_context if news_context is not None else self.get_news_context()
        return score_headline_sentiment(news_context.headlines)


def build_context_summary(
    volatility: str,
    news: NewsContext,
    sentiment: SentimentContext,
    fear_greed: Optional[str],
    fomo: FOMORiskResult,
) -> str:
    """Plain-English summary for the AI verdict prompt, same pattern as
    main.py's build_structure_summary/build_bias_summary.
    """
    parts = [f"Volatility: {volatility}."]

    if news.has_high_impact_soon:
        events = ", ".join(e.event for e in news.upcoming_high_impact)
        parts.append(f"HIGH-IMPACT NEWS within the hour: {events}. Weigh this heavily toward caution.")
    else:
        parts.append("No high-impact US economic news in the next hour.")

    parts.append(f"News sentiment: {sentiment.label} (score {sentiment.score:.2f}, {sentiment.sample_size} headlines).")
    parts.append(f"Fear & Greed: {fear_greed if fear_greed else 'not available'}.")

    if fomo.is_fomo_risk:
        parts.append(f"FOMO RISK flagged: {'; '.join(fomo.factors)}.")
    else:
        parts.append("No FOMO risk flagged.")

    return " ".join(parts)
