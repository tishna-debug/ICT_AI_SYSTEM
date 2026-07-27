"""
Tests for interface/dashboard.py's pure data-loading helpers (load_json,
tail_lines). The rendering functions call into Streamlit's `st.*` API
directly and are verified by hand in a real browser instead (see the
"start the dev server and use it" step for any UI change) - they aren't
meaningfully unit-testable without Streamlit's own AppTest harness, which
is out of scope for this build step.
"""

import json

from interface.dashboard import load_json, tail_lines


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
