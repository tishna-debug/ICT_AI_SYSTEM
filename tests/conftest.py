"""
Shared pytest fixtures for the engine/rules/ test suite.

`mk_candle` builds a Candle from short positional args instead of the full
keyword form, since most tests only care about a handful of OHLC values
and a synthetic, evenly-spaced timestamp.
"""

import os
import tempfile

# Must run before anything imports engine.logging_config (directly or
# transitively via engine.mt5_bridge/alerts.telegram_bot/etc.), so every
# logger created during this test session writes to a throwaway directory
# instead of the real logs/ - otherwise pytest runs interleave test noise
# into a live main.py session's real logs. See engine/logging_config.py.
os.environ.setdefault("ICT_LOGS_DIR", tempfile.mkdtemp(prefix="ict_test_logs_"))

from datetime import datetime, timedelta

import pytest

from engine.rules.base import Candle

BASE_TS = datetime(2026, 1, 1)


@pytest.fixture
def mk_candle():
    def _mk(i: int, o: float, h: float, l: float, c: float, timeframe: str = "M5", symbol: str = "TEST", minutes_per_candle: int = 5):
        return Candle(
            timestamp=BASE_TS + timedelta(minutes=minutes_per_candle * i),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=10,
            timeframe=timeframe,
            symbol=symbol,
        )

    return _mk
