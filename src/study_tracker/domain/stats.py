"""Task analytics and ordering rules.

Pure functions – no Qt, no SQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from study_tracker.db.tasks_repo import Task

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_STATUS_ORDER = {"in_progress": 0, "todo": 1, "done": 2}


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
