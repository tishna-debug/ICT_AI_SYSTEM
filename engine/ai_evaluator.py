"""
engine/ai_evaluator.py

Build Step 3: turns one confirmed, Kill-Zone-aligned, HTF-bias-confirmed
setup into a Buy/Sell/No-Trade verdict with written reasoning, via the
Claude API. Should only ever be called on setups that already passed
engine.rules.bias_cascade.is_setup_eligible_for_ai() - never on every
candle - per the Master Doc's "Claude API called only on confirmed
setups" cost-control rule (target ~$5-15/month).

Advisory only: this module NEVER places, modifies, or closes a trade. It
only produces a written recommendation for a human to read and act on (or
not) themselves.

Per CLAUDE.md's graceful degradation rule: a missing API key, a network
error, or an unparseable response must never crash the rest of the
system. evaluate() never raises - every failure mode falls back to a
NO_TRADE verdict that explains what went wrong, and gets logged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from dotenv import load_dotenv

from engine.event_narration import describe_event
from engine.logging_config import get_logger

logger = get_logger("ai_evaluator")

DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024

SYSTEM_PROMPT = """You are the reasoning layer of an advisory-only ICT (Inner Circle Trader) \
trading system. You NEVER place trades - you only recommend one of BUY, SELL, or NO_TRADE, \
with reasoning a human trader can evaluate before deciding whether to act.

Rules:
- Base your verdict ONLY on the structural evidence provided (the detected setup, current \
  trend, active zones, and Kill Zone / HTF bias context). Do not invent price action that \
  wasn't given to you.
- Cite the SPECIFIC rule(s) that fired (e.g. "bullish FVG created + BOS confirmed off a \
  MAJOR swing") - never give a vague or generic justification.
- If the evidence is mixed, contradictory, or thin, say NO_TRADE rather than guessing.
- Keep the reasoning concise (3-6 sentences), in plain English a non-technical trader can \
  follow.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{"verdict": "BUY" | "SELL" | "NO_TRADE", "confidence": "HIGH" | "MEDIUM" | "LOW", "reasoning": "..."}
"""


@dataclass
class Verdict:
    verdict: str            # "BUY" | "SELL" | "NO_TRADE"
    confidence: str          # "HIGH" | "MEDIUM" | "LOW"
    reasoning: str
    symbol: str
    timeframe: str
    triggered_by: str        # plain-English description of the event that triggered this call
    created_at: datetime
    event_type: str = "AI_VERDICT"


def _default_transport(prompt: str, api_key: str, model: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _build_prompt(setup_description: str, structure_summary: str, bias_summary: str) -> str:
    return (
        f"Detected setup:\n{setup_description}\n\n"
        f"Current market structure:\n{structure_summary or '(none provided)'}\n\n"
        f"HTF bias / Kill Zone context:\n{bias_summary or '(none provided)'}\n\n"
        "Give your verdict now."
    )


def _no_trade_fallback(symbol: str, timeframe: str, triggered_by: str, reason: str) -> Verdict:
    return Verdict(
        verdict="NO_TRADE",
        confidence="LOW",
        reasoning=reason,
        symbol=symbol,
        timeframe=timeframe,
        triggered_by=triggered_by,
        created_at=datetime.now(timezone.utc),
    )


class AIEvaluator:
    """Calls Claude to turn a confirmed setup into a verdict.

    `transport` defaults to the real Anthropic API call but can be
    swapped out in tests, same pattern as MT5CandleFeed's fetch_fn and
    TelegramNotifier's transport.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        transport: Optional[Callable[[str, str, str], str]] = None,
    ):
        load_dotenv()
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self._transport = transport or _default_transport

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def evaluate(
        self,
        event: object,
        symbol: str,
        timeframe: str,
        structure_summary: str = "",
        bias_summary: str = "",
    ) -> Verdict:
        """Turn one confirmed setup into a Buy/Sell/No-Trade verdict with
        reasoning. Never raises.
        """
        setup_description = describe_event(event)

        if not self.is_configured():
            logger.error("Cannot get an AI verdict - ANTHROPIC_API_KEY is missing from .env.")
            return _no_trade_fallback(
                symbol, timeframe, setup_description, "AI evaluator not configured (missing API key) - defaulting to NO_TRADE."
            )

        prompt = _build_prompt(setup_description, structure_summary, bias_summary)

        try:
            raw = self._transport(prompt, self.api_key, self.model)
        except Exception:
            logger.exception("AI verdict call failed (network or API error).")
            return _no_trade_fallback(
                symbol, timeframe, setup_description, "AI call failed - defaulting to NO_TRADE. See logs/ai_evaluator.log."
            )

        try:
            parsed = json.loads(raw)
            verdict = str(parsed["verdict"]).upper()
            confidence = str(parsed["confidence"]).upper()
            reasoning = str(parsed["reasoning"])
        except Exception:
            logger.error(f"Could not parse AI response as the expected JSON shape: {raw!r}")
            return _no_trade_fallback(
                symbol, timeframe, setup_description, "AI response wasn't in the expected format - defaulting to NO_TRADE."
            )

        if verdict not in ("BUY", "SELL", "NO_TRADE"):
            logger.error(f"AI returned an unrecognized verdict: {verdict!r}")
            return _no_trade_fallback(
                symbol, timeframe, setup_description, f"AI returned an unrecognized verdict ({verdict!r}) - defaulting to NO_TRADE."
            )
        if confidence not in ("HIGH", "MEDIUM", "LOW"):
            confidence = "LOW"

        return Verdict(
            verdict=verdict,
            confidence=confidence,
            reasoning=reasoning,
            symbol=symbol,
            timeframe=timeframe,
            triggered_by=setup_description,
            created_at=datetime.now(timezone.utc),
        )


def log_verdict(verdict: Verdict, path: str = "data/verdicts.json") -> None:
    """Appends one verdict to the JSON log (Master Doc: data/verdicts.json
    - "Claude AI BUY/SELL/NO TRADE reasoning logs"). Plain JSON file, no
    database, per the Master Doc's data storage policy.
    """
    record = {
        "verdict": verdict.verdict,
        "confidence": verdict.confidence,
        "reasoning": verdict.reasoning,
        "symbol": verdict.symbol,
        "timeframe": verdict.timeframe,
        "triggered_by": verdict.triggered_by,
        "created_at": verdict.created_at.isoformat(),
    }

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            records = json.loads(content) if content else []
    except FileNotFoundError:
        records = []

    records.append(record)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
