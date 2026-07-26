# ICT AI Trading Intelligence System — Master Documentation

**Purpose of this document:** This is the single reference file for the entire system. Share it with any AI model, programmer, or freelancer, and they should be able to understand the full system, its rules, its architecture, its folder structure, and how to extend it safely — without needing to ask the owner technical questions first.

**Owner:** Non-technical trader/operator. Does not write or manage code, servers, or databases directly. All technical work is delegated.

**Status:** Architecture, rule layer, and folder structure fully specified. Ready to begin Step 1 of the build (`engine/rules/` modules). This document is the anchor for every future update.

---

## 1. What This System Is

An AI-assisted trading decision system, built on **ICT (Inner Circle Trader)** concepts, that:

1. Watches live price action on target markets (US100, US500, Gold/XAU, and similar).
2. Applies **strict, mathematically-defined ICT rules** to identify PD (Premium/Discount) array setups — Fair Value Gaps (FVG), Break of Structure (BOS), Change of Character (CHOCH), Liquidity Sweeps, and Displacement.
3. Cross-checks any candidate setup against **market context factors**: news events, volatility state, sentiment, Fear & Greed level, and crowd behavior (FOMO risk).
4. Outputs one of three verdicts — **Buy / Sell / No Trade** — with a written reasoning trail explaining exactly which rule and which context factor drove the decision.
5. Displays everything on a **local Streamlit dashboard** on the owner's laptop and pushes real-time alerts to Telegram.

**What it explicitly does NOT do:** auto-execute trades. It is a decision-support and alerting system. A human places every trade.

---

## 2. Design Principles (do not violate these when extending the system)

| Principle | Meaning |
|---|---|
| **No database** | The system uses flat JSON files, not a database server. Deliberate choice to keep it maintainable by a non-technical owner and hosting cost at $0. Do not introduce SQL/NoSQL without owner sign-off. |
| **Rules are mathematically strict** | ICT concepts are defined with exact, testable numeric conditions — not vague pattern-matching. Every rule change must update Section 4 first, then the code. |
| **One file per PD array concept** | Each ICT concept (FVG, BOS, CHOCH, etc.) lives in its own file under `engine/rules/`. Never merge multiple concepts into one file — this is what lets the system scale to new concepts later without risk to existing ones. |
| **Reasoning is always shown** | Every verdict must be traceable to specific rule(s) and context factor(s) that fired. No "black box" outputs. |
| **No auto-trading** | The system is advisory only. Any future request to add auto-execution is a major decision the owner must explicitly approve — not a natural extension of this system. |
| **Claude API called only on confirmed setups** | Never call the reasoning layer on every candle tick — only when Python's rule layer has already confirmed a valid, Kill-Zone-aligned setup. Keeps cost near $5–15/month. |
| **Low-budget, low-maintenance** | Prefer free/low-cost tools and owner-runnable infrastructure (own laptop) over hosted/paid infrastructure, unless owner explicitly upgrades budget. |
| **Owner is non-technical** | All setup must be reducible to "double-click to start" or equivalent. No step should require the owner to write or debug code. |
| **Graceful degradation** | A failure in one module (Telegram down, AI call times out) must never crash the whole engine. Each module fails independently and logs the error. |
| **Secrets never leave the machine** | API keys live only in `.env`, are never committed to git, and are never included in backups. |

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     OWNER'S LAPTOP (Windows)               │
│                                                             │
│  ┌──────────────┐   ┌──────────────────┐   ┌───────────┐ │
│  │  MT5 Terminal │──▶│   Core Engine     │──▶│ Dashboard │ │
│  │ (live prices) │   │  (Python script)  │   │(Streamlit)│ │
│  └──────────────┘   └────────┬──────────┘   └───────────┘ │
│                               │                             │
│                               ▼                             │
│                      ┌─────────────────┐                   │
│                      │  Flat-file store │                   │
│                      │ (JSON, auto)     │                   │
│                      └─────────────────┘                   │
└───────────────────────────────┬───────────────────────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 ▼               ▼               ▼
          ┌────────────┐  ┌────────────┐  ┌─────────────┐
          │ News/Data   │  │  Anthropic  │  │  Telegram    │
          │ APIs (free  │  │  API (Claude│  │  Bot (free)  │
          │ tier)       │  │  reasoning) │  │  alerts      │
          └────────────┘  └────────────┘  └─────────────┘
```

**Core Engine** — pulls prices from MT5, checks them against the rule modules in `engine/rules/`, applies Kill Zone and HTF bias filters, calls the Anthropic API only on confirmed setups, and writes results to the flat-file store, the dashboard, and Telegram.

---

## 4. ICT Rule Layer (Phase 1 — Canonical Definitions)

These are the exact, mathematical rules the system checks. This section is the **single source of truth** — any code implementing these concepts must match this section exactly, and any rule change must be made here first, then in the matching file under `engine/rules/`.

| Concept | Status | Key engineering decision | Code location |
|---|---|---|---|
| Candle (base unit) | Defined | Standard OHLC candle model | `engine/rules/base.py` |
| Displacement | Defined | Threshold-based, tied to average range | `engine/rules/base.py` |
| Swing Points | Defined | Local high/low confirmed by `SWING_LOOKBACK` candles each side; degree (MAJOR/MINOR) scored by confirming-candle strength, not discretion | `engine/rules/swings.py` |
| Fair Value Gap (FVG) | Defined | Full mitigation requires a candle **close** beyond the gap's far edge (wicks don't count); the **50–60% fill band** only governs the *additional* `STRONG` confidence tag on a partial fill (width adjusts with volatility, measured via **14-period ATR on the same timeframe as the FVG being evaluated**). **Exception:** on HTF entries of 15M/5M, a full 100% wick fill is also accepted as mitigation. | `engine/rules/fvg.py` |
| Break of Structure (BOS) | Defined | **Requires candle close beyond the level** (wick alone does not count) | `engine/rules/bos.py` |
| Change of Character (CHOCH) | Defined | Structural shift definition, distinct from BOS | `engine/rules/choch.py` |
| Liquidity Sweep | Defined | Wick-based raid of prior high/low, followed by rejection | `engine/rules/liquidity_sweep.py` |
| Market Structure State | Defined | Master per-symbol/timeframe state object; assembled from all concepts above on every new candle, with a deterministic content hash for replay verification | `engine/rules/structure_state.py` |
| Kill Zone filter | Defined | Only London and New York sessions are valid trading windows. Within NY, **9:30–10:00 AM EST is the flagged high-volatility sub-window**, weighted accordingly. Setups outside these windows are filtered or heavily downweighted. | `engine/rules/base.py` (session filter) |
| HTF Bias Cascade | Defined | **Primary check:** bias aligned across **Daily → 4H → 1H → 15M** = full-confidence setup. **Fallback check:** if 4-way alignment fails, drop 4H and check **Daily → 1H → 15M** instead — if aligned, still tradeable but flagged lower-confidence. **Entries taken on 5M, 3M, or 1M** once bias (primary or fallback) is confirmed. | `engine/rules/bias_cascade.py` |

All numeric values in this table (ATR period, fill %, Kill Zone hours) are also stored in `config/rules_config.json` so they can be tuned without editing code.

> **Note for whoever picks this up:** the full mathematical rulebook (exact formulas and edge cases) exists as a separate "ICT Engineering Rulebook" document from earlier project work. Attach it alongside this master file for any handoff — it contains the literal formulas this table summarizes.

**Phase 2+ concepts** (not yet formally defined — planned additions): Order Blocks, Breaker Blocks, Optimal Trade Entry (OTE) zones, Judas Swing, Power of Three. Add each as its own new file in `engine/rules/`, and add a row here, before coding it.

---

## 5. Context Layer (Market Conditions Beyond Price)

Answers "should I trust this setup right now?" — sits alongside the ICT rule layer and can downgrade a technically-valid setup to "No Trade."

| Factor | Source | What it affects |
|---|---|---|
| News events | Free-tier financial news/economic calendar API | Flags high-impact news windows; system defaults to caution or No-Trade around major releases |
| Volatility state | Derived from live price data (no extra cost) | Feeds the ATR-based FVG threshold; flags abnormal volatility |
| Sentiment | Free/low-cost sentiment API or aggregated source | Contributes to reasoning, not a hard veto |
| Fear & Greed level | Public index (free) | Contextual input, not a hard veto |
| FOMO/crowd behavior risk | Derived heuristic (rapid extension + volume spike + sentiment extreme together) | Flags a setup as "technically valid but high FOMO risk" |

**Status:** Defined conceptually; implemented in `engine/ai_evaluator.py` — this is Build Step 3, after the rule engine and Telegram alerts are proven (see Section 9).

---

## 6. Folder & File Structure

This is the authoritative project layout. Anyone building or extending the system must follow this structure — it's what keeps the system understandable as it grows.

```
project/
├── config/
│   ├── settings.json          # Symbols, timeframes, Kill Zones, account risk limits
│   └── rules_config.json      # Mathematical thresholds (ATR periods, FVG fill bands, HTF rules)
├── data/
│   ├── setups.json            # Active & historic ICT setup signals
│   ├── verdicts.json          # Claude AI BUY / SELL / NO TRADE reasoning logs
│   ├── status.json            # Heartbeat file — engine health state for crash detection
│   └── price_logs/            # Local OHLC cache for offline backtesting
├── engine/
│   ├── __init__.py
│   ├── mt5_bridge.py          # Live MT5 tick connection & price candle extraction
│   ├── event_bus.py           # Synchronous pub/sub for engine/rules/ events (Phase 1 Step 10)
│   ├── rules/                 # One file per ICT PD array concept — never merged
│   │   ├── __init__.py
│   │   ├── base.py            # Candle model, data quality rules, ATR(14), displacement, Kill Zone filter
│   │   ├── swings.py          # Swing high/low detection
│   │   ├── fvg.py
│   │   ├── bos.py
│   │   ├── choch.py
│   │   ├── liquidity_sweep.py
│   │   ├── structure_state.py # Master StructureState assembly + snapshot/replay (Phase 1 Steps 9 & 11)
│   │   └── bias_cascade.py
│   └── ai_evaluator.py        # Anthropic Claude API prompt runner & risk evaluator
├── alerts/
│   ├── __init__.py
│   └── telegram_bot.py        # Telegram alert dispatcher & formatters
├── interface/
│   └── dashboard.py           # Streamlit local browser dashboard
├── logs/                       # System error logs & runtime logs (rotating), separate from data/
├── backups/                    # Automated ZIP archives — excludes .env, retention-limited
├── scripts/
│   ├── setup_environment.py   # One-click directory & file builder
│   ├── test_mt5.py            # Diagnostic script to verify MT5 connection
│   ├── backup_system.py       # Zips project (excluding .env), prunes old backups, can push to a cloud-synced folder
│   └── validation_harness.py  # Section 9 precision/recall/F1 scoring against hand-labeled charts (Phase 1 Step 12)
├── requirements.txt            # Exact Python dependency list, for reliable reinstall
├── .env                        # API keys (ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, MT5 credentials) — never shared, never backed up
├── .env.example                 # Safe template with blank values, for sharing with a programmer
├── .gitignore                   # Excludes .env, logs/, and backups/ from git
├── README.md                    # System overview and start commands
└── main.py                      # Master orchestrator script
```

**Rule for extending this structure:** a new ICT concept = a new file in `engine/rules/` + a new row in Section 4. A new context factor = a new row in Section 5 + logic in `ai_evaluator.py`. Nothing should be bolted onto an unrelated existing file.

---

## 7. Data Storage (No Database)

All data is stored in plain JSON files, auto-managed by the Core Engine. No database server, no SQL, no external hosting.

| Data | Format | Location |
|---|---|---|
| Price/setup history | JSON | `data/setups.json`, `data/price_logs/` |
| Verdict/reasoning log | JSON | `data/verdicts.json` |
| Engine health/heartbeat | JSON | `data/status.json` |
| Alert history | JSON | logged via `alerts/telegram_bot.py` |

If the system later needs to scale to many instruments, years of history, or multi-user access, a database becomes worth reconsidering — a deliberate future decision, not a default.

---

## 8. Security & Backup

| Concern | Policy |
|---|---|
| API keys | Stored only in `.env`. Never committed to git (`.gitignore`), never included in `backups/` archives, never shared with anyone — share `.env.example` instead. |
| Local backups | `scripts/backup_system.py` zips the project (excluding `.env`) into `backups/` on a schedule, with a **retention limit (~7–14 most recent)** so it doesn't grow forever. |
| Offsite/disaster backup | Local backups alone don't protect against laptop loss/theft/failure. The backup zip should also be periodically copied to a free cloud-synced folder (Google Drive/OneDrive) — no new tooling required. |
| Sharing with a programmer | Share the project folder + this master doc + `.env.example`. Never share the real `.env` or `backups/`. |

---

## 9. Reliability & Error Handling

| Concern | Policy |
|---|---|
| Is the system alive? | `data/status.json` is updated by the engine every candle cycle as a heartbeat. The dashboard reads it and shows **Running ✅ / Stopped ⚠️ / Crashed ❌ (since [time])** — so the owner is never guessing. |
| One module fails | Each module (`mt5_bridge`, `ai_evaluator`, `telegram_bot`) is wrapped so its failure is logged to `logs/` and does not crash `main.py` or the other modules. Example: if Telegram is down, setups still get detected and logged; only the alert is missed. |
| Reinstalling / new machine | `requirements.txt` lists exact dependencies, so setup is one command instead of guesswork. |
| Execution speed | The engine reacts on **candle close**, not continuous polling — keeps CPU/API usage low and matches the Kill-Zone-only design. |

---

## 10. Technology Stack

| Layer | Tool | Cost |
|---|---|---|
| Language | Python 3.11 | Free |
| Market data | MT5 (broker terminal, Windows) + Python MT5 library | Free (existing broker account) |
| AI reasoning | Anthropic API (Claude), called only on confirmed setups | Pay-as-you-go, est. $5–15/month |
| News/sentiment data | Free-tier financial APIs | Free |
| Dashboard | Streamlit (local, browser-based) | Free |
| Alerts | Telegram Bot API | Free |
| Hosting | Owner's own Windows laptop (must stay on during trading hours) | Free — optional ~$5/mo VPS only if 24/7 uptime needed later |
| Database | None (see Section 7) | $0 |

**Estimated total ongoing cost: ~$5–15/month.**

---

## 11. Build Roadmap (Revised Order)

Confirmed sequence — build and test each step before starting the next:

1. **Step 1 (current):** `engine/rules/` — ICT PD array detection modules (FVG, BOS, CHOCH, sweeps, bias cascade), tested against historical MT5 data, no AI or interface yet.
2. **Step 2:** `alerts/telegram_bot.py` — get raw rule-based signals onto the owner's phone, to validate rule accuracy in the real world before adding AI cost.
3. **Step 3:** `engine/ai_evaluator.py` — connect the Anthropic API to generate the Buy/Sell/No-Trade verdict and reasoning, called only on confirmed setups.
4. **Step 4:** Context layer — news, volatility, sentiment, Fear & Greed, FOMO heuristics feeding into the AI verdict.
5. **Step 5:** `interface/dashboard.py` — Streamlit dashboard, built last, once the underlying signal is proven.
6. **Step 6 (later, optional):** Expand instrument coverage, add Phase 2 ICT concepts (Order Blocks, OTE, Judas Swing, Power of Three) as new files in `engine/rules/`, revisit database only if scale genuinely requires it.

---

## 12. How to Update This System Later

- **To change a rule:** edit Section 4 first, then update the matching file in `engine/rules/` and `config/rules_config.json`. Never edit code without updating this section first.
- **To add a new PD array concept:** add a new file in `engine/rules/`, add a row to Section 4 — never add it into an existing concept's file.
- **To add a new context factor:** add a row to Section 5, then implement in `ai_evaluator.py`.
- **To hand this off to someone new:** give them this file, the ICT Engineering Rulebook, and `.env.example` (never the real `.env`). That's enough for a programmer or another AI model to understand and extend the system without further explanation from the owner.
- **To check budget impact of a change:** update Section 10's cost table before building.
- **To check system health:** check `data/status.json` via the dashboard, and `logs/` for any recent errors.

---

*This document is the living source of truth for the system. Any time the system changes — a rule, a folder, a tool — this file should be updated in the same session.*
