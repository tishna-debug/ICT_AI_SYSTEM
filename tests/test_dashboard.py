"""
Tests for interface/dashboard.py's pure data-loading helpers (load_json,
tail_lines). The rendering functions call into Streamlit's `st.*` API
directly and are verified by hand in a real browser instead (see the
"start the dev server and use it" step for any UI change) - they aren't
meaningfully unit-testable without Streamlit's own AppTest harness, which
is out of scope for this build step.
"""

import json
from datetime import datetime, timezone

from interface.dashboard import format_ny, load_json, parse_iso, tail_lines, to_new_york


def test_load_json_missing_file_returns_none(tmp_path):
    assert load_json(tmp_path / "does_not_exist.json") is None


def test_load_json_empty_file_returns_none(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("")
    assert load_json(path) is None


def test_load_json_malformed_returns_none(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    assert load_json(path) is None


def test_load_json_valid_returns_parsed_data(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps({"state": "RUNNING"}))
    assert load_json(path) == {"state": "RUNNING"}


def test_tail_lines_missing_file_returns_empty_list(tmp_path):
    assert tail_lines(tmp_path / "nope.log") == []


def test_tail_lines_returns_last_n_lines(tmp_path):
    path = tmp_path / "some.log"
    path.write_text("\n".join(f"line {i}" for i in range(100)))
    lines = tail_lines(path, n=5)
    assert lines == [f"line {i}" for i in range(95, 100)]


def test_to_new_york_summer_is_edt_utc_minus_4():
    # 2026-07-28 17:45 UTC (summer, daylight saving) -> 13:45 EDT
    dt = datetime(2026, 7, 28, 17, 45, tzinfo=timezone.utc)
    ny = to_new_york(dt)
    assert ny.strftime("%H:%M %Z") == "13:45 EDT"
    assert ny.utcoffset().total_seconds() == -4 * 3600


def test_to_new_york_winter_is_est_utc_minus_5():
    # 2026-01-15 17:45 UTC (winter, standard time) -> 12:45 EST - this is
    # exactly the case a hardcoded "UTC-4" would get wrong.
    dt = datetime(2026, 1, 15, 17, 45, tzinfo=timezone.utc)
    ny = to_new_york(dt)
    assert ny.strftime("%H:%M %Z") == "12:45 EST"
    assert ny.utcoffset().total_seconds() == -5 * 3600


def test_to_new_york_assumes_naive_datetime_is_utc():
    naive = datetime(2026, 7, 28, 17, 45)  # no tzinfo
    aware = datetime(2026, 7, 28, 17, 45, tzinfo=timezone.utc)
    assert to_new_york(naive) == to_new_york(aware)


def test_parse_iso_valid_and_invalid():
    assert parse_iso(None) is None
    assert parse_iso("") is None
    assert parse_iso("not a date") is None
    assert parse_iso("2026-07-28T17:45:00+00:00") == datetime(2026, 7, 28, 17, 45, tzinfo=timezone.utc)


def test_format_ny_formats_valid_timestamp():
    result = format_ny("2026-07-28T17:45:00+00:00", "%H:%M %Z")
    assert result == "13:45 EDT"


def test_format_ny_falls_back_to_raw_value_when_unparseable():
    assert format_ny("garbage-not-a-date", "%H:%M") == "garbage-not-a-date"
    assert format_ny(None, "%H:%M") == "-"
