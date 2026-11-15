"""Tests for conference window parsing."""

from refresh_conference_dates import _dates_to_window


def test_single_event_gets_buffered_window():
    window = _dates_to_window([(10, 23), (10, 27)])
    assert window == ("10-09", "11-10")


def test_calendar_page_with_many_events_is_rejected():
    # 2026-10-01 auto-update: esmo.org/meeting-calendar lists several meetings, so the
    # min-max of all dates gave World GI and ESMO Congress the same Sep-Dec window.
    assert _dates_to_window([(7, 1), (7, 4), (10, 23), (12, 5)]) is None
