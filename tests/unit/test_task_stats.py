"""Unit tests for domain/stats.py."""

from __future__ import annotations

import pytest

from study_tracker.db.tasks_repo import Task
from study_tracker.domain.stats import estimated_work_remaining, is_overdue, next_up, overdue_days


def make_task(
    id: int,
    title: str = "T",
    status: str = "todo",
    priority: str = "medium",
    due_date: str | None = None,
    estimate_secs: int | None = None,
    time_spent_secs: int = 0,
    created_at: str = "2026-10-01T00:00:00Z",
    archived: bool = False,
) -> Task:
    return Task(
        id=id,
        subject_id=1,
        title=title,
        status=status,
        priority=priority,
        archived=archived,
        due_date=due_date,
        estimate_secs=estimate_secs,
        notes="",
        completed_at=None,
        created_at=created_at,
        time_spent_secs=time_spent_secs,
    )


class TestOverdue:
    def test_overdue_true(self):
        t = make_task(1, due_date="2026-10-10")
        assert is_overdue(t, today="2026-10-13") is True
        assert overdue_days(t, today="2026-10-13") == 3

    def test_due_today_not_overdue(self):
        t = make_task(1, due_date="2026-10-13")
        assert is_overdue(t, today="2026-10-13") is False
        assert overdue_days(t, today="2026-10-13") == 0

    def test_done_not_overdue(self):
        t = make_task(1, status="done", due_date="2026-10-10")
        assert is_overdue(t, today="2026-10-13") is False
        assert overdue_days(t, today="2026-10-13") == 0

    def test_no_due_date_not_overdue(self):
        t = make_task(1, due_date=None)
        assert is_overdue(t, today="2026-10-13") is False


class TestNextUpOrdering:
    def test_ordering_rules(self):
        today = "2026-10-13"
        # 1. Overdue task (due 2026-10-10)
        t_overdue_1 = make_task(1, title="Overdue 1", due_date="2026-10-10", priority="low")
        # Overdue earlier (due 2026-10-05) -> more overdue!
        t_overdue_2 = make_task(2, title="Overdue 2", due_date="2026-10-05", priority="low")
        # 2. Due soon (due 2026-10-14)
        t_due_soon = make_task(3, title="Due soon", due_date="2026-10-14", priority="low")
        # 3. High priority, no due date
        t_high = make_task(4, title="High prio", priority="high")
        # 4. In progress vs todo (both medium priority)
        t_in_prog = make_task(5, title="In progress", status="in_progress", priority="medium")
        t_todo = make_task(6, title="Todo", status="todo", priority="medium", created_at="2026-10-02T00:00:00Z")
        # 5. Oldest created first
        t_older = make_task(7, title="Older", created_at="2026-09-01T00:00:00Z")

        # Done task should be excluded
        t_done = make_task(8, title="Done", status="done", due_date="2026-10-01")
        # Archived task should be excluded
        t_archived = make_task(9, title="Archived", archived=True, due_date="2026-10-01")

        all_tasks = [t_todo, t_high, t_archived, t_due_soon, t_overdue_1, t_done, t_overdue_2, t_in_prog, t_older]
        ordered = next_up(all_tasks, today=today, limit=5)

        # Expected top 5:
        # 1. t_overdue_2 (most overdue: 2026-10-05)
        # 2. t_overdue_1 (overdue: 2026-10-10)
        # 3. t_due_soon (due soon: 2026-10-14)
        # 4. t_high (high priority)
        # 5. t_in_prog (in_progress before todo)
        assert [t.id for t in ordered] == [2, 1, 3, 4, 5]


class TestEstimatedWorkRemaining:
    def test_calculation(self):
        t1 = make_task(1, estimate_secs=3600, time_spent_secs=1200)  # remaining 2400
        t2 = make_task(2, estimate_secs=1800, time_spent_secs=2000)  # remaining 0 (exceeded)
        t3 = make_task(3, estimate_secs=None)                         # no estimate
        t4 = make_task(4, status="done", estimate_secs=3600, time_spent_secs=0)  # done -> ignored
        t5 = make_task(5, archived=True, estimate_secs=3600, time_spent_secs=0)  # archived -> ignored

        rem_secs, no_est = estimated_work_remaining([t1, t2, t3, t4, t5])
        assert rem_secs == 2400
        assert no_est == 1
