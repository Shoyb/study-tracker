"""Persistent undo history browser."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from study_tracker.services.undo.journal import JournalService
from study_tracker.ui.widgets.confirm import warn


class UndoHistoryDialog(QDialog):
    """Display recent actions and allow undoing through a selected action."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock,
        on_change: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._journal = JournalService(conn)
        self._clock = clock
        self._on_change = on_change
        self.setWindowTitle("Undo History")
        self.setMinimumSize(520, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Recent changes"))
        self._entries = QListWidget()
        layout.addWidget(self._entries)
        self._undo_to = QPushButton("Undo through selected action")
        self._undo_to.clicked.connect(self._undo_selected)
        layout.addWidget(self._undo_to)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self) -> None:
        self._entries.clear()
        groups = {}
        for entry in self._journal.history(limit=500):
            groups.setdefault(entry.group_id, entry)
        for entry in groups.values():
            item = QListWidgetItem(f"{entry.created_at_utc}   {entry.summary}")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setForeground(QColor("#888888") if entry.undone_at_utc else QColor("#202020"))
            item.setToolTip(f"{entry.entity_type}: {entry.action}")
            self._entries.addItem(item)
        self._undo_to.setEnabled(bool(groups))

    def _undo_selected(self) -> None:
        item = self._entries.currentItem()
        if item is None:
            return
        try:
            summary = self._journal.undo_through(
                item.data(Qt.ItemDataRole.UserRole), self._clock.now_utc()
            )
        except Exception as exc:
            warn(self, "Cannot undo", str(exc))
            return
        if summary:
            self._on_change()
            self._refresh()
