"""Clock abstraction – all production code must use this, never datetime.now().

Injecting a ``Clock`` object lets tests control time exactly:

    clock = FakeClock(start="2026-10-13T08:00:00Z")
    clock.advance(seconds=3600)
    assert clock.now_utc() == "2026-10-13T09:00:00Z"
"""

import time
from datetime import UTC, datetime, timedelta


class Clock:
    """Real-time clock backed by the system clock."""

    def __init__(
        self, utc_offset_hours: int | None = None, cutoff_minutes: int = 180
    ) -> None:
        self._utc_offset_hours = utc_offset_hours
        self._cutoff_minutes = cutoff_minutes

    def now_utc(self) -> str:
        """Return the current UTC time as an ISO 8601 string ending in Z.

        Example: ``"2026-10-13T08:15:30Z"``
        """
        dt = datetime.now(tz=UTC).replace(microsecond=0)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def monotonic(self) -> float:
        """Return a monotonic timestamp in seconds (for measuring elapsed time)."""
        return time.monotonic()

    def local_datetime(self) -> datetime:
        """Return the current local wall time without timezone information."""
        value = datetime.strptime(self.now_utc(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        return value.astimezone().replace(tzinfo=None)

    def local_utc_offset_minutes(self) -> int:
        """Return the system's current local UTC offset in minutes."""
        offset = datetime.now(tz=UTC).astimezone().utcoffset()
        return int((offset or timedelta(0)).total_seconds() // 60)

    def local_date(self) -> str:
        """Return today's study date as ``YYYY-MM-DD``.

        The study-day cutoff defaults to 03:00 and can be changed at runtime.
        """
        return self.study_date()

    def study_date(self, cutoff_minutes: int | None = None) -> str:
        """Return the current study date using the configured cutoff."""
        from datetime import timedelta

        if self._utc_offset_hours is None:
            offset = datetime.now(tz=UTC).astimezone().utcoffset()
            offset = offset or timedelta(0)
        else:
            offset = timedelta(hours=self._utc_offset_hours)
        local_dt = datetime.now(tz=UTC) + offset
        cutoff = self._cutoff_minutes if cutoff_minutes is None else cutoff_minutes
        study_dt = local_dt - timedelta(minutes=cutoff)
        return study_dt.strftime("%Y-%m-%d")

    def set_cutoff_minutes(self, cutoff_minutes: int) -> None:
        if not 0 <= cutoff_minutes < 1440:
            raise ValueError("cutoff_minutes must be between 0 and 1439")
        self._cutoff_minutes = cutoff_minutes


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
        cutoff_minutes: int = 180,
    ) -> None:
        super().__init__(utc_offset_hours=utc_offset_hours, cutoff_minutes=cutoff_minutes)
        self._dt = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        self._monotonic: float = 0.0

    def now_utc(self) -> str:
        return self._dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def monotonic(self) -> float:
        return self._monotonic

    def local_datetime(self) -> datetime:
        return (self._dt + timedelta(hours=self._utc_offset_hours)).replace(tzinfo=None)

    def local_utc_offset_minutes(self) -> int:
        return int(self._utc_offset_hours * 60)

    def local_date(self) -> str:
        return self.study_date()

    def study_date(self, cutoff_minutes: int | None = None) -> str:
        from datetime import timedelta

        local_dt = self._dt + timedelta(hours=self._utc_offset_hours)
        cutoff = self._cutoff_minutes if cutoff_minutes is None else cutoff_minutes
        study_dt = local_dt - timedelta(minutes=cutoff)
        return study_dt.strftime("%Y-%m-%d")

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
