"""Tests for core/formatting.py."""


from study_tracker.core.formatting import (
    format_date,
    format_duration,
    format_duration_short,
    format_time,
    parse_hhmm,
)

# ── format_duration ───────────────────────────────────────────────────────────

class TestFormatDuration:
    def test_zero(self):
        assert format_duration(0) == "0 min"

    def test_negative_treated_as_zero(self):
        assert format_duration(-5) == "0 min"

    def test_less_than_one_minute(self):
        assert format_duration(59) == "< 1 min"
        assert format_duration(1) == "< 1 min"

    def test_exactly_one_minute(self):
        assert format_duration(60) == "1 min"

    def test_several_minutes(self):
        assert format_duration(300) == "5 min"

    def test_exactly_one_hour(self):
        assert format_duration(3600) == "1 h 00 min"

    def test_hours_and_minutes(self):
        assert format_duration(7500) == "2 h 05 min"

    def test_one_hour_one_minute(self):
        assert format_duration(3660) == "1 h 01 min"


# ── format_duration_short ─────────────────────────────────────────────────────

class TestFormatDurationShort:
    def test_zero(self):
        assert format_duration_short(0) == "00:00:00"

    def test_one_hour(self):
        assert format_duration_short(3600) == "01:00:00"

    def test_mixed(self):
        assert format_duration_short(3723) == "01:02:03"

    def test_large(self):
        assert format_duration_short(36000) == "10:00:00"


# ── format_date ───────────────────────────────────────────────────────────────

class TestFormatDate:
    def test_known_date(self):
        # 2026-10-13 is a Tuesday.
        assert format_date("2026-10-13") == "Tue 13 Oct 2026"

    def test_monday(self):
        assert format_date("2026-10-12").startswith("Mon")

    def test_invalid_returns_input(self):
        assert format_date("not-a-date") == "not-a-date"

    def test_empty_returns_empty(self):
        assert format_date("") == ""

    def test_none_returns_empty(self):
        assert format_date(None) == ""  # type: ignore[arg-type]


# ── format_time ───────────────────────────────────────────────────────────────

class TestFormatTime:
    def test_empty_string(self):
        assert format_time("") == ""

    def test_none(self):
        assert format_time(None) == ""  # type: ignore[arg-type]

    def test_valid_utc_returns_hhmm(self):
        # Just check it returns something HH:MM shaped.
        result = format_time("2026-10-13T08:15:30Z")
        assert len(result) == 5
        assert result[2] == ":"


# ── parse_hhmm ────────────────────────────────────────────────────────────────

class TestParseHHMM:
    def test_valid(self):
        assert parse_hhmm("08:30") == 8 * 3600 + 30 * 60

    def test_midnight(self):
        assert parse_hhmm("00:00") == 0

    def test_end_of_day(self):
        assert parse_hhmm("23:59") == 23 * 3600 + 59 * 60

    def test_invalid_hour(self):
        assert parse_hhmm("24:00") is None

    def test_invalid_minute(self):
        assert parse_hhmm("12:60") is None

    def test_bad_format(self):
        assert parse_hhmm("830") is None
        assert parse_hhmm("8:3") is None
        assert parse_hhmm("abc") is None

    def test_strips_whitespace(self):
        assert parse_hhmm("  09:45  ") == 9 * 3600 + 45 * 60
