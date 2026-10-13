"""Sectioned access to existing record editors."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.formatting import format_duration
from study_tracker.services import day_plan_service
from study_tracker.ui.dialogs.day_plan_dialog import DayPlanDialog
from study_tracker.ui.pages.calendar_page import CalendarPage
from study_tracker.ui.pages.exams_page import ExamsPage
from study_tracker.ui.pages.history_page import HistoryPage
from study_tracker.ui.pages.subjects_page import SubjectsPage
from study_tracker.ui.pages.tasks_page import TasksPage
from study_tracker.ui.signals import AppSignals


class RecordsPage(QWidget):
    """Group session, task, subject, exam, calendar, and plan records."""

    def __init__(self, conn: sqlite3.Connection, signals: AppSignals, clock, parent=None) -> None:
        super().__init__(parent)
        self._tabs = QTabWidget()
        self._history_page = HistoryPage(conn, signals, clock)
        self._tasks_page = TasksPage(conn, signals, clock)
        self._subjects_page = SubjectsPage(conn, signals, clock)
        self._exams_page = ExamsPage(conn, signals, clock)
        self._calendar_page = CalendarPage(conn, signals, clock)
        self._day_plans_page = DailyPlansPage(conn, signals, clock)
        for label, page in (
            ("Sessions", self._history_page),
            ("Tasks", self._tasks_page),
            ("Subjects", self._subjects_page),
            ("Exams", self._exams_page),
            ("Calendar", self._calendar_page),
            ("Daily plans", self._day_plans_page),
        ):
            self._tabs.addTab(page, label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

    def show_history_date(self, local_date: str) -> None:
        self._tabs.setCurrentWidget(self._history_page)
        self._history_page.show_date(local_date)


class DailyPlansPage(QWidget):
    """Browse and edit saved per-day plans."""

    def __init__(self, conn: sqlite3.Connection, signals: AppSignals, clock, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._signals = signals
        self._clock = clock
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        header = QHBoxLayout()
        header.addWidget(QLabel("<h2>Daily plans</h2>"))
        header.addStretch()
        self._edit_button = QPushButton("Edit")
        self._edit_button.setEnabled(False)
        self._edit_button.clicked.connect(self._edit_selected)
        header.addWidget(self._edit_button)
        root.addLayout(header)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["Study day", "Study target", "Exam target", "Rest day"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.itemSelectionChanged.connect(self._sync_edit_button)
        self._table.doubleClicked.connect(self._edit_selected)
        root.addWidget(self._table)
        signals.settings_changed.connect(self.refresh)
        signals.exam_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        plans = day_plan_service.get_saved_day_plans(self._conn)
        self._table.setRowCount(len(plans))
        for row, plan in enumerate(plans):
            values = (
                plan.local_date,
                "Rest day" if plan.is_rest_day else format_duration(plan.study_goal_secs or 0),
                self._format_exam_goal(plan.exam_goal_type, plan.exam_goal_value),
                "Yes" if plan.is_rest_day else "No",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, plan.local_date)
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()
        self._sync_edit_button()

    def _format_exam_goal(self, goal_type: str | None, value: int | None) -> str:
        if not goal_type or goal_type == "none":
            return "None"
        units = {"count": "exams", "minutes": "minutes", "questions": "questions"}
        return f"{value or 0} {units.get(goal_type, goal_type)}"

    def _sync_edit_button(self) -> None:
        self._edit_button.setEnabled(self._table.currentRow() >= 0)

    def _edit_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        study_day = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        dialog = DayPlanDialog(self._conn, study_day, self._clock, self)
        if dialog.exec() == DayPlanDialog.DialogCode.Accepted:
            self._signals.settings_changed.emit()
            self._signals.exam_changed.emit()
