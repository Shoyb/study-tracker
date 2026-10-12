"""Display-formatting helpers.

All date, time and duration formatting for the UI lives here so that every
page shows the same strings for the same data.

Nothing in this module imports Qt – it is safe to use in tests.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Duration formatting
# ---------------------------------------------------------------------------

def format_duration(seconds: int) -> str:
    """Return a human-readable duration string.

    Examples::

        format_duration(0)       -> "0 min"
        format_duration(45)      -> "< 1 min"
        format_duration(3600)    -> "1 h 00 min"
        format_duration(7500)    -> "2 h 05 min"
        format_duration(59)      -> "< 1 min"
        format_duration(60)      -> "1 min"
        format_duration(119)     -> "1 min"
        format_duration(3660)    -> "1 h 01 min"
    """
    if seconds < 0:
        seconds = 0
    if seconds == 0:
        return "0 min"
    minutes = seconds // 60
    if minutes == 0:
        return "< 1 min"
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    return f"{hours} h {mins:02d} min"


def format_duration_short(seconds: int) -> str:
    """Return a compact HH:MM:SS string, used for the running timer display."""
    if seconds < 0:
        seconds = 0
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Date and datetime formatting
# ---------------------------------------------------------------------------

_WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTH_ABBR = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def format_date(iso_date: str) -> str:
    """Format a ``YYYY-MM-DD`` string as ``"Tue 13 Oct 2026"``.

    Returns the original string unchanged if it cannot be parsed.
    """
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        wd = _WEEKDAY_ABBR[dt.weekday()]
        mon = _MONTH_ABBR[dt.month]
        return f"{wd} {dt.day} {mon} {dt.year}"
    except (ValueError, TypeError):
        return iso_date or ""


def format_time(iso_utc: str) -> str:
    """Format a UTC ISO 8601 timestamp as a local ``HH:MM`` string.

    Returns ``""`` for NULL / empty values.
    """
    if not iso_utc:
        return ""
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        local_dt = dt.astimezone()
        return local_dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return iso_utc


def format_datetime(iso_utc: str) -> str:
    """Format a UTC ISO 8601 timestamp as ``"Tue 13 Oct 2026, 14:30"``."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        local_dt = dt.astimezone()
        wd = _WEEKDAY_ABBR[local_dt.weekday()]
        mon = _MONTH_ABBR[local_dt.month]
        return f"{wd} {local_dt.day} {mon} {local_dt.year}, {local_dt.strftime('%H:%M')}"
    except (ValueError, TypeError):
        return iso_utc


# ---------------------------------------------------------------------------
# Parsing helpers (used by the manual-entry dialog)
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_hhmm(text: str) -> int | None:
    """Parse ``HH:MM`` into seconds since midnight, or ``None`` on failure."""
    m = _TIME_RE.match(text.strip())
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2))
    if h > 23 or mn > 59:
        return None
    return h * 3600 + mn * 60
