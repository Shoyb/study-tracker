"""Editor for a calendar note or event."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from study_tracker.db.calendar_repo import CalendarItem


class CalendarItemDialog(QDialog):
    def __init__(
        self,
        conn: sqlite3.Connection,
        local_date: str,
        item: CalendarItem | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit calendar item" if item else "Add calendar item")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._kind = QComboBox()
        self._kind.addItem("Note", "note")
        self._kind.addItem("Event", "event")
        self._kind.currentIndexChanged.connect(self._update_time_fields)
        self._title = QLineEdit()
        self._body = QPlainTextEdit()
        self._body.setMaximumHeight(120)
        self._date = QDateEdit(QDate.fromString(local_date, "yyyy-MM-dd"))
        self._date.setCalendarPopup(True)
        self._start = QTimeEdit(QTime(9, 0))
        self._start.setDisplayFormat("HH:mm")
        self._end = QTimeEdit(QTime(10, 0))
        self._end.setDisplayFormat("HH:mm")
        form.addRow("Kind:", self._kind)
        form.addRow("Title:", self._title)
        form.addRow("Notes:", self._body)
        form.addRow("Study day:", self._date)
        form.addRow("Start:", self._start)
        form.addRow("End:", self._end)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if item is not None:
            self._kind.setCurrentIndex(self._kind.findData(item.kind))
            self._title.setText(item.title)
            self._body.setPlainText(item.notes)
            self._date.setDate(QDate.fromString(item.local_date, "yyyy-MM-dd"))
            if item.start_time:
                self._start.setTime(QTime.fromString(item.start_time, "HH:mm"))
            if item.end_time:
                self._end.setTime(QTime.fromString(item.end_time, "HH:mm"))
        self._update_time_fields()

    def _update_time_fields(self) -> None:
        is_event = self._kind.currentData() == "event"
        self._start.setVisible(is_event)
        self._end.setVisible(is_event)

    @property
    def kind(self) -> str:
        return self._kind.currentData()

    @property
    def title(self) -> str:
        return self._title.text().strip()

    @property
    def notes(self) -> str:
        return self._body.toPlainText().strip()

    @property
    def local_date(self) -> str:
        return self._date.date().toString("yyyy-MM-dd")

    @property
    def start_time(self) -> str | None:
        return self._start.time().toString("HH:mm") if self.kind == "event" else None

    @property
    def end_time(self) -> str | None:
        return self._end.time().toString("HH:mm") if self.kind == "event" else None
