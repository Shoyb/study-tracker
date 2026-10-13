"""The at-a-glance study Dashboard."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from study_tracker.charts.daily_bar import draw_daily_bars
from study_tracker.core.formatting import format_duration
from study_tracker.db import sessions_repo, settings_repo
from study_tracker.domain.allocation import allocate_by_day
from study_tracker.domain.day import day_bounds
from study_tracker.services import calendar_service, task_service
from study_tracker.services.day_plan_service import exam_goal_progress
from study_tracker.services.stats_service import dashboard_stats
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.mpl_canvas import MplCanvas


class DashboardPage(QWidget):
    """Summary tiles calculated by the shared statistics service."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        signals: AppSignals,
        clock,
        on_day_selected: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._clock = clock
        self._on_day_selected = on_day_selected
        self._range = QComboBox()
        self._tiles: dict[str, QLabel] = {}
        self._build_ui()
        signals.sessions_changed.connect(self.refresh)
        signals.tasks_changed.connect(self.refresh)
        signals.settings_changed.connect(self.refresh)
        signals.calendar_changed.connect(self.refresh)
        signals.exam_changed.connect(self.refresh)
        signals.day_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        header = QHBoxLayout()
        header.addWidget(QLabel("<h2>Dashboard</h2>"))
        header.addStretch()
        header.addWidget(QLabel("Summary range:"))
        ranges = (
            ("Last 7 days", 7),
            ("Last 14 days", 14),
            ("Last 30 days", 30),
            ("Last 90 days", 90),
        )
        for label, days in ranges:
            self._range.addItem(label, days)
        self._range.setCurrentIndex(2)
        self._range.currentIndexChanged.connect(self.refresh)
        header.addWidget(self._range)
        root.addLayout(header)
        self._study_day = QLabel()
        root.addWidget(self._study_day)
        self._today_agenda = QLabel()
        self._today_agenda.setWordWrap(True)
        root.addWidget(self._today_agenda)
        self._exam_goal = QLabel()
        root.addWidget(self._exam_goal)

        grid = QGridLayout()
        labels = (
            ("today", "Today"), ("week", "This week"), ("month", "This month"),
            ("average", "Daily average"), ("sessions", "Sessions in range"),
            ("streak", "Current streak"), ("tasks", "Tasks completed"), ("rate", "Completion rate"),
            ("pomodoros", "Pomodoros today"),
        )
        for index, (key, title) in enumerate(labels):
            tile = QLabel()
            tile.setMinimumHeight(92)
            tile.setStyleSheet(
                "background: #1F2A32; border: 1px solid #3A4F5F; border-radius: 10px; "
                "padding: 12px; font-size: 11pt; color: #E6EDF3;"
            )
            tile.setTextFormat(Qt.TextFormat.RichText)
            self._tiles[key] = tile
            grid.addWidget(tile, index // 4, index % 4)
            tile.setText(f"<span style='color:#52606D'>{title}</span><br><b>—</b>")
        root.addLayout(grid)
        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #D9E4EE; padding-top: 12px;")
        root.addWidget(self._detail)
        self._daily_chart = MplCanvas(height=2.8)
        self._daily_chart.setStyleSheet(
            "background: #1F2A32; border: 1px solid #3A4F5F; border-radius: 10px;"
        )
        root.addWidget(self._daily_chart)
        root.addStretch()

    def refresh(self) -> None:
        if not self._conn:
            return
        cutoff_minutes = int(settings_repo.get(self._conn, "day_cutoff_minutes") or "180")
        now_local = self._clock.local_datetime()
        _, day_end = day_bounds(self._clock.local_date(), cutoff_minutes)
        remaining = max(0, int((day_end - now_local).total_seconds()))
        self._study_day.setText(
            f"Study day {now_local.strftime('%a %d %b')}, ends at "
            f"{cutoff_minutes // 60:02d}:{cutoff_minutes % 60:02d} "
            f"(in {format_duration(remaining)})"
        )
        today = self._clock.local_date()
        todays_tasks = [
            task.title
            for task in task_service.get_all(self._conn, include_archived=False)
            if task.status != "done" and today in {task.due_date, task.scheduled_date}
        ]
        todays_items = calendar_service.get_items_for_date(self._conn, today, cutoff_minutes)
        exam_progress = exam_goal_progress(self._conn, today)
        agenda = [f"Task: {title}" for title in todays_tasks]
        agenda.extend(
            f"{item.kind.title()}: {item.title}"
            for item in todays_items
        )
        self._today_agenda.setText(
            "Today: " + ("  |  ".join(agenda) if agenda else "Nothing planned")
        )
        unit = {
            "count": "exams",
            "minutes": "minutes",
            "questions": "questions",
        }.get(exam_progress.goal.goal_type, "")
        self._exam_goal.setText(
            "Exam goal: disabled"
            if not unit
            else f"Exam goal: {exam_progress.completed} of "
            f"{exam_progress.goal.value} {unit}"
        )
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        pomodoro_sessions = sessions_repo.get_all(
            self._conn, date_from=yesterday, date_to=today
        )
        pomodoro_today = [
            allocate_by_day(session, cutoff_minutes).get(today, 0)
            for session in pomodoro_sessions
            if session.pomodoro_completed
        ]
        pomodoro_count = sum(seconds > 0 for seconds in pomodoro_today)
        pomodoro_seconds = sum(pomodoro_today)
        data = dashboard_stats(
            self._conn, today=self._clock.local_date(), range_days=int(self._range.currentData())
        )
        values = {
            "today": format_duration(data.today_secs),
            "week": format_duration(data.week_secs),
            "month": format_duration(data.month_secs),
            "average": format_duration(round(data.daily_average_secs)),
            "sessions": str(data.session_count),
            "streak": f"{data.current_streak} day{'s' if data.current_streak != 1 else ''}",
            "tasks": f"{data.completed_tasks} completed",
            "rate": "—" if data.completion_rate is None else f"{data.completion_rate:.0f}%",
            "pomodoros": f"{pomodoro_count} · {format_duration(pomodoro_seconds)}",
        }
        titles = {
            "today": "Today",
            "week": "This week",
            "month": "This month",
            "average": "Daily average",
            "sessions": "Sessions in range",
            "streak": "Current streak",
            "tasks": "Tasks completed",
            "rate": "Completion rate",
            "pomodoros": "Pomodoros today",
        }
        for key, value in values.items():
            text = f"<span style='color:#D9E4EE'>{titles[key]}</span><br><b>{value}</b>"
            self._tiles[key].setText(text)
        self._detail.setText(
            f"{data.open_tasks} task{'s' if data.open_tasks != 1 else ''} open in this period. "
            "See Analytics for subject and task comparisons."
        )
        axes, bars = self._daily_chart.redraw(
            draw_daily_bars, data.daily, self._clock.local_date()
        )
        dates = sorted(data.daily)
        labels = [
            f"{day}: {format_duration(data.daily[day])}, "
            f"{data.daily_session_counts[day]} session(s)"
            for day in dates
        ]
        self._daily_chart.enable_bar_hover(
            axes,
            bars,
            labels,
            on_click=lambda index: self._on_day_selected and self._on_day_selected(dates[index]),
        )
