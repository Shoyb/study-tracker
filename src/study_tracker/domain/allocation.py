"""Midnight splitting and daily allocation rules.

Pure functions – no Qt, no SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from study_tracker.db.sessions_repo import Session


def allocate_by_day(session: Session) -> dict[str, int]:
    """Allocate a session's duration_secs to local calendar days.

    Rules from section G:
    - Duration-only entries: all seconds belong to session.local_date.
    - Timed sessions that stay within one local day: all seconds belong to that day.
    - Timed sessions crossing midnight: span cut at each local midnight.
      duration_secs shared in proportion to seconds of span falling on each day,
      using integer arithmetic with the remainder given to the last day,
      so the parts always add up to stored duration_secs exactly.
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

    start_date_str = start_local.strftime("%Y-%m-%d")
    end_date_str = end_local.strftime("%Y-%m-%d")

    if start_date_str == end_date_str:
        return {start_date_str: session.duration_secs}

    total_span_secs = int((end_local - start_local).total_seconds())
    if total_span_secs <= 0:
        return {session.local_date: session.duration_secs}

    # Slice the span by local midnight
    spans: list[tuple[str, int]] = []
    curr_start = start_local

    while curr_start < end_local:
        curr_date_str = curr_start.strftime("%Y-%m-%d")
        next_midnight = datetime(
            curr_start.year, curr_start.month, curr_start.day
        ) + timedelta(days=1)

        curr_end = min(next_midnight, end_local)
        span_secs = int((curr_end - curr_start).total_seconds())
        if span_secs > 0:
            spans.append((curr_date_str, span_secs))
        curr_start = next_midnight

    if not spans:
        return {session.local_date: session.duration_secs}

    # Allocate duration_secs proportionally
    result: dict[str, int] = {}
    allocated_so_far = 0

    for i, (date_str, span_secs) in enumerate(spans):
        if i == len(spans) - 1:
            # Last day gets whatever remains so total == session.duration_secs
            day_dur = session.duration_secs - allocated_so_far
        else:
            day_dur = int(session.duration_secs * span_secs / total_span_secs)
            allocated_so_far += day_dur

        if day_dur > 0:
            result[date_str] = result.get(date_str, 0) + day_dur

    return result
