"""Edit study and exam goals for one study day."""

from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)

from study_tracker.core.errors import AppError
from study_tracker.services import day_plan_service
from study_tracker.ui.widgets.confirm import warn


class DayPlanDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, study_day: str, clock, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._study_day = study_day
        self._clock = clock
        self.setWindowTitle(f"Plan for {study_day}")

        form = QFormLayout()
        self._study_minutes = QSpinBox()
        self._study_minutes.setRange(0, 1440)
        self._study_minutes.setSuffix(" min")
        self._study_minutes.setValue(day_plan_service.get_study_goal_seconds(conn, study_day) // 60)
        form.addRow("Study target:", self._study_minutes)

        self._goal_type = QComboBox()
        for label, value in (
            ("No exam goal", "none"),
            ("Completed exams", "count"),
            ("Minutes in exams", "minutes"),
            ("Questions attempted", "questions"),
        ):
            self._goal_type.addItem(label, value)
        goal = day_plan_service.get_exam_goal(conn, study_day)
        self._goal_type.setCurrentIndex(self._goal_type.findData(goal.goal_type))
        self._goal_value = QSpinBox()
        self._goal_value.setRange(0, 100000)
        self._goal_value.setValue(goal.value)
        self._goal_type.currentIndexChanged.connect(self._sync_goal_value)
        form.addRow("Exam goal:", self._goal_type)
        form.addRow("Goal amount:", self._goal_value)

        self._rest_day = QCheckBox("Mark as a rest day")
        self._rest_day.setChecked(day_plan_service.is_rest_day(conn, study_day))
        self._rest_day.toggled.connect(self._sync_rest_day)
        form.addRow("", self._rest_day)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._sync_goal_value()
        self._sync_rest_day(self._rest_day.isChecked())

    def _sync_goal_value(self, *_args) -> None:
        self._goal_value.setEnabled(self._goal_type.currentData() != "none")
        if self._goal_type.currentData() == "none":
            self._goal_value.setValue(0)

    def _sync_rest_day(self, checked: bool) -> None:
        for widget in (self._study_minutes, self._goal_type, self._goal_value):
            widget.setEnabled(not checked)

    def _save(self) -> None:
        try:
            if self._rest_day.isChecked():
                day_plan_service.save_day_plan(
                    self._conn,
                    self._study_day,
                    study_goal_secs=0,
                    exam_goal_type="none",
                    exam_goal_value=0,
                    is_rest_day=True,
                    now_utc=self._clock.now_utc(),
                )
            else:
                day_plan_service.save_day_plan(
                    self._conn,
                    self._study_day,
                    study_goal_secs=self._study_minutes.value() * 60,
                    exam_goal_type=self._goal_type.currentData(),
                    exam_goal_value=self._goal_value.value(),
                    is_rest_day=False,
                    now_utc=self._clock.now_utc(),
                )
        except AppError as exc:
            warn(self, "Invalid daily plan", str(exc))
            return
        self.accept()
