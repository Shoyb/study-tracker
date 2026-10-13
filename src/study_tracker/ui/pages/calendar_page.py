"""Monthly calendar of daily study totals."""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.formatting import format_duration
from study_tracker.services import session_service, subject_service, task_service
from study_tracker.services.stats_service import totals_for_range
from study_tracker.ui.signals import AppSignals


class CalendarPage(QWidget):
    """A clickable month grid with a compact selected-day session list."""

    def __init__(self, conn: sqlite3.Connection, signals: AppSignals, clock, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._clock = clock
        today = date.fromisoformat(clock.local_date())
        self._year, self._month = today.year, today.month
        self._selected_day = today.isoformat()
        self._build_ui()
        signals.sessions_changed.connect(self.refresh)
        signals.day_changed.connect(self._today)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        controls = QHBoxLayout()
        previous = QPushButton("‹ Previous")
        previous.clicked.connect(lambda: self._shift_month(-1))
        self._title = QLabel()
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        following = QPushButton("Next ›")
        following.clicked.connect(lambda: self._shift_month(1))
        today = QPushButton("Today")
        today.clicked.connect(self._today)
        controls.addWidget(previous)
        controls.addWidget(self._title, 1)
        controls.addWidget(today)
        controls.addWidget(following)
        root.addLayout(controls)

        self._grid = QTableWidget(6, 7)
        self._grid.setHorizontalHeaderLabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        self._grid.verticalHeader().hide()
        self._grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._grid.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._grid.cellClicked.connect(self._select_cell)
        root.addWidget(self._grid)

        self._day_title = QLabel()
        self._day_title.setStyleSheet("font-size: 13pt; font-weight: bold; padding-top: 8px;")
        root.addWidget(self._day_title)
        self._sessions = QTableWidget(0, 4)
        self._sessions.setHorizontalHeaderLabels(["Time", "Duration", "Subject", "Task"])
        self._sessions.verticalHeader().hide()
        self._sessions.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._sessions)

    def _shift_month(self, amount: int) -> None:
        self._month += amount
        if self._month == 0:
            self._year, self._month = self._year - 1, 12
        elif self._month == 13:
            self._year, self._month = self._year + 1, 1
        self._selected_day = date(self._year, self._month, 1).isoformat()
        self.refresh()

    def _today(self) -> None:
        value = date.fromisoformat(self._clock.local_date())
        self._year, self._month = value.year, value.month
        self._selected_day = value.isoformat()
        self.refresh()

    def _select_cell(self, row: int, column: int) -> None:
        item = self._grid.item(row, column)
        if item and item.data(Qt.ItemDataRole.UserRole):
            self._selected_day = item.data(Qt.ItemDataRole.UserRole)
            self._refresh_sessions()

    def refresh(self) -> None:
        first = date(self._year, self._month, 1)
        last = date(self._year, self._month, calendar.monthrange(self._year, self._month)[1])
        totals = totals_for_range(self._conn, start=first.isoformat(), end=last.isoformat())
        self._title.setText(first.strftime("%B %Y"))
        self._grid.clearContents()
        for day in range(1, last.day + 1):
            value = date(self._year, self._month, day)
            day_text = value.isoformat()
            seconds = totals[day_text]
            item = QTableWidgetItem(f"{day}\n{format_duration(seconds) if seconds else ''}")
            item.setData(Qt.ItemDataRole.UserRole, day_text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            if seconds:
                item.setBackground(Qt.GlobalColor.cyan)
            self._grid.setItem((first.weekday() + day - 1) // 7, value.weekday(), item)
        self._refresh_sessions()

    def _refresh_sessions(self) -> None:
        sessions = session_service.get_all(
            self._conn, date_from=self._selected_day, date_to=self._selected_day
        )
        subjects = {
            s.id: s.name for s in subject_service.get_all(self._conn, include_archived=True)
        }
        tasks = {t.id: t.title for t in task_service.get_all(self._conn, include_archived=True)}
        total = format_duration(sum(session.duration_secs for session in sessions))
        self._day_title.setText(f"Sessions for {self._selected_day} ({total})")
        self._sessions.setRowCount(len(sessions))
        for row, session in enumerate(sessions):
            time = session.start_utc[11:16] if session.start_utc else "Duration only"
            self._sessions.setItem(row, 0, QTableWidgetItem(time))
            self._sessions.setItem(row, 1, QTableWidgetItem(format_duration(session.duration_secs)))
            subject = subjects.get(session.subject_id, "Unknown")
            self._sessions.setItem(row, 2, QTableWidgetItem(subject))
            self._sessions.setItem(row, 3, QTableWidgetItem(tasks.get(session.task_id, "—")))
