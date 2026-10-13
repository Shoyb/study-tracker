"""Database-backed statistics assembled from the shared domain functions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from study_tracker.db import sessions_repo, settings_repo, tasks_repo
from study_tracker.domain import allocation, stats


@dataclass(frozen=True)
class DashboardStats:
    today_secs: int
    week_secs: int
    month_secs: int
    daily_average_secs: float
    session_count: int
    current_streak: int
    completed_tasks: int
    open_tasks: int
    completion_rate: float | None
    daily: dict[str, int]
    daily_session_counts: dict[str, int]


def _first_recorded_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MIN(local_date) AS value FROM sessions").fetchone()
    return row["value"] if row and row["value"] else None


def _sessions_for_range(
    conn: sqlite3.Connection, start: str, end: str
) -> list[sessions_repo.Session]:
    # Timed sessions may have begun the prior evening and continue after midnight.
    previous_day = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    return sessions_repo.get_all(conn, date_from=previous_day, date_to=end)


def dashboard_stats(
    conn: sqlite3.Connection, *, today: str, range_days: int = 30
) -> DashboardStats:
    """Build all Dashboard values without duplicating allocation logic."""
    range_days = max(1, range_days)
    end = date.fromisoformat(today)
    start = end - timedelta(days=range_days - 1)
    start_text, end_text = start.isoformat(), end.isoformat()
    cutoff_minutes = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")
    sessions = _sessions_for_range(conn, start_text, end_text)
    daily = stats.daily_totals(sessions, start_text, end_text, cutoff_minutes)
    daily_session_counts = {day: 0 for day in daily}
    for session in sessions:
        for day, seconds in allocation.allocate_by_day(session, cutoff_minutes).items():
            if day in daily_session_counts and seconds:
                daily_session_counts[day] += 1

    first_day = _first_recorded_date(conn)
    average = stats.daily_average(daily, first_day)
    week_start = settings_repo.get(conn, "week_start") or "monday"
    weeks = stats.weekly_totals(daily, week_start)
    current_week = weeks.get(
        next(reversed(weeks)) if weeks else today, 0
    )
    month_start = end.replace(day=1).isoformat()
    month_daily = stats.daily_totals(
        _sessions_for_range(conn, month_start, end_text), month_start, end_text, cutoff_minutes
    )
    threshold_hours = float(settings_repo.get(conn, "streak_threshold_hrs") or "0.5")
    tasks = tasks_repo.get_all(conn, include_archived=True)
    completed, open_count, rate = stats.task_completion_rate(tasks, start_text, end_text)

    return DashboardStats(
        today_secs=daily[today],
        week_secs=current_week,
        month_secs=sum(month_daily.values()),
        daily_average_secs=average,
        session_count=stats.session_count(sessions, start_text, end_text, cutoff_minutes),
        current_streak=stats.current_streak(
            daily, today=today, threshold_secs=round(threshold_hours * 3600)
        ),
        completed_tasks=completed,
        open_tasks=open_count,
        completion_rate=rate,
        daily=daily,
        daily_session_counts=daily_session_counts,
    )


def totals_for_range(
    conn: sqlite3.Connection, *, start: str, end: str
) -> dict[str, int]:
    """Return zero-filled daily totals for a Calendar or a future chart."""
    cutoff_minutes = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")
    return stats.daily_totals(
        _sessions_for_range(conn, start, end), start, end, cutoff_minutes
    )


def task_time_for_range(
    conn: sqlite3.Connection, *, start: str, end: str
) -> dict[int, int]:
    """Return seconds allocated to each task in a date range."""
    totals: dict[int, int] = {}
    cutoff_minutes = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")
    for session in _sessions_for_range(conn, start, end):
        if session.task_id is None:
            continue
        seconds = sum(
            value
            for day, value in allocation.allocate_by_day(session, cutoff_minutes).items()
            if start <= day <= end
        )
        if seconds:
            totals[session.task_id] = totals.get(session.task_id, 0) + seconds
    return totals


def completions_by_week(
    conn: sqlite3.Connection, *, start: str, end: str, week_start: str
) -> dict[str, int]:
    """Count tasks completed in each configured week in a date range."""
    daily = {day: 0 for day in stats.daily_totals([], start, end)}
    for task in tasks_repo.get_all(conn, include_archived=True):
        if task.completed_at and start <= task.completed_at[:10] <= end:
            daily[task.completed_at[:10]] += 1
    return stats.weekly_totals(daily, week_start)
