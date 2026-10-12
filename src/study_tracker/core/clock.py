"""Clock abstraction – all production code must use this, never datetime.now().

Injecting a ``Clock`` object lets tests control time exactly:

    clock = FakeClock(start="2026-10-13T08:00:00Z")
    clock.advance(seconds=3600)
    assert clock.now_utc() == "2026-10-13T09:00:00Z"
"""

import time
from datetime import UTC, datetime


class Clock:
    """Real-time clock backed by the system clock."""

    def now_utc(self) -> str:
        """Return the current UTC time as an ISO 8601 string ending in Z.

        Example: ``"2026-10-13T08:15:30Z"``
        """
        dt = datetime.now(tz=UTC).replace(microsecond=0)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def monotonic(self) -> float:
        """Return a monotonic timestamp in seconds (for measuring elapsed time)."""
        return time.monotonic()

    def local_date(self) -> str:
        """Return today's local calendar date as ``YYYY-MM-DD``."""
        return datetime.now().strftime("%Y-%m-%d")


class FakeClock(Clock):
    """Controllable clock for unit tests.

    Args:
        start: UTC ISO 8601 string (``"2026-10-13T08:00:00Z"``).
               Defaults to ``"2026-01-01T00:00:00Z"``.
        utc_offset_hours: Local UTC offset used by ``local_date``.
                          Defaults to 0 (UTC).
    """

    def __init__(
        self,
        start: str = "2026-01-01T00:00:00Z",
        utc_offset_hours: int = 0,
    ) -> None:
        self._dt = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        self._monotonic: float = 0.0
        self._utc_offset_hours = utc_offset_hours

    def now_utc(self) -> str:
        return self._dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def monotonic(self) -> float:
        return self._monotonic

    def local_date(self) -> str:
        from datetime import timedelta

        local_dt = self._dt + timedelta(hours=self._utc_offset_hours)
        return local_dt.strftime("%Y-%m-%d")

    def advance(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
        """Move the fake clock forward by the given amount."""
        from datetime import timedelta

        delta = timedelta(seconds=seconds, minutes=minutes, hours=hours)
        self._dt += delta
        self._monotonic += delta.total_seconds()

    def set_utc(self, timestamp: str) -> None:
        """Jump the fake clock to an absolute UTC timestamp."""
        self._dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
