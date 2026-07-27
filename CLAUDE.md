# CLAUDE.md — Project Memory for Claude Code

This file is read automatically at the start of every Claude Code session in this folder. It contains everything needed to build this project correctly, from scratch, without the owner re-explaining anything.

---

## 0. Who you're working with

The owner is **non-technical** — does not write or debug code, does not know Python, does not manage servers or databases. Rules for working with them:
- Explain every step in plain language before and while doing it
- Never assume they can fix an error themselves — always fix it and explain what happened
- Always ask before creating, changing, or deleting files, and before adding any new paid tool or cost
- If a decision requires real judgment (new cost, new tool, database, auto-trading, anything not already decided below), **stop and ask** — don't decide for them

---

## 1. What this system is

An AI-assisted trading **decision-support** tool (not an auto-trader). It:
1. Watches live price action on **US100, US500, and Gold/XAU** (and similar instruments)
2. Applies strict, mathematically-defined **ICT (Inner Circle Trader)** rules to detect setups: Fair Value Gaps (FVG), Break of Structure (BOS), Change of Character (CHOCH), Liquidity Sweeps, Displacement
3. Cross-checks any candidate setup against market context: news events, volatility, sentiment, Fear & Greed, FOMO/crowd risk
4. Outputs **Buy / Sell / No Trade** with a full written reasoning trail (which rule + which context factor fired)
5. Shows everything on a local **Streamlit** dashboard and sends alerts via **Telegram**

**It never auto-executes trades.** A human places every trade, always.

---

## 2. Non-negotiable design principles

| Principle | Rule |
|---|---|
| No database | Flat JSON files only. Never introduce SQL/NoSQL without the owner's explicit sign-off. |
| Rules are mathematically strict | Every ICT concept has exact numeric conditions — never vague pattern-matching. Any rule change updates this file FIRST, then the code. |
| One file per ICT concept | Each concept (FVG, BOS, CHOCH, etc.) lives in its own file under `engine/rules/`. Never merge concepts into one file. |
| Reasoning always shown | Every verdict must be traceable to the specific rule(s) and context factor(s) that fired. No black-box outputs. |
| No auto-trading | Advisory only. Auto-execution is a major future decision requiring explicit owner approval — never a "natural extension." |
| Claude API called only on confirmed setups | Never call the AI reasoning layer on every candle — only after Python's rule layer has confirmed a valid, Kill-Zone-aligned setup. Keeps cost near $5–15/month. |
| Low-budget, low-maintenance | Prefer free/low-cost tools and the owner's own laptop over paid hosted infrastructure, unless the owner explicitly upgrades budget. |
| Owner is non-technical | Every setup step must be reducible to "double-click to start" or equivalent. No step should require the owner to write or debug code. |
| Graceful degradation | A failure in one module (Telegram down, AI call times out) must never crash the whole engine. Each module fails independently and logs the error. |
| Secrets never leave the machine | API keys live only in `.env` — never committed to git, never in backups, never hardcoded in any file. |

---

## 3. Folder structure — build exactly this

```
project/
├── config/
│   ├── settings.json          # Symbols, timeframes, Kill Zones, account risk limits
│   └── rules_config.json      # Mathematical thresholds (ATR periods, FVG fill bands, HTF rules)
├── data/
│   ├── setups.json            # Active & historic ICT setup signals
│   ├── verdicts.json          # Claude AI BUY / SELL / NO TRADE reasoning logs
│   ├── status.json            # Heartbeat file — engine health for crash detection
│   └── price_logs/            # Local OHLC cache for offline backtesting
├── engine/
│   ├── __init__.py
│   ├── mt5_bridge.py          # Live MT5 price connection & candle extraction (read-only, no trading)
│   ├── event_bus.py           # Synchronous pub/sub for engine/rules/ events
│   ├── logging_config.py      # Shared logger (writes to logs/) every module reuses
│   ├── rules/
│   │   ├── __init__.py
│   │   ├── base.py            # Candle dataclass, data quality checks, 14-ATR calc, displacement, Kill Zone filter
│   │   ├── swings.py          # Swing high/low detection
│   │   ├── fvg.py
│   │   ├── bos.py
│   │   ├── choch.py
│   │   ├── liquidity_sweep.py
│   │   ├── structure_state.py # Master StructureState assembly + snapshot/replay
│   │   └── bias_cascade.py
│   └── ai_evaluator.py        # Anthropic Claude API prompt runner & risk evaluator
├── alerts/
│   ├── __init__.py
│   └── telegram_bot.py
├── interface/
│   └── dashboard.py            # Streamlit dashboard
├── logs/                        # Rotating error/runtime logs
├── backups/                     # Automated ZIP archives — excludes .env, retention-limited
├── scripts/
│   ├── setup_environment.py   # One-click directory & file builder
│   ├── test_mt5.py             # Diagnostic script to verify MT5 connection
│   ├── demo_run.py             # Plain-English demo of the rule engine on made-up sample data
│   ├── validation_harness.py  # Section 9 precision/recall/F1 scoring against hand-labeled charts
│   └── backup_system.py       # Zips project (excluding .env), prunes old backups
├── tests/                       # pytest suite - run with `pytest`
├── requirements.txt
├── .env                         # ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN — never shared. No MT5
│                                 # credentials here: mt5_bridge.py attaches to a terminal you're
│                                 # already logged into by hand, on purpose (see Section 6 below)
├── .env.example
├── .gitignore
├── README.md
└── main.py                      # Master orchestrator
```

**Rule for extending this:** new ICT concept = new file in `engine/rules/` + new row in the ICT rules table below. New context factor = new row in the Context Layer table + logic in `ai_evaluator.py`. Never bolt something onto an unrelated file.

---

## 4. ICT Rule Layer — canonical definitions (single source of truth)

### 4.1 System constants (also mirrored in `config/rules_config.json` once built)

```python
# Displacement
MIN_DISPLACEMENT_BODY_RATIO = 0.60
MIN_DISPLACEMENT_ATR_MULTIPLIER = 1.5

# FVG
MIN_FVG_TICKS = 3
MIN_DISPLACEMENT_SCORE = 0.55
FVG_STRONG_FILL_BAND_MIN = 0.50
FVG_STRONG_FILL_BAND_MAX = 0.60
ATR_BASELINE_PERIOD = 50
FVG_HTF_WICK_EXCEPTION_TIMEFRAMES = ["M15", "M5"]
MAX_FVG_AGE_CANDLES = 50

# Swing Points
SWING_LOOKBACK = 5
MIN_SWING_STRENGTH = 2

# BOS / CHOCH
BOS_REQUIRES_CLOSE = True
MIN_BOS_DISPLACEMENT = 0.5

# Liquidity Sweep
SWEEP_WICK_RATIO = 0.30
SWEEP_RECOVERY_RATIO = 0.50

# Kill Zones (EST)
LONDON_KILL_ZONE_START = "02:00"
LONDON_KILL_ZONE_END = "05:00"
NY_KILL_ZONE_START = "08:00"
NY_KILL_ZONE_END = "11:00"
NY_HOT_WINDOW_START = "09:30"
NY_HOT_WINDOW_END = "10:00"
KILL_ZONE_MODE = "filter"   # "filter" = drop outside window; "downweight" = tag low confidence

# HTF Bias Cascade
PRIMARY_BIAS_TIMEFRAMES = ["D", "H4", "H1", "M15"]
FALLBACK_BIAS_TIMEFRAMES = ["D", "H1", "M15"]
ENTRY_TIMEFRAMES = ["M5", "M3", "M1"]
```

### 4.2 Candle
Standard OHLC + derived fields (`body`, `range`, `upper_wick`, `lower_wick`, `direction`, `body_ratio`, `mid_price`). A candle is valid only if: `high >= max(open, close)`, `low <= min(open, close)`, `high >= low`, all prices `> 0`, `volume >= 0`, timestamp not null/duplicate. Invalid candles are rejected and logged — never passed to engines.

### 4.3 Displacement
Prerequisite for FVG/BOS/CHOCH validity. A candle is displaced if: `body_ratio >= 0.60` AND `range >= ATR(14) * 1.5` AND `direction != "doji"`. Score = `(body_score * 0.6) + (range_score * 0.4)`, rounded to 4 decimals, range 0.0–1.0.

### 4.4 Swing Points
Swing High/Low confirmed by `SWING_LOOKBACK` (5) candles on each side with `MIN_SWING_STRENGTH` (2) confirming candles. Confirmed only after the lookback candles have closed to the right (detected in the past, never real-time). Invalidated when price closes beyond the level (via BOS) — but invalidated swings are retained as historical structure, never deleted.

### 4.5 Fair Value Gap (FVG)
Three-candle imbalance. Bullish: `candle[2].low > candle[0].high`, gap size `>= MIN_FVG_TICKS`, middle candle displacement score `>= 0.55`. Bearish is the mirror.

**Mitigation (canonical, unchanged from original rulebook):**
- **PARTIAL** = price trades through the gap's midpoint
- **FULL** = a candle **closes** beyond the gap's far edge (wicks never count on their own)
- **VIOLATED** = price trades fully through with momentum and closes beyond in the same direction

**Confidence merge (Addendum A) — additive only, does not change the above state machine:**
- New field: `mitigation_confidence: "NONE" | "STRONG" | "FULL"`
- STRONG tag: fill % required scales between 50–60% based on `ATR(14) / ATR_avg(50)` volatility ratio (formula: `fvg_fill_threshold()` in Addendum A1)
- **HTF wick exception:** on **M15/M5 only**, a full wick fill through the gap counts as FULL mitigation — the one documented override to "close only," scoped narrowly to these two timeframes

Expiry: age increments each untouched candle; expires after `MAX_FVG_AGE_CANDLES` (50), retained in historical record.

### 4.6 Break of Structure (BOS)
Continuation signal. Requires: prior Swing High/Low exists, **candle CLOSE beyond the level** (never wick — `BOS_REQUIRES_CLOSE = True` is final), breaking candle displacement score `>= 0.5`, and the swing has not been previously broken.

**BOS vs Sweep:** wick exceeds level but closes back inside → Liquidity Sweep, NOT a BOS. Candle closes beyond → true BOS.

### 4.7 Change of Character (CHOCH)
A BOS that occurs **against** the prevailing trend (reversal signal, vs. BOS's continuation signal). Same detection mechanism as BOS — the label depends entirely on trend context:
```python
def classify_structure_break(direction, current_trend):
    return "BOS" if direction == current_trend else "CHOCH"
```
Confidence is scored `HIGH | MEDIUM | LOW` based on: swing degree (major/minor), displacement score, whether preceded by a sweep, and HTF bias alignment.

### 4.8 Liquidity Sweep
Wick exceeds a prior swing level, closes back inside, with `upper_wick/range >= 0.30` (or lower_wick equivalent) and recovery ratio `>= 0.50`. Classified **CLEAN** (single wick, immediate close-back, recovery >0.70 — strong reversal signal) or **MESSY** (multiple candles, partial recovery — weaker, flag for review). If it later closes beyond the level, reclassify as BOS, remove from sweep detection.

**High-value combo:** Sweep + FVG created in the same 3-candle sequence → tag `SWEEP_FVG_COMBO`, confidence multiplier +0.15.

### 4.9 Kill Zone Filter
Only **London (02:00–05:00 EST)** and **New York (08:00–11:00 EST)** sessions are valid. Within NY, **09:30–10:00 EST** is the flagged high-volatility sub-window, weighted accordingly. Setups outside these windows are still detected/logged for historical record but not passed to the AI reasoning layer (`KILL_ZONE_MODE = "filter"`).

### 4.10 HTF Bias Cascade
**Primary:** bias aligned across **Daily → 4H → 1H → 15M** = full-confidence setup.
**Fallback:** if 4-way fails, drop 4H and check **Daily → 1H → 15M** — if aligned, tradeable but flagged lower-confidence ("REDUCED").
Entries are taken on **5M, 3M, or 1M** once bias (primary or fallback) is confirmed, and only if direction matches the bias AND falls within a valid Kill Zone.

### 4.11 Market Structure State
One master `StructureState` object per symbol/timeframe, updated after every candle: trend, active swing points, active/mitigated FVGs, recent BOS/CHOCH/sweeps, candle count. Must be **fully deterministic** — identical candle sequence must always produce an identical state (verified via hashing on replay).

### 4.12 Phase 2+ concepts (not yet defined — do not build yet)
Order Blocks, Breaker Blocks, Optimal Trade Entry (OTE) zones, Judas Swing, Power of Three. Each gets its own new file + a new row in this section, defined here BEFORE any code is written.

---

## 5. Context Layer (Phase 4 of build — not yet implemented)

| Factor | Source | Effect |
|---|---|---|
| News events | Free-tier financial news/economic calendar API | Flags high-impact windows; defaults to caution/No-Trade around major releases |
| Volatility state | Derived from live price data | Feeds ATR-based FVG threshold; flags abnormal volatility |
| Sentiment | Free/low-cost sentiment API | Contributes to reasoning, not a hard veto |
| Fear & Greed level | Public index (free) | Contextual input, not a hard veto |
| FOMO/crowd risk | Rapid extension + volume spike + sentiment extreme together | Flags "technically valid but high FOMO risk" |

Lives in `engine/ai_evaluator.py` — build only after the rule engine and Telegram alerts are proven (Steps 1–2 complete).

---

## 6. Build order — do not skip or reorder

1. ✅ **`engine/rules/`** — all ICT detection modules (Candle → ATR → Displacement → Swing → FVG → BOS/TrendState → CHOCH → Sweep → StructureState → event bus → replay/validation harness), plus Addendum A's Kill Zone filter and HTF Bias Cascade (`engine/rules/bias_cascade.py`). Built and tested (114 automated tests, `pytest`).
2. ✅ **`engine/mt5_bridge.py`** — live price connection. Attaches to an MT5 terminal you're already logged into by hand (no credentials stored anywhere); read-only, never places a trade. Diagnostic: `scripts/test_mt5.py`. Live watcher: `scripts/watch_live.py` (currently watching `USTEC` = US100/Nasdaq-100 on the owner's broker).
3. ✅ **`alerts/telegram_bot.py`** — sends detected signals to the owner's phone via Telegram. Uses the plain HTTP API directly (no extra package - alerts are one-way only). Credentials in `.env`. Diagnostic: `scripts/test_telegram.py`. **Blocked on the owner's network, on hold**: Telegram's servers appear blocked at the ISP level (confirmed: general internet works, `api.telegram.org` connection times out even over the owner's VPN attempt) - code is done and tested, owner has explicitly deferred chasing this further for now.
4. ✅ **`engine/ai_evaluator.py`** — turns a confirmed, eligible setup (per `bias_cascade.is_setup_eligible_for_ai`) into a Buy/Sell/No-Trade verdict with written reasoning via the Claude API. Never places a trade. Logs to `data/verdicts.json`. Diagnostic: `scripts/test_ai_evaluator.py` - **live-verified** with the owner's real API key (upgraded `anthropic` 0.34.2 → 0.120.0 in the process; 0.34.2 doesn't actually work with current `httpx`).
5. ✅ **`main.py`** — the always-on orchestrator: one `StructureStateEngine` per timeframe needed for the HTF Bias Cascade (D/H4/H1/M15) plus the entry timeframe (M5), live candles in, alert-worthy events to Telegram, eligible setups to the AI evaluator + context layer, verdicts logged and Telegraphed. Live-verified against the owner's real MT5 account (connects, warms up all 5 timeframes, polls without error) - a full live signal→AI→Telegram firing hasn't been observed yet simply because none has occurred during a test window; the decision logic itself has dedicated unit tests.
6. ✅ **`engine/context_layer.py`** — Section 5's context factors feeding `ai_evaluator.py`'s prompt. Owner's provider decisions: news + economic calendar via Financial Modeling Prep's free tier (`FMP_API_KEY`), sentiment derived from those same headlines (no second signup), Fear & Greed explicitly skipped (no reliable free official API for the US equity version). Volatility state and the FOMO heuristic need no external service. Diagnostic: `scripts/test_context_layer.py` *(not yet run live - owner still needs to sign up for FMP and add the key to `.env`)*.
7. ✅ **`interface/dashboard.py`** — local read-only Streamlit dashboard: system status (with a stale-heartbeat check - flags "RUNNING" as suspect if the heartbeat is >5 min old, since a hard crash or a laptop sleep would otherwise leave a stale "RUNNING" label unnoticed), recent AI verdicts with full reasoning, detected setups, recent log activity. Never controls `main.py`, only reads `data/`/`logs/`. Run with `streamlit run interface/dashboard.py`. Visually verified in a real browser against sample data.
8. ✅ **`scripts/backup_system.py`** — zips the project into `backups/` (timestamped, excludes `.env`/`venv/`/`.git/`, keeps the most recent 14), optional `CLOUD_BACKUP_FOLDER` for a second copy. Not in the original numbered build order but documented in Section 7/Master Doc Section 8 - built on request as a local complement to the GitHub backup (`git push`) already happening throughout. Live-verified against the real project (69 files, 0.1MB - confirms `venv/`/`.git/` really are excluded, either would be hundreds of MB otherwise).
9. **All of Phase 1 + Build Steps 1-5, plus the backup utility, are done.** Remaining work is optional/future: Phase 2 ICT concepts (Order Blocks, Breaker Blocks, OTE, Judas Swing, Power of Three - Section 4.12), expanding instruments, or a database if scale genuinely requires it.

**Gap found and fixed while building the dashboard:** `data/setups.json` ("Active & historic ICT setup signals" per this file's own Section 3 folder structure) was never actually written to anywhere - `main.py` detected and Telegraphed setups but never persisted them. Added `main.log_setup()`, wired in alongside the existing Telegram dispatch.

**Security note (fixed 2026-07-28):** `.env` was accidentally tracked in git since the very first commit (the `.gitignore` rule for it only applies to files not yet tracked). Confirmed nothing sensitive was ever actually committed (it was empty in every commit), but it's been untracked now (`git rm --cached`) so `.gitignore` actually protects it going forward. If you ever add a new secret-holding file, double check `git status` shows it as untracked before assuming `.gitignore` covers it.

### Validation benchmarks (must pass before moving to the next concept)
| Concept | Required precision | Test count |
|---|---|---|
| FVG Detection | ≥ 90% | 200 labeled examples |
| BOS Detection | ≥ 85% | 150 labeled examples |
| CHOCH Detection | ≥ 85% | 100 labeled examples |
| Swing Point Detection | ≥ 90% | 200 labeled examples |
| Liquidity Sweep | ≥ 80% | 100 labeled examples |
| Deterministic Replay | 100% | 1,000,000 candles |

Any rule change that drops a metric by more than 2% triggers investigation before proceeding.

---

## 7. Reliability & security

- `data/status.json` updated every candle cycle as a heartbeat; dashboard shows Running ✅ / Stopped ⚠️ / Crashed ❌
- Each module (`mt5_bridge`, `ai_evaluator`, `telegram_bot`) is wrapped so its failure logs to `logs/` without crashing `main.py` or other modules
- Engine reacts on **candle close**, not continuous polling
- API keys live only in `.env`; `.gitignore` excludes `.env`, `logs/`, `backups/`
- Local backups: `scripts/backup_system.py` zips the project (excluding `.env`) into `backups/`, retention ~7–14 most recent, periodically copied to a cloud-synced folder

---

## 8. When you (Claude Code) make any change

1. Update this file FIRST if a rule or structure changes
2. Then update the code
3. Then update `README.md` if the change affects setup/usage
4. Explain the change to the owner in plain language — what changed and why
5. If the change involves new cost, a new tool, a database, or auto-execution — **stop and ask first**, don't decide unilaterally

---

## 9. Communication style required

- Plain language, no unexplained jargon
- Full working code, never partial snippets the owner is expected to complete
- Confirm before creating/editing/deleting files
- Never assume the owner can debug — fix issues and explain what happened
