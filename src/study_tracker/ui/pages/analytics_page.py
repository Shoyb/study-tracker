"""Detailed chart views built from the shared statistics service."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from study_tracker.charts.subject_chart import draw_subject_distribution
from study_tracker.charts.task_charts import (
    draw_completions,
    draw_estimate_vs_actual,
    draw_task_time,
)
from study_tracker.charts.weekly_trend import draw_week_overlay, draw_weekly_trend
from study_tracker.db import settings_repo, subjects_repo, tasks_repo
from study_tracker.services.stats_service import (
    completions_by_week,
    task_time_for_range,
    totals_for_range,
)
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.mpl_canvas import MplCanvas


class AnalyticsPage(QWidget):
    """Time, subject, and task analytics with one shared date range."""

    def __init__(self, conn: sqlite3.Connection, signals: AppSignals, clock, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._clock = clock
        self._range = QComboBox()
        self._overlay = QComboBox()
        self._build_ui()
        for signal in (signals.sessions_changed, signals.tasks_changed, signals.subjects_changed):
            signal.connect(self.refresh)
        signals.settings_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("<h2>Analytics</h2>"))
        controls.addStretch()
        for label, days in (("30 days", 30), ("90 days", 90), ("180 days", 180)):
            self._range.addItem(label, days)
        self._range.currentIndexChanged.connect(self.refresh)
        controls.addWidget(QLabel("Range:"))
        controls.addWidget(self._range)
        root.addLayout(controls)

        tabs = QTabWidget()
        time_tab = QWidget()
        time_layout = QVBoxLayout(time_tab)
        self._trend = MplCanvas(height=3.2)
        self._overlay.addItems(("Daily trend", "Week overlay"))
        self._overlay.currentIndexChanged.connect(self.refresh)
        time_layout.addWidget(self._overlay)
        time_layout.addWidget(self._trend)
        tabs.addTab(time_tab, "Time")

        subjects_tab = QWidget()
        subjects_layout = QVBoxLayout(subjects_tab)
        self._subjects = MplCanvas(height=4.2)
        subjects_layout.addWidget(self._subjects)
        tabs.addTab(subjects_tab, "Subjects")

        tasks_tab = QWidget()
        tasks_layout = QVBoxLayout(tasks_tab)
        self._task_time = MplCanvas(height=3.0)
        self._estimates = MplCanvas(height=3.0)
        self._completions = MplCanvas(height=2.5)
        self._estimate_note = QLabel()
        tasks_layout.addWidget(self._task_time)
        tasks_layout.addWidget(self._estimates)
        tasks_layout.addWidget(self._estimate_note)
        tasks_layout.addWidget(self._completions)
        tabs.addTab(tasks_tab, "Tasks")
        root.addWidget(tabs)

    def _dates(self) -> tuple[str, str]:
        end = date.fromisoformat(self._clock.local_date())
        start = end - timedelta(days=int(self._range.currentData()) - 1)
        return start.isoformat(), end.isoformat()

    def refresh(self) -> None:
        start, end = self._dates()
        totals = totals_for_range(self._conn, start=start, end=end)
        if self._overlay.currentIndex() == 0:
            self._trend.redraw(draw_weekly_trend, totals)
        else:
            week_start = settings_repo.get(self._conn, "week_start") or "monday"
            self._trend.redraw(draw_week_overlay, totals, week_start)

        subject_map = {subject.id: subject for subject in subjects_repo.get_all(self._conn)}
        subject_values = []
        from study_tracker.db import sessions_repo
        from study_tracker.domain.stats import subject_totals

        sessions = sessions_repo.get_all(
            self._conn,
            date_from=(date.fromisoformat(start) - timedelta(days=1)).isoformat(),
            date_to=end,
        )
        for subject_id, seconds in subject_totals(sessions, start, end).items():
            subject = subject_map.get(subject_id)
            if subject:
                subject_values.append((subject.name, seconds, subject.colour))
        self._subjects.redraw(draw_subject_distribution, subject_values)

        task_map = {task.id: task for task in tasks_repo.get_all(self._conn, include_archived=True)}
        task_seconds = task_time_for_range(self._conn, start=start, end=end)
        colours = {subject.id: subject.colour for subject in subject_map.values()}
        task_values = [
            (task.title, seconds, colours.get(task.subject_id, "#1976D2"))
            for task_id, seconds in task_seconds.items()
            if (task := task_map.get(task_id)) is not None
        ]
        self._task_time.redraw(draw_task_time, task_values)
        estimates = [
            (task.title, task.estimate_secs or 0, task_seconds.get(task.id, 0))
            for task in task_map.values()
            if not task.archived
        ]
        without_estimate = self._estimates.redraw(draw_estimate_vs_actual, estimates)
        self._estimate_note.setText(f"{without_estimate} open task(s) have no estimate.")
        week_start = settings_repo.get(self._conn, "week_start") or "monday"
        completions = completions_by_week(self._conn, start=start, end=end, week_start=week_start)
        self._completions.redraw(draw_completions, completions)
