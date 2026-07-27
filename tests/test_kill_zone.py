from datetime import datetime, timezone

from engine.rules.base import check_kill_zone, is_in_kill_zone
from datetime import time as dtime


def test_is_in_kill_zone_london_window():
    in_kz, in_hot = is_in_kill_zone(dtime(3, 0))
    assert in_kz is True
    assert in_hot is False


def test_is_in_kill_zone_ny_hot_window():
    in_kz, in_hot = is_in_kill_zone(dtime(9, 45))
    assert in_kz is True
    assert in_hot is True


def test_is_in_kill_zone_outside_all_windows():
    in_kz, in_hot = is_in_kill_zone(dtime(14, 0))
    assert in_kz is False
    assert in_hot is False


def test_check_kill_zone_labels_london_session():
    # 2026-01-15 07:30 UTC -> 02:30 EST (winter, UTC-5) -> London Kill Zone
    ts = datetime(2026, 1, 15, 7, 30, tzinfo=timezone.utc)
    event = check_kill_zone(ts)
    assert event.in_kill_zone is True
    assert event.session == "LONDON"
    assert event.event_type == "KILL_ZONE_CHECKED"


def test_check_kill_zone_labels_ny_session():
    # 2026-01-15 14:45 UTC -> 09:45 EST (winter, UTC-5) -> NY hot window
    ts = datetime(2026, 1, 15, 14, 45, tzinfo=timezone.utc)
    event = check_kill_zone(ts)
    assert event.in_kill_zone is True
    assert event.in_hot_window is True
    assert event.session == "NY"


def test_check_kill_zone_none_session():
    # 2026-01-15 20:00 UTC -> 15:00 EST -> outside both windows
    ts = datetime(2026, 1, 15, 20, 0, tzinfo=timezone.utc)
    event = check_kill_zone(ts)
    assert event.in_kill_zone is False
    assert event.session == "NONE"


def test_check_kill_zone_handles_naive_datetime_as_utc():
    ts = datetime(2026, 1, 15, 14, 45)  # no tzinfo
    event = check_kill_zone(ts)
    assert event.session == "NY"


def test_check_kill_zone_respects_dst():
    # 2026-07-15 13:45 UTC -> summer, US Eastern is UTC-4 (EDT) -> 09:45 local -> NY hot window
    ts = datetime(2026, 7, 15, 13, 45, tzinfo=timezone.utc)
    event = check_kill_zone(ts)
    assert event.session == "NY"
    assert event.in_hot_window is True
