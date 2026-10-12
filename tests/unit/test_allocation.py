"""Unit tests for domain/allocation.py."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from study_tracker.db.sessions_repo import Session
from study_tracker.domain.allocation import allocate_by_day


def make_session(
    *,
    local_date: str = "2026-10-13",
    start_utc: str | None = None,
    end_utc: str | None = None,
    duration_secs: int = 3600,
    utc_offset_mins: int = 0,
) -> Session:
    return Session(
        id=1,
        uuid="uuid-1",
        subject_id=1,
        task_id=None,
        local_date=local_date,
        start_utc=start_utc,
        end_utc=end_utc,
        duration_secs=duration_secs,
        session_type="timer" if start_utc else "manual_duration",
        notes="",
        utc_offset_mins=utc_offset_mins,
        source=None,
        source_id=None,
        created_at="2026-10-13T00:00:00Z",
    )


class TestAllocateByDay:
    def test_duration_only_session(self):
        s = make_session(local_date="2026-10-13", duration_secs=5400)
        res = allocate_by_day(s)
        assert res == {"2026-10-13": 5400}

    def test_same_day_session(self):
        s = make_session(
            local_date="2026-10-13",
            start_utc="2026-10-13T10:00:00Z",
            end_utc="2026-10-13T11:00:00Z",
            duration_secs=3600,
            utc_offset_mins=0,
        )
        res = allocate_by_day(s)
        assert res == {"2026-10-13": 3600}

    def test_midnight_crossing_half_half(self):
        # 23:30 to 00:30 UTC = 1800s on 2026-10-13, 1800s on 2026-10-14
        s = make_session(
            local_date="2026-10-13",
            start_utc="2026-10-13T23:30:00Z",
            end_utc="2026-10-14T00:30:00Z",
            duration_secs=3600,
            utc_offset_mins=0,
        )
        res = allocate_by_day(s)
        assert res == {"2026-10-13": 1800, "2026-10-14": 1800}

    def test_midnight_crossing_with_offset(self):
        # Local time UTC+6:
        # Start: 2026-10-13T17:30:00Z (+6h = 2026-10-13 23:30:00 local)
        # End:   2026-10-13T18:30:00Z (+6h = 2026-10-14 00:30:00 local)
        s = make_session(
            local_date="2026-10-13",
            start_utc="2026-10-13T17:30:00Z",
            end_utc="2026-10-13T18:30:00Z",
            duration_secs=3600,
            utc_offset_mins=360,
        )
        res = allocate_by_day(s)
        assert res == {"2026-10-13": 1800, "2026-10-14": 1800}

    def test_span_over_three_days(self):
        # 2026-10-13 22:00:00 to 2026-10-15 02:00:00 (2h on day 1, 24h on day 2, 2h on day 3 = 28h total span)
        s = make_session(
            local_date="2026-10-13",
            start_utc="2026-10-13T22:00:00Z",
            end_utc="2026-10-15T02:00:00Z",
            duration_secs=28 * 3600,
            utc_offset_mins=0,
        )
        res = allocate_by_day(s)
        assert sum(res.values()) == 28 * 3600
        assert res["2026-10-13"] == 2 * 3600
        assert res["2026-10-14"] == 24 * 3600
        assert res["2026-10-15"] == 2 * 3600

    def test_randomised_sum_invariance(self):
        """Allocations must always sum to duration_secs exactly."""
        base = datetime(2026, 10, 10, 0, 0, 0, tzinfo=timezone.utc)
        rng = random.Random(42)

        for _ in range(100):
            start_offset_secs = rng.randint(0, 86400 * 5)
            span_secs = rng.randint(60, 86400 * 3)
            # Duration may be less than or equal to span (due to pauses)
            duration_secs = rng.randint(30, span_secs)
            offset_mins = rng.choice([-300, 0, 360, 480])

            st = base + timedelta(seconds=start_offset_secs)
            et = st + timedelta(seconds=span_secs)

            st_str = st.strftime("%Y-%m-%dT%H:%M:%SZ")
            et_str = et.strftime("%Y-%m-%dT%H:%M:%SZ")

            s = make_session(
                start_utc=st_str,
                end_utc=et_str,
                duration_secs=duration_secs,
                utc_offset_mins=offset_mins,
            )
            res = allocate_by_day(s)
            assert sum(res.values()) == duration_secs
