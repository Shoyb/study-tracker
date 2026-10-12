"""Tests for core/clock.py"""

from study_tracker.core.clock import Clock, FakeClock


class TestFakeClock:
    def test_initial_time(self):
        clock = FakeClock("2026-10-13T08:00:00Z")
        assert clock.now_utc() == "2026-10-13T08:00:00Z"

    def test_advance_seconds(self):
        clock = FakeClock("2026-10-13T08:00:00Z")
        clock.advance(seconds=90)
        assert clock.now_utc() == "2026-10-13T08:01:30Z"

    def test_advance_minutes(self):
        clock = FakeClock("2026-10-13T08:00:00Z")
        clock.advance(minutes=60)
        assert clock.now_utc() == "2026-10-13T09:00:00Z"

    def test_advance_hours(self):
        clock = FakeClock("2026-10-13T00:00:00Z")
        clock.advance(hours=24)
        assert clock.now_utc() == "2026-10-14T00:00:00Z"

    def test_monotonic_advances(self):
        clock = FakeClock()
        assert clock.monotonic() == 0.0
        clock.advance(seconds=100)
        assert clock.monotonic() == 100.0

    def test_set_utc(self):
        clock = FakeClock()
        clock.set_utc("2026-12-31T23:59:59Z")
        assert clock.now_utc() == "2026-12-31T23:59:59Z"

    def test_local_date_no_offset(self):
        clock = FakeClock("2026-10-13T10:00:00Z", utc_offset_hours=0)
        assert clock.local_date() == "2026-10-13"

    def test_local_date_with_positive_offset(self):
        # UTC+6: midnight UTC is 06:00 local.
        clock = FakeClock("2026-10-13T22:00:00Z", utc_offset_hours=6)
        assert clock.local_date() == "2026-10-14"  # already next day locally

    def test_local_date_with_negative_offset(self):
        # UTC-5: 02:00 UTC is 21:00 previous day local.
        clock = FakeClock("2026-10-13T02:00:00Z", utc_offset_hours=-5)
        assert clock.local_date() == "2026-10-12"


class TestRealClock:
    def test_now_utc_format(self):
        """Real clock returns correct ISO 8601 format."""
        import re
        clock = Clock()
        ts = clock.now_utc()
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts), ts

    def test_monotonic_is_float(self):
        clock = Clock()
        assert isinstance(clock.monotonic(), float)

    def test_local_date_format(self):
        import re
        clock = Clock()
        date = clock.local_date()
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", date), date
