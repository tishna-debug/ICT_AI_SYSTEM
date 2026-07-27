"""
interface/dashboard.py

Build Step 5: local Streamlit dashboard. READ-ONLY - shows what the
system is doing (by reading the flat JSON files it already writes), never
controls it and never places a trade. Run main.py separately in another
terminal to actually run the system; this just displays
data/status.json, data/setups.json, data/verdicts.json, and recent log
activity from logs/.

Run it with:
    streamlit run interface/dashboard.py

Opens in your browser automatically (usually http://localhost:8501).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATUS_PATH = PROJECT_ROOT / "data" / "status.json"
SETUPS_PATH = PROJECT_ROOT / "data" / "setups.json"
VERDICTS_PATH = PROJECT_ROOT / "data" / "verdicts.json"
LOGS_DIR = PROJECT_ROOT / "logs"

# If main.py's heartbeat says RUNNING but hasn't updated in this long,
# something has silently died (crashed without hitting the except/finally
# in main.py, laptop went to sleep, etc.) - flag it rather than trust the
# stale "RUNNING" label at face value.
STALE_HEARTBEAT_SECONDS = 300


def load_json(path: Path) -> Optional[object]:
    """Reads and parses a JSON file, returning None if it's missing, empty,
    or malformed - never raises, since this is just a read-only viewer.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def tail_lines(path: Path, n: int = 40) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-n:]]
    except FileNotFoundError:
        return []


def render_status(status: Optional[dict]) -> None:
    st.subheader("System Status")

    if status is None:
        st.warning("No status file yet - main.py hasn't run in this folder.")
        return

    state = status.get("state", "UNKNOWN")
    updated_at = None
    if status.get("updated_at"):
        try:
            updated_at = datetime.fromisoformat(status["updated_at"])
        except ValueError:
            pass

    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds() if updated_at else None

    if state == "RUNNING" and age_seconds is not None and age_seconds > STALE_HEARTBEAT_SECONDS:
        st.error(f"Marked RUNNING but the last heartbeat was {int(age_seconds // 60)} minute(s) ago - probably crashed or stopped without cleanup.")
    elif state == "RUNNING":
        st.success("Running")
    elif state == "STOPPED":
        st.warning("Stopped")
    elif state == "CRASHED":
        st.error("Crashed")
    else:
        st.info(f"Status: {state}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Symbol", status.get("symbol", "-"))
    col2.metric("Entry timeframe", status.get("entry_timeframe", "-"))
    col3.metric("Last update", updated_at.strftime("%H:%M:%S UTC") if updated_at else "-")

    if status.get("detail"):
        st.caption(status["detail"])


def render_verdicts(verdicts: Optional[list]) -> None:
    st.subheader("Recent AI Verdicts")
    if not verdicts:
        st.info("No verdicts logged yet.")
        return

    verdict_icon = {"BUY": "\U0001F7E2", "SELL": "\U0001F534", "NO_TRADE": "⚪"}
    for v in reversed(verdicts[-20:]):
        icon = verdict_icon.get(v.get("verdict"), "❓")
        title = f"{icon} {v.get('verdict', '?')} ({v.get('confidence', '?')}) - {v.get('symbol', '?')} {v.get('timeframe', '?')} - {v.get('created_at', '?')}"
        with st.expander(title):
            st.write(f"**Triggered by:** {v.get('triggered_by', '-')}")
            st.write(f"**Reasoning:** {v.get('reasoning', '-')}")


def render_setups(setups: Optional[list]) -> None:
    st.subheader("Recent Detected Setups")
    if not setups:
        st.info("No setups logged yet.")
        return

    rows = [
        {
            "Time": s.get("logged_at", "-"),
            "Type": s.get("event_type", "-"),
            "Timeframe": s.get("timeframe", "-"),
            "Description": s.get("description", "-"),
        }
        for s in reversed(setups[-50:])
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_logs() -> None:
    st.subheader("Recent Log Activity")
    if not LOGS_DIR.exists():
        st.info("No logs yet - they appear once main.py has run at least once.")
        return

    log_files = sorted(LOGS_DIR.glob("*.log"))
    if not log_files:
        st.info("No logs yet - they appear once main.py has run at least once.")
        return

    selected = st.selectbox("Log file", [f.name for f in log_files])
    lines = tail_lines(LOGS_DIR / selected)
    st.code("\n".join(lines) if lines else "(empty)", language="text")


def main() -> None:
    st.set_page_config(page_title="ICT AI Trading System", page_icon="\U0001F4C8", layout="wide")
    st.title("ICT AI Trading System")
    st.caption("Advisory only - this dashboard never places a trade, it only shows what the engine has already detected. Run `python main.py` separately to actually run the system.")

    col_refresh, col_auto = st.columns([1, 3])
    with col_refresh:
        if st.button("Refresh now"):
            st.rerun()
    with col_auto:
        auto_refresh = st.checkbox("Auto-refresh every 10 seconds")

    status = load_json(STATUS_PATH)
    verdicts = load_json(VERDICTS_PATH)
    setups = load_json(SETUPS_PATH)

    render_status(status)
    st.divider()

    tab_verdicts, tab_setups, tab_logs = st.tabs(["AI Verdicts", "Detected Setups", "Logs"])
    with tab_verdicts:
        render_verdicts(verdicts)
    with tab_setups:
        render_setups(setups)
    with tab_logs:
        render_logs()

    if auto_refresh:
        time.sleep(10)
        st.rerun()


if __name__ == "__main__":
    main()
