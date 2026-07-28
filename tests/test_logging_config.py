"""
Tests for engine/logging_config.py.

Note: LOGS_DIR itself is read from ICT_LOGS_DIR once, at module import
time (see the comment in engine/logging_config.py) - tests/conftest.py
sets that env var before any other import happens, which is what keeps
the entire test suite from ever touching the real logs/ directory (you
can confirm this by deleting logs/ and running the full suite - it never
reappears). What's tested directly here is get_logger()'s behavior given
wherever LOGS_DIR currently points, via monkeypatch rather than reloading
the module - reloading would re-trigger every other module's `logger =
get_logger(...)` top-level call in unpredictable ways.
"""

import logging

import engine.logging_config as logging_config
from engine.logging_config import get_logger


def test_get_logger_writes_to_configured_logs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_config, "LOGS_DIR", tmp_path)

    logger = get_logger("test_logging_config_unique_name_1")
    logger.info("hello from a test")
    for handler in logger.handlers:
        handler.flush()

    log_file = tmp_path / "test_logging_config_unique_name_1.log"
    assert log_file.exists()
    assert "hello from a test" in log_file.read_text()

    # cleanup so this named logger doesn't leak handlers into other tests
    logging.getLogger("test_logging_config_unique_name_1").handlers.clear()


def test_get_logger_is_idempotent_does_not_duplicate_handlers(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_config, "LOGS_DIR", tmp_path)

    logger1 = get_logger("test_logging_config_unique_name_2")
    logger2 = get_logger("test_logging_config_unique_name_2")

    assert logger1 is logger2
    assert len(logger1.handlers) == 2  # file + console, not doubled

    logging.getLogger("test_logging_config_unique_name_2").handlers.clear()
