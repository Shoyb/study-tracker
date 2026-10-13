"""Study-day calculations with a configurable cutoff.

The project's "study day" can be shifted from the calendar day boundary to a
custom cutoff such as 03:00.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta


def study_date(local_dt: datetime, cutoff_minutes: int = 180) -> str:
    """Return the study-date string for a local datetime.

    A study day is the date of ``local_dt - cutoff``. For the default 03:00
    cutoff, a session at 01:00 on Wednesday still belongs to Tuesday's study day.
    """
    cutoff = timedelta(minutes=cutoff_minutes)
    return (local_dt - cutoff).date().isoformat()


def day_bounds(study_day: str | date, cutoff_minutes: int = 180) -> tuple[datetime, datetime]:
    """Return the start and end instants that bound a study day."""
    if isinstance(study_day, str):
        study_day_obj = date.fromisoformat(study_day)
    else:
        study_day_obj = study_day

    start = datetime.combine(study_day_obj, time.min) + timedelta(minutes=cutoff_minutes)
    end = start + timedelta(days=1)
    return start, end


def study_date_for_utc(utc_iso: str, utc_offset_mins: int, cutoff_minutes: int = 180) -> str:
    """Convenience helper for deriving the study date from a UTC timestamp."""
    dt_utc = datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ")
    local_dt = dt_utc + timedelta(minutes=utc_offset_mins)
    return study_date(local_dt, cutoff_minutes=cutoff_minutes)
