"""Exam planning and results page."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.errors import AppError
from study_tracker.core.formatting import format_date, format_duration
from study_tracker.db import exams_repo
from study_tracker.services import exam_service
from study_tracker.ui.dialogs.exam_dialog import ExamDialog
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.confirm import warn


class ExamsPage(QWidget):
    def __init__(self, conn: sqlite3.Connection, signals: AppSignals, clock, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._signals = signals
        self._clock = clock
        self._build_ui()
        signals.exam_changed.connect(self.refresh)
        signals.sessions_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        header = QHBoxLayout()
        header.addWidget(QLabel("<h2>Exams</h2>"))
        header.addStretch()
        self._query = QLineEdit()
        self._query.setPlaceholderText("Search exams…")
        self._query.textChanged.connect(self.refresh)
        self._status = QComboBox()
        self._status.addItem("All exams", None)
        self._status.addItem("Upcoming", "planned")
        self._status.addItem("Completed", "completed")
        self._status.currentIndexChanged.connect(self.refresh)
        header.addWidget(self._query)
        header.addWidget(self._status)
        root.addLayout(header)

        actions = QHBoxLayout()
        for label, slot in (
            ("Add exam", self._add_exam),
            ("Plan exam", self._plan_exam),
            ("Edit", self._edit_exam),
            ("Duplicate", self._duplicate_exam),
            ("Delete", self._delete_exam),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch()
        root.addLayout(actions)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["Date", "Title", "Category", "Level", "Status", "Score", "Net accuracy", "Time"]
        )
        self._table.setColumnWidth(0, 115)
        self._table.setColumnWidth(1, 240)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.doubleClicked.connect(self._edit_exam)
        root.addWidget(self._table)
        root.addStretch()

    def _selected_exam(self):
        row = self._table.currentRow()
        if row < 0:
            return None
        exam_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        return exams_repo.get_by_id(self._conn, exam_id)

    def refresh(self) -> None:
        exams = exam_service.get_exams(
            self._conn,
            status=self._status.currentData(),
            query=self._query.text(),
        )
        categories = {
            int(row["id"]): str(row["name"])
            for row in exams_repo.lookup_values(
                self._conn, "exam_categories", include_archived=True
            )
        }
        levels = {
            int(row["id"]): str(row["name"])
            for row in exams_repo.lookup_values(self._conn, "exam_levels", include_archived=True)
        }
        self._table.setRowCount(len(exams))
        for row, exam in enumerate(exams):
            score = exam_service.score(exam)
            values = (
                format_date(exam.exam_date),
                exam.title,
                categories.get(exam.category_id, "—"),
                levels.get(exam.level_id, "—"),
                (
                    "Not recorded"
                    if exam.status == "planned" and exam.exam_date < self._clock.local_date()
                    else "Planned"
                    if exam.status == "planned"
                    else "Completed"
                ),
                (
                    f"{format_duration(0)}"
                    if score is None
                    else f"{format_milli(score.score_milli)} / {format_milli(score.full_milli)}"
                ),
                "—" if score is None else format_percentage(score.net_accuracy),
                format_duration(exam.taken_seconds or 0) if exam.taken_seconds else "—",
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, exam.id)
                if (
                    column == 4
                    and exam.status == "planned"
                    and exam.exam_date < self._clock.local_date()
                ):
                    item.setForeground(Qt.GlobalColor.red)
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()
        self._table.setColumnWidth(1, max(240, self._table.columnWidth(1)))

    def _add_exam(self) -> None:
        self._open_dialog(default_status="completed")

    def _plan_exam(self) -> None:
        self._open_dialog(default_status="planned")

    def _edit_exam(self) -> None:
        exam = self._selected_exam()
        if exam is not None:
            self._open_dialog(exam=exam)

    def _open_dialog(self, exam=None, default_status: str = "completed") -> None:
        dialog = ExamDialog(
            self._conn,
            self._clock,
            exam=exam,
            default_status=default_status,
            parent=self,
        )
        if dialog.exec() != ExamDialog.DialogCode.Accepted:
            return
        try:
            values = {
                "title": dialog.title,
                "exam_date": dialog.exam_date,
                "status": dialog.status,
                "category_id": dialog.category_id,
                "level_id": dialog.level_id,
                "allowed_seconds": dialog.allowed_seconds,
                "taken_seconds": dialog.taken_seconds,
                "notes": dialog.notes,
                "parts": dialog.parts,
                "count_as_study": dialog.count_as_study,
                "now_utc": self._clock.now_utc(),
            }
            if exam is None:
                exam_service.create_exam(self._conn, **values)
            else:
                exam_service.update_exam(self._conn, exam.id, **values)
            self._signals.exam_changed.emit()
            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot save exam", str(exc))
        except (ValueError, sqlite3.IntegrityError) as exc:
            warn(self, "Cannot save exam", str(exc))

    def _duplicate_exam(self) -> None:
        exam = self._selected_exam()
        if exam is None:
            return
        try:
            exam_service.duplicate_exam(
                self._conn,
                exam.id,
                new_date=self._clock.local_date(),
                now_utc=self._clock.now_utc(),
            )
            self._signals.exam_changed.emit()
        except AppError as exc:
            warn(self, "Cannot duplicate exam", str(exc))

    def _delete_exam(self) -> None:
        exam = self._selected_exam()
        if exam is None:
            return
        delete_linked = False
        if exam.session_id is not None:
            result = QMessageBox.question(
                self,
                "Delete exam",
                "Delete the linked study session too?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if result == QMessageBox.StandardButton.Cancel:
                return
            delete_linked = result == QMessageBox.StandardButton.Yes
        elif QMessageBox.question(
            self,
            "Delete exam",
            f"Delete '{exam.title}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            exam_service.delete_exam(
                self._conn,
                exam.id,
                delete_linked_session=delete_linked,
                now_utc=self._clock.now_utc(),
            )
            self._signals.exam_changed.emit()
            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot delete exam", str(exc))


def format_milli(value: int) -> str:
    from study_tracker.domain.exam_scoring import format_milli_marks

    return format_milli_marks(value)


def format_percentage(value) -> str:
    from study_tracker.domain.exam_scoring import format_percentage as format_value

    return format_value(value)
