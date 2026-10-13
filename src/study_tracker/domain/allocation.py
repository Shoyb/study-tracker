"""Midnight splitting and daily allocation rules.

Pure functions – no Qt, no SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from study_tracker.domain.day import day_bounds, study_date

if TYPE_CHECKING:
    from study_tracker.db.sessions_repo import Session


def allocate_by_day(session: Session, cutoff_minutes: int = 180) -> dict[str, int]:
    """Allocate a session across the configured study days.

    Timed sessions are split at the configured study-day boundary. A cutoff of
    180 minutes means each study day runs from 03:00 to 03:00 local time.
    """
    if not session.start_utc or not session.end_utc:
        return {session.local_date: session.duration_secs}

    offset = timedelta(minutes=session.utc_offset_mins)

    start_utc = datetime.strptime(session.start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )
    end_utc = datetime.strptime(session.end_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )

    start_local = (start_utc + offset).replace(tzinfo=None)
    end_local = (end_utc + offset).replace(tzinfo=None)

    if (
        start_local.date() == end_local.date()
        and study_date(start_local, cutoff_minutes) == study_date(end_local, cutoff_minutes)
    ):
        return {study_date(start_local, cutoff_minutes): session.duration_secs}

    total_span_secs = int((end_local - start_local).total_seconds())
    if total_span_secs <= 0:
        return {session.local_date: session.duration_secs}

    spans: list[tuple[str, int]] = []
    curr_start = start_local

    while curr_start < end_local:
        current_day = study_date(curr_start, cutoff_minutes)
        _, next_boundary = day_bounds(current_day, cutoff_minutes)
        curr_end = min(next_boundary, end_local)
        span_secs = int((curr_end - curr_start).total_seconds())
        if span_secs > 0:
            spans.append((current_day, span_secs))
        curr_start = curr_end

    if not spans:
        return {session.local_date: session.duration_secs}

    result: dict[str, int] = {}
    allocated_so_far = 0

    for i, (date_str, span_secs) in enumerate(spans):
        if i == len(spans) - 1:
            day_dur = session.duration_secs - allocated_so_far
        else:
            day_dur = int(session.duration_secs * span_secs / total_span_secs)
            allocated_so_far += day_dur

        if day_dur > 0:
            result[date_str] = result.get(date_str, 0) + day_dur

    return result
