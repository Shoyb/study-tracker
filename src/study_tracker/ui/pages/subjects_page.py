"""Subjects page – manage study subjects."""

from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.errors import AppError
from study_tracker.db.subjects_repo import Subject
from study_tracker.services import subject_service
from study_tracker.ui.dialogs.subject_dialog import SubjectDialog
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.confirm import confirm, warn

log = logging.getLogger(__name__)


class SubjectsPage(QWidget):
    """Full subjects management page.

    Layout::

        ┌─────────────────────────────────────────┐
        │  Title                    [Add Subject]  │
        ├─────────────────────────────────────────┤
        │  ● Physics          [Edit][Archive][Del] │
        │  ● Mathematics      [Edit][Archive][Del] │
        │  …                                       │
        │  [Show archived]                         │
        └─────────────────────────────────────────┘
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        signals: AppSignals,
        clock,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._signals = signals
        self._clock = clock
        self._show_archived = False

        self._build_ui()
        self._signals.subjects_changed.connect(self._refresh)
        self._refresh()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("<h2>Subjects</h2>")
        header.addWidget(title)
        header.addStretch()
        add_btn = QPushButton("+ Add Subject")
        add_btn.clicked.connect(self._on_add)
        header.addWidget(add_btn)
        root.addLayout(header)

        # Subject list
        self._list = QListWidget()
        self._list.setSpacing(2)
        self._list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._list)

        # Toggle archived
        self._archived_btn = QPushButton("Show archived subjects")
        self._archived_btn.setProperty("flat", True)
        self._archived_btn.clicked.connect(self._toggle_archived)
        root.addWidget(self._archived_btn, alignment=Qt.AlignmentFlag.AlignLeft)

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        self._list.clear()
        subjects = subject_service.get_all(self._conn, include_archived=self._show_archived)
        if not subjects:
            item = QListWidgetItem("No subjects yet. Click '+ Add Subject' to create one.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            return

        for subj in subjects:
            self._list.addItem(self._make_item(subj))

        self._archived_btn.setText(
            "Hide archived subjects" if self._show_archived else "Show archived subjects"
        )

    def _make_item(self, subj: Subject) -> QListWidgetItem:
        widget = _SubjectRow(subj, self._conn, self._signals, self._clock, self)
        item = QListWidgetItem(self._list)
        item.setSizeHint(widget.sizeHint())
        self._list.setItemWidget(item, widget)
        return item

    def _toggle_archived(self) -> None:
        self._show_archived = not self._show_archived
        self._refresh()

    def _on_add(self) -> None:
        dlg = SubjectDialog(self._conn, self)
        if dlg.exec() != SubjectDialog.DialogCode.Accepted:
            return
        try:
            subject_service.create(
                self._conn,
                name=dlg.name,
                colour=dlg.colour,
                created_at=self._clock.now_utc(),
            )
            self._signals.subjects_changed.emit()
        except AppError as exc:
            warn(self, "Cannot add subject", str(exc))


class _SubjectRow(QWidget):
    """One row in the subjects list."""

    def __init__(
        self,
        subject: Subject,
        conn: sqlite3.Connection,
        signals: AppSignals,
        clock,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._subject = subject
        self._conn = conn
        self._signals = signals
        self._clock = clock
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        # Colour swatch
        swatch = QLabel()
        swatch.setFixedSize(18, 18)
        swatch.setStyleSheet(
            f"background-color: {self._subject.colour};"
            "border-radius: 9px; border: 1px solid rgba(0,0,0,0.15);"
        )
        layout.addWidget(swatch)

        # Name (greyed if archived)
        name_lbl = QLabel(self._subject.name)
        if self._subject.archived:
            name_lbl.setStyleSheet("color: #9E9E9E; font-style: italic;")
            name_lbl.setText(self._subject.name + "  [archived]")
        layout.addWidget(name_lbl)
        layout.addStretch()

        # Buttons
        edit_btn = QPushButton("Edit")
        edit_btn.setProperty("flat", True)
        edit_btn.clicked.connect(self._on_edit)
        layout.addWidget(edit_btn)

        if self._subject.archived:
            unarchive_btn = QPushButton("Unarchive")
            unarchive_btn.setProperty("flat", True)
            unarchive_btn.clicked.connect(self._on_unarchive)
            layout.addWidget(unarchive_btn)
        else:
            archive_btn = QPushButton("Archive")
            archive_btn.setProperty("flat", True)
            archive_btn.clicked.connect(self._on_archive)
            layout.addWidget(archive_btn)

        del_btn = QPushButton("Delete")
        del_btn.setProperty("flat", True)
        del_btn.setStyleSheet("color: #D32F2F;")
        del_btn.clicked.connect(self._on_delete)
        layout.addWidget(del_btn)

    def _on_edit(self) -> None:
        dlg = SubjectDialog(self._conn, self, subject=self._subject)
        if dlg.exec() != SubjectDialog.DialogCode.Accepted:
            return
        try:
            subject_service.update(
                self._conn,
                self._subject.id,
                name=dlg.name,
                colour=dlg.colour,
                created_at=self._clock.now_utc(),
            )
            self._signals.subjects_changed.emit()
        except AppError as exc:
            warn(self, "Cannot edit subject", str(exc))

    def _on_archive(self) -> None:
        if not confirm(self, "Archive subject",
                       f"Archive \"{self._subject.name}\"?",
                       "It will disappear from pickers but remain in history."):
            return
        try:
            subject_service.archive(self._conn, self._subject.id, self._clock.now_utc())
            self._signals.subjects_changed.emit()
        except AppError as exc:
            warn(self, "Cannot archive", str(exc))

    def _on_unarchive(self) -> None:
        try:
            subject_service.unarchive(self._conn, self._subject.id, self._clock.now_utc())
            self._signals.subjects_changed.emit()
        except AppError as exc:
            warn(self, "Cannot unarchive", str(exc))

    def _on_delete(self) -> None:
        if not confirm(self, "Delete subject",
                       f"Permanently delete \"{self._subject.name}\"?",
                       "This cannot be undone. The subject must have no linked tasks or sessions."):
            return
        try:
            subject_service.delete(self._conn, self._subject.id, self._clock.now_utc())
            self._signals.subjects_changed.emit()
        except AppError as exc:
            warn(self, "Cannot delete", str(exc))
