"""Allocate a No subject session across subjects."""

from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.formatting import format_duration
from study_tracker.db.sessions_repo import Session
from study_tracker.services import subject_service
from study_tracker.ui.widgets.confirm import warn


class SplitSessionDialog(QDialog):
    def __init__(
        self,
        conn: sqlite3.Connection,
        session: Session,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._session = session
        self.setWindowTitle("Split unassigned session")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"Allocate {format_duration(session.duration_secs)} among subjects. "
                "You can leave part of the time unassigned."
            )
        )

        form = QFormLayout()
        self._mode = QComboBox()
        self._mode.addItem("Exact hours and minutes", "exact")
        self._mode.addItem("Relative weights", "weight")
        self._mode.currentIndexChanged.connect(self._sync_columns)
        form.addRow("Allocation method:", self._mode)
        layout.addLayout(form)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Subject", "Hours", "Minutes", "Weight"])
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)
        self._add_row()
        self._add_row()

        row_actions = QHBoxLayout()
        add_button = QPushButton("Add subject")
        add_button.clicked.connect(self._add_row)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_selected_row)
        row_actions.addWidget(add_button)
        row_actions.addWidget(remove_button)
        row_actions.addStretch()
        layout.addLayout(row_actions)

        self._keep_remainder = QCheckBox("Leave part of the time in No subject")
        self._keep_remainder.toggled.connect(self._remainder_toggled)
        layout.addWidget(self._keep_remainder)
        remainder_row = QHBoxLayout()
        self._remainder_hours = QSpinBox()
        self._remainder_hours.setRange(0, 24)
        self._remainder_hours.setSuffix(" h")
        self._remainder_minutes = QSpinBox()
        self._remainder_minutes.setRange(0, 59)
        self._remainder_minutes.setSuffix(" min")
        self._remainder_minutes.setSingleStep(5)
        remainder_row.addWidget(self._remainder_hours)
        remainder_row.addWidget(self._remainder_minutes)
        remainder_row.addStretch()
        layout.addLayout(remainder_row)
        self._remainder_hours.setEnabled(False)
        self._remainder_minutes.setEnabled(False)

        self._result = QLabel()
        self._result.setWordWrap(True)
        layout.addWidget(self._result)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._sync_columns()

    def _add_row(self) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        subject_combo = QComboBox()
        subjects = [
            subject
            for subject in subject_service.get_active(self._conn)
            if subject.name.casefold() != "no subject"
        ]
        for subject in subjects:
            subject_combo.addItem(subject.name, subject.id)
        self._table.setCellWidget(row, 0, subject_combo)

        hours = QSpinBox()
        hours.setRange(0, 24)
        hours.setSuffix(" h")
        self._table.setCellWidget(row, 1, hours)

        minutes = QSpinBox()
        minutes.setRange(0, 59)
        minutes.setSuffix(" min")
        minutes.setSingleStep(5)
        self._table.setCellWidget(row, 2, minutes)

        weight = QDoubleSpinBox()
        weight.setRange(0, 10000)
        weight.setDecimals(2)
        weight.setSingleStep(0.25)
        self._table.setCellWidget(row, 3, weight)
        self._sync_columns()

    def _remove_selected_row(self) -> None:
        row = self._table.currentRow()
        if row >= 0 and self._table.rowCount() > 1:
            self._table.removeRow(row)

    def _sync_columns(self, *_args) -> None:
        exact = self._mode.currentData() == "exact"
        self._table.setColumnHidden(1, not exact)
        self._table.setColumnHidden(2, not exact)
        self._table.setColumnHidden(3, exact)

    def _remainder_toggled(self, checked: bool) -> None:
        self._remainder_hours.setEnabled(checked)
        self._remainder_minutes.setEnabled(checked)

    @property
    def keep_unassigned_seconds(self) -> int:
        if not self._keep_remainder.isChecked():
            return 0
        return self._remainder_hours.value() * 3600 + self._remainder_minutes.value() * 60

    def _allocations(self) -> dict[int, int]:
        remainder = self.keep_unassigned_seconds
        available = self._session.duration_secs - remainder
        if remainder > self._session.duration_secs:
            raise ValueError("Unassigned time cannot exceed the original session duration.")

        subject_ids: list[int] = []
        values: list[float] = []
        for row in range(self._table.rowCount()):
            subject_id = self._table.cellWidget(row, 0).currentData()
            if subject_id is None:
                continue
            subject_ids.append(subject_id)
            if self._mode.currentData() == "exact":
                hours = self._table.cellWidget(row, 1).value()
                minutes = self._table.cellWidget(row, 2).value()
                values.append(float(hours * 3600 + minutes * 60))
            else:
                values.append(self._table.cellWidget(row, 3).value())

        if self._mode.currentData() == "exact":
            allocations: dict[int, int] = {}
            for subject_id, seconds in zip(subject_ids, values, strict=True):
                if seconds:
                    allocations[subject_id] = allocations.get(subject_id, 0) + int(seconds)
            return allocations

        total_weight = sum(values)
        if available == 0 and total_weight == 0:
            return {}
        if total_weight <= 0:
            raise ValueError("Enter a positive weight for at least one subject.")
        exact_shares = [available * weight / total_weight for weight in values]
        whole_seconds = [int(share) for share in exact_shares]
        extra_seconds = available - sum(whole_seconds)
        remainder_order = sorted(
            range(len(values)),
            key=lambda index: exact_shares[index] - whole_seconds[index],
            reverse=True,
        )
        for index in remainder_order[:extra_seconds]:
            whole_seconds[index] += 1
        allocations = {}
        for subject_id, seconds in zip(subject_ids, whole_seconds, strict=True):
            if seconds:
                allocations[subject_id] = allocations.get(subject_id, 0) + seconds
        return allocations

    def _accept(self) -> None:
        try:
            allocations = self._allocations()
            allocated = sum(allocations.values())
            total = self._session.duration_secs
            remainder = self.keep_unassigned_seconds
            if allocated + remainder != total:
                raise ValueError(
                    f"Allocated {format_duration(allocated)} plus unassigned "
                    f"{format_duration(remainder)} must equal {format_duration(total)}."
                )
        except ValueError as exc:
            warn(self, "Invalid split", str(exc))
            return
        self.accept()

    @property
    def allocations(self) -> dict[int, int]:
        return self._allocations()
