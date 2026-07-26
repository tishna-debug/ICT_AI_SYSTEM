# ICT AI Trading Intelligence System

Advisory-only system: watches price, applies strict ICT rules, gives a
written Buy / Sell / No-Trade reasoning trail. **It never places trades
automatically** — a human places every trade.

Full design docs (keep these next to this folder, don't lose them):
- `ICT-AI-Trading-System-Master-Doc-3.md` — architecture & folder structure
- `ICT-Engineering-Rulebook-Phase1.md` — exact math for every ICT concept
- `ICT-Rulebook-Addendum-A.md` — confidence scoring, Kill Zones, HTF bias

---

## First-time setup (do this once)

1. **Extract this folder** somewhere permanent, e.g. `C:\Users\<you>\ict-trading-system`.
2. **Open it in VS Code**: VS Code → File → Open Folder → select the extracted folder.
3. **Open a terminal inside VS Code**: menu → Terminal → New Terminal.
4. **Create a virtual environment** (keeps this project's packages separate
   from everything else on your laptop). Paste into the terminal:
   ```
   python -m venv .venv
   ```
5. **Activate it.**
   - Windows: `.venv\Scripts\activate`
   - Mac/Linux: `source .venv/bin/activate`

   You'll know it worked because the terminal line now starts with `(.venv)`.
6. **Install the dependencies:**
   ```
   pip install -r requirements.txt
   ```
   (`MetaTrader5` only installs on Windows — that's expected and fine.)
7. **Run the environment check:**
   ```
   python scripts/verify_setup.py
   ```
   You should see `ALL CHECKS PASSED` at the end. If you do, your coding
   environment is correctly wired up — Python, the folder structure, and
   the rule engine all talk to each other correctly.
8. **Run the orchestrator stub:**
   ```
   python main.py
   ```

If both of those run without errors, you're done with setup. Nothing here
touches real money, a real broker, or the internet yet.

---

## What's already built vs. what's next

**Already implemented** (real code, not placeholders), matching the
rulebook exactly:
- `engine/rules/base.py` — Candle model, data quality validation, ATR(14), Displacement
- `engine/rules/swings.py` — Swing Point detection (high/low, strength, MAJOR/MINOR degree)
- `engine/rules/fvg.py` — Fair Value Gap detection + mitigation + Addendum A confidence scoring
- `engine/rules/bos.py` — Break of Structure + TrendState machine
- `engine/rules/choch.py` — Change of Character classification
- `engine/rules/liquidity_sweep.py` — Liquidity Sweep detection
- `engine/rules/structure_state.py` — master StructureState assembly, snapshot save/load, and replay
- `engine/event_bus.py` — synchronous pub/sub for all `engine/rules/` events
- `scripts/validation_harness.py` — Section 9 precision/recall/F1 scoring tool (needs your hand-labeled chart data to run against — see the script's docstring)

**Stubs only** — intentionally not built yet, per the Master Doc's build order:
- `engine/rules/bias_cascade.py` — HTF Bias Cascade (Addendum A)
- `engine/mt5_bridge.py` — live price connection (Build Step 1)
- `alerts/telegram_bot.py` — phone alerts (Build Step 2)
- `engine/ai_evaluator.py` — Claude API verdicts (Build Step 3)
- `interface/dashboard.py` — Streamlit dashboard (Build Step 5)

**Known open item:** the Phase 1 rulebook's own Liquidity Sweep recovery-ratio
formula (Section 7.2) is structurally unable to produce a "MESSY" sweep
classification — given its condition 2 (`close` back inside the level),
the recovery ratio is mathematically always ≥ 1.0, so every detected sweep
classifies as "CLEAN". Implemented literally per your instruction; flagged
here in case it matters once you validate against real charts.

## Build roadmap (Master Doc, Section 11 — build in this order)

1. Test `engine/rules/` against real historical MT5 candle data (no AI, no
   dashboard yet) until it hits the precision targets in the rulebook's
   Section 9 validation table.
2. Wire up `alerts/telegram_bot.py` so raw rule signals reach your phone —
   proves rule accuracy in the real world before you start paying for AI calls.
3. Build `engine/ai_evaluator.py` to turn confirmed setups into a Buy/Sell/No-Trade
   verdict with reasoning.
4. Add the context layer (news, volatility, sentiment, Fear & Greed, FOMO) into
   the AI verdict.
5. Build `interface/dashboard.py` last.

**Rule for extending this project:** a new ICT concept gets its own new
file in `engine/rules/` — never bolted onto an existing one. A rule change
always gets made in the rulebook markdown files first, then in the matching
code file and `config/rules_config.json`.

---

## How to keep working with Claude on this

This folder + the 3 markdown docs are everything Claude (or a programmer)
needs to pick this project back up — no extra explanation required.

For the next build step (Step 1: testing against real MT5 data), **Claude
Code** is the better tool than this chat: it can read, write, and run files
directly on your laptop as you work, rather than you copy-pasting code back
and forth. This chat is great for planning, reviewing, and generating a
batch of files like this one — Claude Code is better for the ongoing,
iterative "run it, see the error, fix it" loop of building Step 1 onward.
