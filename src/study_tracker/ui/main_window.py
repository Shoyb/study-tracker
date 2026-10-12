"""Main application window."""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from study_tracker.ui.sidebar import Sidebar
from study_tracker.ui.signals import AppSignals

log = logging.getLogger(__name__)


class PlaceholderPage(QWidget):
    """Temporary placeholder shown for pages not yet implemented."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(f"<h2>{name}</h2><p>Coming soon…</p>")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


class TimerBar(QWidget):
    """Slim persistent bar shown at the top of the content area while a timer runs.

    Hidden by default; will be wired up in Milestone 7.
    """

    def __init__(self, signals: AppSignals, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TimerBar")
        self._signals = signals
        self.hide()  # Hidden until a timer is running.

        layout = QHBoxLayout(self)
        self._subject_label = QLabel("—")
        self._elapsed_label = QLabel("00:00:00")
        self._elapsed_label.setObjectName("TimerElapsed")
        layout.addWidget(self._subject_label)
        layout.addStretch()
        layout.addWidget(self._elapsed_label)


class MainWindow(QMainWindow):
    """The single top-level window for Study Tracker.

    Layout::

        ┌──────────────────────────────────────────┐
        │  Sidebar (190 px)  │  Content area        │
        │                    │  ┌──────────────────┐ │
        │  Dashboard         │  │ Timer bar (top)  │ │
        │  Timer             │  ├──────────────────┤ │
        │  Tasks             │  │                  │ │
        │  History           │  │  Active page     │ │
        │  Calendar          │  │                  │ │
        │  Analytics         │  │                  │ │
        │  Subjects          │  └──────────────────┘ │
        │  Settings          │                       │
        ├────────────────────────────────────────────┤
        │  Status bar                                │
        └────────────────────────────────────────────┘
    """

    _PAGE_NAMES = [
        "Dashboard",
        "Timer",
        "Tasks",
        "History",
        "Calendar",
        "Analytics",
        "Subjects",
        "Settings",
    ]

    def __init__(self, signals: AppSignals, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._signals = signals

        self.setWindowTitle("Study Tracker")
        self.setMinimumSize(QSize(900, 600))
        self.resize(1100, 700)
        self._build_ui()
        self._setup_shortcuts()
        log.info("Main window initialised.")

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar(central)
        self._sidebar.page_selected.connect(self._on_page_selected)
        root_layout.addWidget(self._sidebar)

        # Right-hand column: timer bar on top, stacked pages below.
        right_col = QWidget()
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._timer_bar = TimerBar(self._signals, right_col)
        right_layout.addWidget(self._timer_bar)

        self._stack = QStackedWidget(right_col)
        for name in self._PAGE_NAMES:
            self._stack.addWidget(PlaceholderPage(name))
        right_layout.addWidget(self._stack)

        root_layout.addWidget(right_col)

        # Status bar
        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    def _setup_shortcuts(self) -> None:
        """Ctrl+1 … Ctrl+8 navigate to the corresponding sidebar page."""
        for i in range(len(self._PAGE_NAMES)):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda idx=i: self._navigate(idx))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_page_selected(self, index: int) -> None:
        self._navigate(index)

    def _navigate(self, index: int) -> None:
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
            self._sidebar.setCurrentRow(index)
            log.debug("Navigated to page %d (%s).", index, self._PAGE_NAMES[index])

    def show_status(self, message: str, timeout_ms: int = 4000) -> None:
        """Display a short message in the status bar."""
        self._status_bar.showMessage(message, timeout_ms)
