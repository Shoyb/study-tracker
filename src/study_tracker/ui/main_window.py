"""Main application window."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.clock import Clock
from study_tracker.core.formatting import format_duration, format_duration_short
from study_tracker.db import subjects_repo, tasks_repo
from study_tracker.services.timer_service import TimerService
from study_tracker.ui.pages.history_page import HistoryPage
from study_tracker.ui.pages.subjects_page import SubjectsPage
from study_tracker.ui.pages.tasks_page import TasksPage
from study_tracker.ui.pages.timer_page import TimerPage
from study_tracker.ui.sidebar import Sidebar
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.confirm import warn

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

    Visible when timer is running or paused and user is on any other page.
    Clicking the bar navigates to the Timer page (Ctrl+2).
    """

    def __init__(
        self,
        signals: AppSignals,
        timer_svc: TimerService | None = None,
        conn: sqlite3.Connection | None = None,
        on_navigate: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TimerBar")
        self._signals = signals
        self._timer_svc = timer_svc
        self._conn = conn
        self._on_navigate = on_navigate
        self._on_stop = on_stop
        self.hide()  # Hidden until a timer is running.
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "#TimerBar { background-color: #E3F2FD; border-bottom: 1px solid #90CAF9; "
            "padding: 4px 12px; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)

        self._info_label = QLabel("—")
        self._info_label.setStyleSheet("font-weight: bold; color: #1565C0;")

        self._elapsed_label = QLabel("00:00:00")
        self._elapsed_label.setObjectName("TimerElapsed")
        self._elapsed_label.setStyleSheet(
            "font-family: 'Consolas', monospace; font-weight: bold; font-size: 11pt;"
        )

        self._pause_btn = QPushButton("⏸  Pause")
        self._pause_btn.setFixedHeight(28)
        self._pause_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._pause_btn.clicked.connect(self._on_pause_resume_clicked)

        self._stop_btn = QPushButton("⏹  Stop")
        self._stop_btn.setFixedHeight(28)
        self._stop_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._stop_btn.clicked.connect(self._on_stop_clicked)

        layout.addWidget(QLabel("⏱"))
        layout.addWidget(self._info_label)
        layout.addStretch()
        layout.addWidget(self._elapsed_label)
        layout.addWidget(self._pause_btn)
        layout.addWidget(self._stop_btn)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._on_navigate:
            self._on_navigate()
        super().mousePressEvent(event)

    def _on_pause_resume_clicked(self) -> None:
        if not self._timer_svc or not self._timer_svc.is_active:
            return
        if self._timer_svc.is_paused:
            self._timer_svc.resume()
        else:
            self._timer_svc.pause()
        self._signals.timer_state_changed.emit()

    def _on_stop_clicked(self) -> None:
        if self._on_stop:
            self._on_stop()

    def update_display(self) -> None:
        if not self._timer_svc or not self._timer_svc.is_active or not self._conn:
            return

        secs = self._timer_svc.elapsed_seconds()
        self._elapsed_label.setText(format_duration_short(secs))

        subj = subjects_repo.get_by_id(self._conn, self._timer_svc.subject_id)
        subj_name = subj.name if subj else "Subject"
        if self._timer_svc.task_id:
            task = tasks_repo.get_by_id(self._conn, self._timer_svc.task_id)
            task_title = f" — {task.title}" if task else ""
        else:
            task_title = ""

        status_prefix = "[PAUSED] " if self._timer_svc.is_paused else ""
        self._info_label.setText(f"{status_prefix}{subj_name}{task_title}")
        self._pause_btn.setText("▶  Resume" if self._timer_svc.is_paused else "⏸  Pause")


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

    def __init__(
        self,
        signals: AppSignals,
        conn: sqlite3.Connection | None = None,
        clock: Clock | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._signals = signals
        self._conn = conn
        self._clock = clock or Clock()
        self._timer_svc = (
            TimerService(self._conn, self._clock) if self._conn is not None else None
        )

        self.setWindowTitle("Study Tracker")
        self.setMinimumSize(QSize(900, 600))
        self.resize(1100, 700)
        self._build_ui()
        self._setup_shortcuts()
        self._setup_timers()

        self._signals.timer_state_changed.connect(self._update_timer_bar)

        QTimer.singleShot(0, self._check_startup_recovery)
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

        self._timer_bar = TimerBar(
            self._signals,
            timer_svc=self._timer_svc,
            conn=self._conn,
            on_navigate=lambda: self._navigate(1),
            on_stop=self._on_timer_bar_stop,
            parent=right_col,
        )
        right_layout.addWidget(self._timer_bar)

        self._stack = QStackedWidget(right_col)
        for name in self._PAGE_NAMES:
            if name == "Timer" and self._conn is not None and self._timer_svc is not None:
                self._timer_page = TimerPage(
                    self._conn, self._timer_svc, self._signals, self._clock
                )
                self._stack.addWidget(self._timer_page)
            elif name == "Subjects" and self._conn is not None:
                self._subjects_page = SubjectsPage(self._conn, self._signals, self._clock)
                self._stack.addWidget(self._subjects_page)
            elif name == "Tasks" and self._conn is not None:
                self._tasks_page = TasksPage(self._conn, self._signals, self._clock)
                self._stack.addWidget(self._tasks_page)
            elif name == "History" and self._conn is not None:
                self._history_page = HistoryPage(self._conn, self._signals, self._clock)
                self._stack.addWidget(self._history_page)
            else:
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

    def _setup_timers(self) -> None:
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(250)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(15000)
        self._heartbeat_timer.timeout.connect(self._on_heartbeat)
        self._heartbeat_timer.start()

    # ------------------------------------------------------------------
    # Timer & background handlers
    # ------------------------------------------------------------------

    def _on_tick(self) -> None:
        self._signals.timer_tick.emit()
        if self._timer_svc and self._timer_svc.is_running:
            gap = self._timer_svc.check_inactivity_gap()
            if gap is not None:
                self._signals.timer_state_changed.emit()
                mins = gap // 60
                warn(
                    self,
                    "Inactivity detected",
                    f"Computer was asleep or timer was suspended for {gap}s ({mins}m).\n"
                    "The timer has been paused.",
                )
        self._update_timer_bar()

    def _on_heartbeat(self) -> None:
        if self._timer_svc:
            self._timer_svc.heartbeat()

    def _update_timer_bar(self) -> None:
        if self._timer_svc and self._timer_svc.is_active:
            is_timer_page = self._stack.currentIndex() == 1
            self._timer_bar.setVisible(not is_timer_page)
            self._timer_bar.update_display()
        else:
            self._timer_bar.hide()

    def _on_timer_bar_stop(self) -> None:
        if hasattr(self, "_timer_page"):
            self._timer_page._on_stop()

    def _check_startup_recovery(self) -> None:
        if self._timer_svc is None or self._conn is None:
            return
        state = self._timer_svc.load_persisted_state()
        if state is None:
            return

        from datetime import datetime

        from study_tracker.ui.dialogs.recovery_dialog import RecoveryDialog

        dlg = RecoveryDialog(self._conn, state, self)
        if dlg.exec() != RecoveryDialog.DialogCode.Accepted:
            return

        if dlg.action == RecoveryDialog.SAVE:
            offset = datetime.now().astimezone().utcoffset()
            offset_mins = int(offset.total_seconds() // 60) if offset else 0
            sess = self._timer_svc.recover_and_save(state, utc_offset_mins=offset_mins)
            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
            self.show_status(f"Recovered session saved ({format_duration(sess.duration_secs)}).")
        elif dlg.action == RecoveryDialog.RESUME:
            self._timer_svc.recover_as_paused(state)
            self._signals.timer_state_changed.emit()
            self._navigate(1)
            self.show_status("Recovered session loaded (paused).")
        elif dlg.action == RecoveryDialog.DISCARD:
            self._timer_svc.discard()
            self.show_status("Interrupted session discarded.")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._timer_svc and self._timer_svc.is_active:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Timer Active")
            msg_box.setText(
                "A study timer is currently active.\n"
                "What would you like to do before closing?"
            )
            stop_btn = msg_box.addButton("Stop & Save", QMessageBox.ButtonRole.AcceptRole)
            pause_btn = msg_box.addButton("Pause & Quit", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(cancel_btn)

            msg_box.exec()
            clicked = msg_box.clickedButton()

            if clicked == stop_btn:
                from datetime import datetime
                offset = datetime.now().astimezone().utcoffset()
                offset_mins = int(offset.total_seconds() // 60) if offset else 0
                try:
                    self._timer_svc.stop(utc_offset_mins=offset_mins)
                    event.accept()
                except Exception as exc:
                    warn(self, "Cannot stop timer", str(exc))
                    event.ignore()
            elif clicked == pause_btn:
                if not self._timer_svc.is_paused:
                    self._timer_svc.pause()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_page_selected(self, index: int) -> None:
        self._navigate(index)

    def _navigate(self, index: int) -> None:
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
            self._sidebar.setCurrentRow(index)
            self._update_timer_bar()
            log.debug("Navigated to page %d (%s).", index, self._PAGE_NAMES[index])

    def show_status(self, message: str, timeout_ms: int = 4000) -> None:
        """Display a short message in the status bar."""
        self._status_bar.showMessage(message, timeout_ms)

    def add_manual_session(
        self,
        subject_id: int | None = None,
        task_id: int | None = None,
    ) -> None:
        """Open SessionDialog and save manual study session."""
        if self._conn is None:
            return

        from datetime import datetime

        from study_tracker.core.errors import AppError
        from study_tracker.db import subjects_repo
        from study_tracker.services import session_service
        from study_tracker.ui.dialogs.session_dialog import SessionDialog

        offset = datetime.now().astimezone().utcoffset()
        offset_mins = int(offset.total_seconds() // 60) if offset else 0

        dlg = SessionDialog(
            self._conn,
            self._clock,
            self,
            default_subject_id=subject_id,
            default_task_id=task_id,
        )
        if dlg.exec() != SessionDialog.DialogCode.Accepted:
            return

        try:
            now_utc = self._clock.now_utc()
            if dlg.is_timed:
                st_utc, et_utc = dlg.get_timestamps_utc(offset_mins)
                sess = session_service.add_manual_timed(
                    self._conn,
                    subject_id=dlg.subject_id,
                    task_id=dlg.task_id,
                    start_utc=st_utc,
                    end_utc=et_utc,
                    duration_secs=dlg.duration_secs,
                    notes=dlg.notes,
                    utc_offset_mins=offset_mins,
                    created_at=now_utc,
                )
            else:
                sess = session_service.add_manual_duration(
                    self._conn,
                    subject_id=dlg.subject_id,
                    task_id=dlg.task_id,
                    local_date=dlg.local_date,
                    duration_secs=dlg.duration_secs,
                    notes=dlg.notes,
                    utc_offset_mins=offset_mins,
                    created_at=now_utc,
                )

            subj = subjects_repo.get_by_id(self._conn, dlg.subject_id)
            subj_name = subj.name if subj else ""
            self.show_status(f"Session saved: {format_duration(sess.duration_secs)}, {subj_name}")
            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot save session", str(exc))
