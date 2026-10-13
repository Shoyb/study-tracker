"""Left sidebar navigation widget."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSizePolicy


class Sidebar(QListWidget):
    """A fixed-width list of navigation items.

    Emits ``page_selected(index)`` when the user clicks an item or uses a
    keyboard shortcut.
    """

    page_selected = Signal(int)

    _ITEMS = [
        ("📊", "Dashboard"),
        ("⏱", "Timer"),
        ("🗂", "Records"),
        ("📈", "Analytics"),
        ("⚙", "Settings"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(190)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setObjectName("Sidebar")
        self.setSpacing(2)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        for icon, label in self._ITEMS:
            item = QListWidgetItem(f"  {icon}  {label}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.addItem(item)

        self.setCurrentRow(0)
        self.currentRowChanged.connect(self.page_selected)
