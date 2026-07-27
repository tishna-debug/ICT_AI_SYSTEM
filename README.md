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
7. **See it actually work — run the demo:**
   ```
   python scripts/demo_run.py
   ```
   This feeds a small made-up price story through the rule engine and
   prints, in plain English, what it detects (swing points, Fair Value
   Gaps, Break of Structure, etc). No real market data or broker
   connection needed — if this prints output without errors, your setup
   is correct and the engine is working.
8. **Run the automated test suite:**
   ```
   pytest
   ```
   This runs every check the engine needs to pass — Candle math, ATR,
   every ICT rule, the full state machine. You should see something like
   `58 passed` at the end with no failures. Run this any time after a
   code change to confirm nothing broke.
9. **Connect to real price data (optional, once you're ready):**
   - Open the MetaTrader5 desktop app and log into your account (**use a
     demo account while testing** — nothing in this system places trades,
     but there's no reason to point it at a live account yet).
   - Leave it open, then run:
     ```
     python scripts/test_mt5.py
     ```
   - This confirms the connection, tells you which account it found
     (double-check it says DEMO), and lists your broker's exact symbol
     names for US100/US500/Gold so you know what to use later. It never
     places a trade.
10. **Watch it work on real live prices (optional):** with MT5 still open,
    run:
    ```
    python scripts/watch_live.py
    ```
    This watches one real symbol (edit the `SYMBOL`/`TIMEFRAME` constants
    near the top of the file to change which one) and prints detected
    patterns to this terminal as real candles close. It loads some recent
    history first so it isn't starting from nothing, then keeps watching
    until you stop it with **Ctrl+C**. Still read-only — never places a
    trade. This is *not* the same as a finished "always-on" system (that's
    `main.py`, still to come) — it's a way to watch the engine work on
    real prices today, in a terminal window you keep open.
11. **Set up Telegram alerts (optional, Build Step 2):**
    - Open Telegram, message **@BotFather**, send `/newbot`, and follow its
      prompts (name it anything; the username must end in `bot`). It replies
      with a **token** that looks like `123456789:ABCdefGhIJKl...`.
    - Send any message to your new bot (e.g. "hi"), then open this URL in a
      browser with your real token in place of `<TOKEN>`:
      `https://api.telegram.org/bot<TOKEN>/getUpdates` — find the number
      after `"chat":{"id":` in the response, that's your chat ID.
    - Copy `.env.example` to a new file named `.env` in this folder, and
      fill in:
      ```
      TELEGRAM_BOT_TOKEN=your token here
      TELEGRAM_CHAT_ID=your chat id here
      ```
      (`.env` is gitignored — it never gets committed or shared.)
    - Test it:
      ```
      python scripts/test_telegram.py
      ```
      You should get a message on Telegram within a few seconds.
12. **Set up AI verdicts (optional, Build Step 3 — costs a small amount
    per API call, roughly $5-15/month total since it's only called on
    confirmed setups, never on every candle):**
    - Get an API key at https://console.anthropic.com (you'll need to add
      a payment method there — that's between you and Anthropic, not
      something this code touches).
    - Add it to `.env`:
      ```
      ANTHROPIC_API_KEY=sk-ant-...
      ```
    - Test it:
      ```
      python scripts/test_ai_evaluator.py
      ```
      This sends one sample setup to Claude and prints back a Buy/Sell/
      No-Trade verdict with reasoning — confirms your key and billing work.
13. **Run the always-on system:**
    ```
    python main.py
    ```
    This is the real thing: connects to MT5, watches your entry timeframe
    plus the four higher timeframes the HTF Bias Cascade needs, and for
    every confirmed setup that's both inside a valid Kill Zone and aligned
    with the higher-timeframe bias, asks Claude for a verdict and sends it
    to your phone. Everything else (raw signal alerts, heartbeat file at
    `data/status.json`, verdict log at `data/verdicts.json`) happens
    automatically. Stop it any time with **Ctrl+C**.

Nothing above touches real money or places a trade. Steps 9-10 and 13
talk to your MT5 terminal only to read prices. Step 11 (and 13's alerts)
only send messages to your own Telegram chat. Step 12 (and 13's verdicts)
only ask Claude for a written opinion — nothing ever acts on it.

---

## What's already built vs. what's next

**Already implemented** (real code, not placeholders), matching the
rulebook exactly:
- `engine/rules/base.py` — Candle model, data quality validation, ATR(14), Displacement, Kill Zone filter (Addendum A)
- `engine/rules/swings.py` — Swing Point detection (high/low, strength, MAJOR/MINOR degree)
- `engine/rules/fvg.py` — Fair Value Gap detection + mitigation + Addendum A confidence scoring
- `engine/rules/bos.py` — Break of Structure + TrendState machine
- `engine/rules/choch.py` — Change of Character classification
- `engine/rules/liquidity_sweep.py` — Liquidity Sweep detection
- `engine/rules/structure_state.py` — master StructureState assembly, snapshot save/load, and replay
- `engine/event_bus.py` — synchronous pub/sub for all `engine/rules/` events
- `scripts/validation_harness.py` — Section 9 precision/recall/F1 scoring tool (needs your hand-labeled chart data to run against — see the script's docstring)
- `scripts/demo_run.py` — plain-English demo on made-up sample data (see "First-time setup" above)
- `engine/mt5_bridge.py` — live price connection (Build Step 1). Attaches to
  a MetaTrader5 desktop terminal you're already logged into by hand — no
  account password is ever read, stored, or requested by this code. Only
  reads price data; never places, modifies, or closes a trade.
- `scripts/test_mt5.py` — run this after opening/logging into MT5 to check
  the connection and find your broker's exact symbol names for US100/US500/Gold
- `scripts/watch_live.py` — watches one real symbol/timeframe on your MT5
  account and prints detected patterns live in your terminal, read-only
  (see "First-time setup" step 10 above)
- `engine/logging_config.py` — shared logger setup (writes to `logs/`), used
  by `mt5_bridge.py` and every future module that needs to fail without crashing
- `engine/event_narration.py` — turns a raw detection event into a one-line
  plain-English description; shared by `demo_run.py`, `watch_live.py`, and
  `alerts/telegram_bot.py`
- `alerts/telegram_bot.py` — sends detected signals to your phone via
  Telegram (Build Step 2). Uses Telegram's plain HTTP API directly (no
  extra package) since alerts only ever go one way, out. Credentials live
  in `.env`, never in code — see "First-time setup" step 11 above.
- `scripts/test_telegram.py` — sends a test message to confirm your
  Telegram setup works
- `engine/rules/bias_cascade.py` — HTF Bias Cascade (Addendum A): checks
  whether an entry-timeframe setup aligns with the Daily→4H→1H→15M trend
  (or the D→1H→15M fallback), and gates AI calls to only Kill-Zone-aligned,
  bias-confirmed setups
- `engine/ai_evaluator.py` — turns a confirmed setup into a Buy/Sell/
  No-Trade verdict with written reasoning via the Claude API (Build Step
  3). Never places a trade — only produces a recommendation for you to
  read. Logs every verdict to `data/verdicts.json`.
- `scripts/test_ai_evaluator.py` — sends one sample setup to Claude and
  prints the verdict, to confirm your API key/billing work
- `main.py` — the always-on orchestrator: MT5 candles in, multi-timeframe
  rule engine, Kill Zone + HTF Bias Cascade gating, AI verdicts and
  Telegram alerts out (see "First-time setup" step 13 above)
- `tests/` — automated test suite (`pytest`), 95 tests covering every rule above

**Stubs only** — intentionally not built yet, per the Master Doc's build order:
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
