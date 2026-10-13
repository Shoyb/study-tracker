"""Statistics and task ordering rules.

Pure functions – no Qt, no SQL.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from study_tracker.domain.allocation import allocate_by_day

if TYPE_CHECKING:
    from study_tracker.db.sessions_repo import Session
    from study_tracker.db.tasks_repo import Task

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_STATUS_ORDER = {"in_progress": 0, "todo": 1, "done": 2}


def _dates_in_range(start: str, end: str) -> Iterable[str]:
    """Yield every ISO calendar date in the inclusive range."""
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    while start_date <= end_date:
        yield start_date.isoformat()
        start_date += timedelta(days=1)


def daily_totals(
    sessions: Iterable[Session], start: str, end: str, cutoff_minutes: int = 180
) -> dict[str, int]:
    """Return allocated study seconds for every day in an inclusive range.

    ``allocate_by_day`` is intentionally the only place where a session is
    split at the study-day boundary. Keeping that rule here makes all reports
    agree exactly.
    """
    totals = {day: 0 for day in _dates_in_range(start, end)}
    for session in sessions:
        for day, seconds in allocate_by_day(session, cutoff_minutes).items():
            if day in totals:
                totals[day] += seconds
    return totals


def daily_average(totals: dict[str, int], first_recorded_date: str | None = None) -> float:
    """Return the average including zero days, but never before study began."""
    if not totals:
        return 0.0
    dates = sorted(totals)
    if first_recorded_date:
        dates = [day for day in dates if day >= first_recorded_date]
    if not dates:
        return 0.0
    return sum(totals[day] for day in dates) / len(dates)


def weekly_totals(totals: dict[str, int], week_start: str = "monday") -> dict[str, int]:
    """Group daily totals by the configured first day of the week."""
    starts = {"monday": 0, "saturday": 5}
    if week_start not in starts:
        raise ValueError("week_start must be 'monday' or 'saturday'")
    result: dict[str, int] = {}
    for day, seconds in totals.items():
        current = date.fromisoformat(day)
        week_day = current - timedelta(days=(current.weekday() - starts[week_start]) % 7)
        key = week_day.isoformat()
        result[key] = result.get(key, 0) + seconds
    return dict(sorted(result.items()))


def current_streak(totals: dict[str, int], *, today: str, threshold_secs: int) -> int:
    """Count qualifying consecutive days, without letting unfinished today break it."""
    day = date.fromisoformat(today)
    if totals.get(today, 0) < threshold_secs:
        day -= timedelta(days=1)
    streak = 0
    while totals.get(day.isoformat(), 0) >= threshold_secs:
        streak += 1
        day -= timedelta(days=1)
    return streak


def longest_streak(totals: dict[str, int], *, threshold_secs: int) -> int:
    """Return the longest run of qualifying calendar days."""
    longest = current = 0
    for day in sorted(totals):
        if totals[day] >= threshold_secs:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _allocation_overlaps_range(allocation: dict[str, int], start: str, end: str) -> bool:
    return any(start <= day <= end and seconds > 0 for day, seconds in allocation.items())


def session_count(
    sessions: Iterable[Session], start: str, end: str, cutoff_minutes: int = 180
) -> int:
    """Count a session once when any allocated second falls in the range."""
    return sum(
        _allocation_overlaps_range(allocate_by_day(session, cutoff_minutes), start, end)
        for session in sessions
    )


def subject_totals(
    sessions: Iterable[Session], start: str, end: str, cutoff_minutes: int = 180
) -> dict[int, int]:
    """Return allocated time per subject for an inclusive date range."""
    result: dict[int, int] = {}
    for session in sessions:
        seconds = sum(
            value
            for day, value in allocate_by_day(session, cutoff_minutes).items()
            if start <= day <= end
        )
        if seconds:
            result[session.subject_id] = result.get(session.subject_id, 0) + seconds
    return result


def task_completion_rate(
    tasks: Iterable[Task], start: str, end: str
) -> tuple[int, int, float | None]:
    """Return completed count, open-in-period count, and completion percentage."""
    completed = 0
    open_count = 0
    for task in tasks:
        created_day = task.created_at[:10]
        completed_day = task.completed_at[:10] if task.completed_at else None
        if start <= (completed_day or "") <= end:
            completed += 1
        if created_day <= end and (completed_day is None or completed_day >= start):
            open_count += 1
    percentage = (completed * 100 / open_count) if open_count else None
    return completed, open_count, percentage


def is_overdue(task: Task, today: str) -> bool:
    """Return True if the task has a due date before today and is not done."""
    if not task.due_date or task.status == "done":
        return False
    return task.due_date < today


def overdue_days(task: Task, today: str) -> int:
    """Return number of days overdue (positive int), or 0 if not overdue."""
    if not is_overdue(task, today) or not task.due_date:
        return 0
    try:
        due_dt = datetime.strptime(task.due_date, "%Y-%m-%d")
        today_dt = datetime.strptime(today, "%Y-%m-%d")
        return max(0, (today_dt - due_dt).days)
    except (ValueError, TypeError):
        return 0


def next_up(tasks: list[Task], today: str, limit: int = 5) -> list[Task]:
    """Return top open tasks ordered by the 5 rules from section F:

    1. Overdue tasks first (most overdue first: earliest due date).
    2. Tasks with a due date (soonest first).
    3. Higher priority before lower (high > medium > low).
    4. In progress before To do.
    5. Oldest created first (earliest created_at).
    """
    open_tasks = [t for t in tasks if t.status != "done" and not t.archived]

    def sort_key(t: Task) -> tuple:
        overdue = is_overdue(t, today)
        has_due = t.due_date is not None

        # Rule 1 & 2:
        # Group 0: overdue (ordered by due_date ascending)
        # Group 1: non-overdue with due_date (ordered by due_date ascending)
        # Group 2: no due date
        if overdue:
            due_group = 0
            due_val = t.due_date or ""
        elif has_due:
            due_group = 1
            due_val = t.due_date or ""
        else:
            due_group = 2
            due_val = "9999-99-99"

        # Rule 3: Priority
        prio_val = _PRIORITY_ORDER.get(t.priority, 1)

        # Rule 4: Status (in_progress before todo)
        status_val = _STATUS_ORDER.get(t.status, 1)

        # Rule 5: created_at ascending
        created_val = t.created_at

        return (due_group, due_val, prio_val, status_val, created_val)

    sorted_tasks = sorted(open_tasks, key=sort_key)
    return sorted_tasks[:limit]


def estimated_work_remaining(tasks: list[Task]) -> tuple[int, int]:
    """Calculate estimated work remaining for open, non-archived tasks.

    Returns:
        (total_remaining_seconds, count_of_tasks_without_estimate)
    """
    open_tasks = [t for t in tasks if t.status != "done" and not t.archived]
    remaining_secs = 0
    no_estimate_count = 0

    for t in open_tasks:
        if t.estimate_secs is not None and t.estimate_secs > 0:
            rem = max(0, t.estimate_secs - t.time_spent_secs)
            remaining_secs += rem
        else:
            no_estimate_count += 1

    return remaining_secs, no_estimate_count
