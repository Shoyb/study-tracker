"""Add / Edit subject dialog."""

from __future__ import annotations

import sqlite3

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.errors import AppError
from study_tracker.db.subjects_repo import Subject
from study_tracker.ui.widgets.confirm import warn


class SubjectDialog(QDialog):
    """Dialog for creating or editing a subject.

    After ``exec()`` returns ``Accepted``, read ``.name`` and ``.colour``.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        parent: QWidget | None = None,
        subject: Subject | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._subject = subject
        self._colour = subject.colour if subject else "#1976D2"

        self.setWindowTitle("Edit Subject" if subject else "Add Subject")
        self.setMinimumWidth(340)
        self._build_ui()
        if subject:
            self._name_edit.setText(subject.name)
            self._apply_colour(subject.colour)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. Physics")
        self._name_edit.setMaxLength(60)
        if self._subject and self._subject.name.casefold() == "no subject":
            self._name_edit.setReadOnly(True)
            self._name_edit.setToolTip("Used for sessions when you did not track a subject.")
        form.addRow("Name:", self._name_edit)

        colour_row = QWidget()
        colour_layout = QHBoxLayout(colour_row)
        colour_layout.setContentsMargins(0, 0, 0, 0)
        self._colour_swatch = QLabel()
        self._colour_swatch.setFixedSize(28, 28)
        self._colour_swatch.setObjectName("ColourSwatch")
        self._colour_btn = QPushButton("Choose…")
        self._colour_btn.setProperty("flat", True)
        self._colour_btn.clicked.connect(self._pick_colour)
        colour_layout.addWidget(self._colour_swatch)
        colour_layout.addWidget(self._colour_btn)
        colour_layout.addStretch()
        form.addRow("Colour:", colour_row)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_colour(self._colour)

    def _apply_colour(self, hex_colour: str) -> None:
        self._colour = hex_colour
        self._colour_swatch.setStyleSheet(
            f"background-color: {hex_colour}; border: 1px solid #BDBDBD; border-radius: 4px;"
        )

    def _pick_colour(self) -> None:
        initial = QColor(self._colour)
        chosen = QColorDialog.getColor(initial, self, "Choose subject colour")
        if chosen.isValid():
            self._apply_colour(chosen.name().upper())

    def _on_accept(self) -> None:
        from study_tracker.domain.validation import validate_subject_colour, validate_subject_name

        try:
            validate_subject_name(self._name_edit.text())
            validate_subject_colour(self._colour)
        except AppError as exc:
            warn(self, "Invalid input", str(exc))
            return
        self.accept()

    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self._name_edit.text().strip()

    @property
    def colour(self) -> str:
        return self._colour
