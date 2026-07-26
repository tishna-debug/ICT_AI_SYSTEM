"""
Shared pytest fixtures for the engine/rules/ test suite.

`mk_candle` builds a Candle from short positional args instead of the full
keyword form, since most tests only care about a handful of OHLC values
and a synthetic, evenly-spaced timestamp.
"""

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
