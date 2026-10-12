"""Add / Edit task dialog."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.errors import AppError
from study_tracker.db.tasks_repo import Task
from study_tracker.domain.validation import validate_task_title
from study_tracker.services import subject_service
from study_tracker.ui.widgets.confirm import warn


class TaskDialog(QDialog):
    """Dialog for creating or editing a task."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock,
        parent: QWidget | None = None,
        task: Task | None = None,
        default_subject_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._clock = clock
        self._task = task
        self._default_subject_id = default_subject_id

        self.setWindowTitle("Edit Task" if task else "Add Task")
        self.setMinimumWidth(400)
        self._build_ui()
        if task:
            self._populate(task)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Title
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Task title")
        self._title_edit.setMaxLength(200)
        form.addRow("Title:", self._title_edit)

        # Subject
        self._subject_combo = QComboBox()
        self._subjects = subject_service.get_active(self._conn)
        if self._task and self._task.subject_id not in [s.id for s in self._subjects]:
            # Also include archived subject if editing a task linked to it
            all_subjects = subject_service.get_all(self._conn, include_archived=True)
            self._subjects = all_subjects

        for s in self._subjects:
            self._subject_combo.addItem(s.name, s.id)

        if self._default_subject_id:
            idx = self._subject_combo.findData(self._default_subject_id)
            if idx >= 0:
                self._subject_combo.setCurrentIndex(idx)
        form.addRow("Subject:", self._subject_combo)

        # Status (if editing)
        if self._task:
            self._status_combo = QComboBox()
            self._status_combo.addItem("To do", "todo")
            self._status_combo.addItem("In progress", "in_progress")
            self._status_combo.addItem("Done", "done")
            idx = self._status_combo.findData(self._task.status)
            if idx >= 0:
                self._status_combo.setCurrentIndex(idx)
            form.addRow("Status:", self._status_combo)
        else:
            self._status_combo = None

        # Priority
        self._priority_combo = QComboBox()
        self._priority_combo.addItem("Medium", "medium")
        self._priority_combo.addItem("High", "high")
        self._priority_combo.addItem("Low", "low")
        form.addRow("Priority:", self._priority_combo)

        # Due date
        due_row = QWidget()
        due_layout = QHBoxLayout(due_row)
        due_layout.setContentsMargins(0, 0, 0, 0)
        self._has_due_chk = QCheckBox("Set due date")
        self._due_date_edit = QDateEdit()
        self._due_date_edit.setCalendarPopup(True)
        today_str = self._clock.local_date()
        qd = QDate.fromString(today_str, "yyyy-MM-dd")
        self._due_date_edit.setDate(qd)
        self._due_date_edit.setEnabled(False)
        self._has_due_chk.toggled.connect(self._due_date_edit.setEnabled)
        due_layout.addWidget(self._has_due_chk)
        due_layout.addWidget(self._due_date_edit)
        due_layout.addStretch()
        form.addRow("Due Date:", due_row)

        # Estimate (hours and minutes)
        est_row = QWidget()
        est_layout = QHBoxLayout(est_row)
        est_layout.setContentsMargins(0, 0, 0, 0)
        self._has_est_chk = QCheckBox("Set estimate")
        self._est_hours = QSpinBox()
        self._est_hours.setRange(0, 999)
        self._est_hours.setSuffix(" h")
        self._est_hours.setEnabled(False)
        self._est_mins = QSpinBox()
        self._est_mins.setRange(0, 59)
        self._est_mins.setSuffix(" min")
        self._est_mins.setSingleStep(5)
        self._est_mins.setEnabled(False)
        self._has_est_chk.toggled.connect(self._est_hours.setEnabled)
        self._has_est_chk.toggled.connect(self._est_mins.setEnabled)
        est_layout.addWidget(self._has_est_chk)
        est_layout.addWidget(self._est_hours)
        est_layout.addWidget(self._est_mins)
        est_layout.addStretch()
        form.addRow("Estimate:", est_row)

        # Notes
        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setMaximumHeight(80)
        self._notes_edit.setPlaceholderText("Optional notes…")
        form.addRow("Notes:", self._notes_edit)

        layout.addLayout(form)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, task: Task) -> None:
        self._title_edit.setText(task.title)
        idx = self._subject_combo.findData(task.subject_id)
        if idx >= 0:
            self._subject_combo.setCurrentIndex(idx)

        idx = self._priority_combo.findData(task.priority)
        if idx >= 0:
            self._priority_combo.setCurrentIndex(idx)

        if task.due_date:
            self._has_due_chk.setChecked(True)
            self._due_date_edit.setDate(QDate.fromString(task.due_date, "yyyy-MM-dd"))

        if task.estimate_secs is not None and task.estimate_secs > 0:
            self._has_est_chk.setChecked(True)
            h = task.estimate_secs // 3600
            m = (task.estimate_secs % 3600) // 60
            self._est_hours.setValue(h)
            self._est_mins.setValue(m)

        self._notes_edit.setPlainText(task.notes)

    def _on_accept(self) -> None:
        try:
            validate_task_title(self._title_edit.text())
        except AppError as exc:
            warn(self, "Invalid input", str(exc))
            return
        if self._subject_combo.count() == 0:
            warn(self, "No subjects", "Please create a subject before adding tasks.")
            return
        self.accept()

    # ------------------------------------------------------------------
    @property
    def title(self) -> str:
        return self._title_edit.text().strip()

    @property
    def subject_id(self) -> int:
        return self._subject_combo.currentData()

    @property
    def status(self) -> str:
        if self._status_combo:
            return self._status_combo.currentData()
        return "todo"

    @property
    def priority(self) -> str:
        return self._priority_combo.currentData()

    @property
    def due_date(self) -> str | None:
        if self._has_due_chk.isChecked():
            return self._due_date_edit.date().toString("yyyy-MM-dd")
        return None

    @property
    def estimate_secs(self) -> int | None:
        if self._has_est_chk.isChecked():
            secs = self._est_hours.value() * 3600 + self._est_mins.value() * 60
            return secs if secs > 0 else None
        return None

    @property
    def notes(self) -> str:
        return self._notes_edit.toPlainText().strip()
