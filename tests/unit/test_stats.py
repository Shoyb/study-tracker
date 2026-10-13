"""Unit tests for statistics and analytics calculations in domain/stats.py."""

from __future__ import annotations

from study_tracker.db.sessions_repo import Session
from study_tracker.db.tasks_repo import Task
from study_tracker.domain import stats


def make_session(
    id: int = 1,
    subject_id: int = 1,
    task_id: int | None = None,
    local_date: str = "2026-10-13",
    start_utc: str | None = None,
    end_utc: str | None = None,
    duration_secs: int = 3600,
    session_type: str = "timer",
    utc_offset_mins: int = 0,
) -> Session:
    return Session(
        id=id,
        uuid=f"uuid-{id}",
        subject_id=subject_id,
        task_id=task_id,
        local_date=local_date,
        start_utc=start_utc,
        end_utc=end_utc,
        duration_secs=duration_secs,
        session_type=session_type,
        notes="",
        utc_offset_mins=utc_offset_mins,
        created_at="2026-10-13T00:00:00Z",
        updated_at="2026-10-13T00:00:00Z",
    )


def make_task(
    id: int,
    created_at: str,
    completed_at: str | None = None,
    status: str = "todo",
) -> Task:
    return Task(
        id=id,
        subject_id=1,
        title=f"Task {id}",
        status=status,
        priority="medium",
        archived=False,
        due_date=None,
        estimate_secs=None,
        notes="",
        created_at=created_at,
        completed_at=completed_at,
        time_spent_secs=0,
        session_count=0,
    )


class TestDailyTotals:
    def test_daily_totals_fills_all_dates_with_zero(self):
        s1 = make_session(1, local_date="2026-10-10", duration_secs=3600)
        s2 = make_session(2, local_date="2026-10-12", duration_secs=1800)

        totals = stats.daily_totals([s1, s2], "2026-10-10", "2026-10-13")
        assert totals == {
            "2026-10-10": 3600,
            "2026-10-11": 0,
            "2026-10-12": 1800,
            "2026-10-13": 0,
        }

    def test_midnight_crossing_session_in_daily_totals(self):
        # 23:00 to 01:00 UTC = 1h on day 1, 1h on day 2
        s = make_session(
            1,
            local_date="2026-10-10",
            start_utc="2026-10-10T23:00:00Z",
            end_utc="2026-10-11T01:00:00Z",
            duration_secs=7200,
        )
        totals = stats.daily_totals([s], "2026-10-10", "2026-10-12", cutoff_minutes=0)
        assert totals["2026-10-10"] == 3600
        assert totals["2026-10-11"] == 3600
        assert totals["2026-10-12"] == 0


class TestDailyAverage:
    def test_average_includes_zero_days(self):
        totals = {
            "2026-10-10": 3600,
            "2026-10-11": 0,
            "2026-10-12": 1800,
            "2026-10-13": 0,
        }
        # 5400 secs / 4 days = 1350.0
        avg = stats.daily_average(totals)
        assert avg == 1350.0

    def test_first_recorded_date_rule(self):
        # Range is 2026-10-01 to 2026-10-04, but first recorded date was 2026-10-03
        totals = {
            "2026-10-01": 0,
            "2026-10-02": 0,
            "2026-10-03": 3600,
            "2026-10-04": 7200,
        }
        # Range restricted to 2 days (Oct 3 and Oct 4): (3600 + 7200) / 2 = 5400.0
        avg = stats.daily_average(totals, first_recorded_date="2026-10-03")
        assert avg == 5400.0

    def test_empty_totals_returns_zero(self):
        assert stats.daily_average({}) == 0.0


class TestWeeklyTotals:
    def test_weekly_totals_monday_start(self):
        # 2026-10-12 is Monday, 2026-10-18 is Sunday
        # 2026-10-19 is next Monday
        totals = {
            "2026-10-12": 1000,
            "2026-10-15": 2000,
            "2026-10-18": 500,
            "2026-10-19": 3000,
        }
        weeks = stats.weekly_totals(totals, week_start="monday")
        assert weeks["2026-10-12"] == 3500
        assert weeks["2026-10-19"] == 3000

    def test_weekly_totals_saturday_start(self):
        # 2026-10-10 is Saturday. 2026-10-10 through 2026-10-16 is one week.
        totals = {
            "2026-10-10": 1000,
            "2026-10-12": 2000,
            "2026-10-17": 5000,  # next Saturday
        }
        weeks = stats.weekly_totals(totals, week_start="saturday")
        assert weeks["2026-10-10"] == 3000
        assert weeks["2026-10-17"] == 5000


class TestStreaks:
    def test_streak_with_today_qualifying(self):
        # Threshold: 1800 (30 min)
        totals = {
            "2026-10-10": 2000,
            "2026-10-11": 2000,
            "2026-10-12": 2000,
            "2026-10-13": 2000,  # today qualifies
        }
        assert stats.current_streak(totals, today="2026-10-13", threshold_secs=1800) == 4

    def test_streak_with_today_pending(self):
        # Today does not qualify yet, but yesterday did -> streak continues through yesterday
        totals = {
            "2026-10-10": 2000,
            "2026-10-11": 2000,
            "2026-10-12": 2000,
            "2026-10-13": 500,  # today pending (< 1800)
        }
        assert stats.current_streak(totals, today="2026-10-13", threshold_secs=1800) == 3

    def test_streak_broken_when_yesterday_failed(self):
        totals = {
            "2026-10-10": 2000,
            "2026-10-11": 0,  # broke streak
            "2026-10-12": 0,  # broke streak
            "2026-10-13": 500,
        }
        assert stats.current_streak(totals, today="2026-10-13", threshold_secs=1800) == 0

    def test_longest_streak(self):
        totals = {
            "2026-10-01": 2000,
            "2026-10-02": 2000,
            "2026-10-03": 2000,
            "2026-10-04": 2000,
            "2026-10-05": 0,
            "2026-10-06": 2000,
            "2026-10-07": 2000,
        }
        assert stats.longest_streak(totals, threshold_secs=1800) == 4


class TestSessionCountAndSubjectTotals:
    def test_session_count_in_range(self):
        s1 = make_session(1, local_date="2026-10-10")
        s2 = make_session(2, local_date="2026-10-15")  # outside
        # s3 spans Oct 11 23:00 to Oct 12 01:00
        s3 = make_session(
            3,
            local_date="2026-10-11",
            start_utc="2026-10-11T23:00:00Z",
            end_utc="2026-10-12T01:00:00Z",
            duration_secs=7200,
        )
        count = stats.session_count([s1, s2, s3], "2026-10-10", "2026-10-12")
        assert count == 2  # s1 and s3

    def test_subject_totals_in_range(self):
        s1 = make_session(1, subject_id=1, local_date="2026-10-10", duration_secs=3600)
        s2 = make_session(2, subject_id=2, local_date="2026-10-10", duration_secs=1800)
        s3 = make_session(3, subject_id=1, local_date="2026-10-15", duration_secs=1000)

        subj_totals = stats.subject_totals([s1, s2, s3], "2026-10-10", "2026-10-12")
        assert subj_totals == {1: 3600, 2: 1800}


class TestTaskCompletionRate:
    def test_task_completion_rate(self):
        t1 = make_task(
            1, created_at="2026-10-01T00:00:00Z", completed_at="2026-10-10T12:00:00Z", status="done"
        )
        t2 = make_task(
            2, created_at="2026-10-05T00:00:00Z", completed_at=None, status="in_progress"
        )
        # t3 completed before range -> not open in range
        t3 = make_task(
            3, created_at="2026-09-01T00:00:00Z", completed_at="2026-09-15T00:00:00Z", status="done"
        )
        # t4 created after range -> not open in range
        t4 = make_task(4, created_at="2026-10-20T00:00:00Z", status="todo")

        comp, open_cnt, pct = stats.task_completion_rate(
            [t1, t2, t3, t4], "2026-10-01", "2026-10-15"
        )
        assert comp == 1
        assert open_cnt == 2
        assert pct == 50.0
