"""
engine/logging_config.py

Shared logging setup for every engine module (mt5_bridge.py today;
telegram_bot.py and ai_evaluator.py will use this too once built).

Per CLAUDE.md's reliability principle: "A failure in one module must
never crash the whole engine. Each module fails independently and logs
the error." get_logger() gives every module a consistent way to do that -
write to logs/<name>.log (rotating, so it never grows unbounded) and also
print to the console, so the owner sees problems in real time without
having to go dig through a log file.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

# Tests set ICT_LOGS_DIR (see tests/conftest.py) so pytest runs never
# write into the real logs/ directory - without this, a live main.py
# session's logs get interleaved with test noise (e.g. simulated
# "MT5 hiccup" errors from tests/test_mt5_bridge.py showing up in
# logs/mt5_bridge.log next to genuine connection errors), which makes the
# real logs unreliable to read after running the test suite.
LOGS_DIR = Path(os.environ.get("ICT_LOGS_DIR") or (Path(__file__).resolve().parent.parent / "logs"))
MAX_LOG_BYTES = 2_000_000  # ~2MB per file before rotating
BACKUP_COUNT = 3


def get_logger(name: str) -> logging.Logger:
    """Returns a logger that writes to logs/<name>.log and the console.
    Safe to call multiple times with the same name - handlers are only
    attached once.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / f"{name}.log", maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    console_handler = logging.StreamHandler()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger
