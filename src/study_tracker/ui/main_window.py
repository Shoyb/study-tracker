"""Main application window."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core import paths
from study_tracker.core.clock import Clock
from study_tracker.core.errors import DatabaseError
from study_tracker.core.formatting import format_duration, format_duration_short
from study_tracker.db import settings_repo, subjects_repo, tasks_repo
from study_tracker.services.alert_service import AlertService
from study_tracker.services.timer_service import TimerService
from study_tracker.ui.notifications import NotificationBanner
from study_tracker.ui.pages.analytics_page import AnalyticsPage
from study_tracker.ui.pages.dashboard_page import DashboardPage
from study_tracker.ui.pages.records_page import RecordsPage
from study_tracker.ui.pages.settings_page import SettingsPage
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

        phase_prefix = ""
        if self._timer_svc.mode == "pomodoro":
            secs = self._timer_svc.remaining_seconds
            phase = (self._timer_svc.phase or "focus").replace("_", " ").title()
            phase_prefix = f"Pomodoro {phase} — "
        elif self._timer_svc.mode == "countdown":
            secs = self._timer_svc.remaining_seconds
            phase_prefix = "Countdown — "
        else:
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
        self._info_label.setText(f"{status_prefix}{phase_prefix}{subj_name}{task_title}")
        self._pause_btn.setText("▶  Resume" if self._timer_svc.is_paused else "⏸  Pause")


class MainWindow(QMainWindow):
    """The single top-level window for Study Tracker.

    Layout::

        ┌──────────────────────────────────────────┐
        │  Sidebar (190 px)  │  Content area        │
        │                    │  ┌──────────────────┐ │
        │  Dashboard         │  │ Timer bar (top)  │ │
        │  Timer             │  ├──────────────────┤ │
        │  Records           │  │  Active page     │ │
        │  Analytics         │  │                  │ │
        │  Settings          │                       │
        ├────────────────────────────────────────────┤
        │  Status bar                                │
        └────────────────────────────────────────────┘
    """

    _PAGE_NAMES = [
        "Dashboard",
        "Timer",
        "Records",
        "Analytics",
        "Settings",
    ]

    def __init__(
        self,
        signals: AppSignals,
        conn: sqlite3.Connection | None = None,
        clock: Clock | None = None,
        on_restore: Callable[[Path], None] | None = None,
        database_path: Path | None = None,
        log_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._signals = signals
        self._conn = conn
        self._clock = clock or Clock()
        self._last_study_day = self._clock.local_date()
        self._on_restore = on_restore
        self._database_path = database_path
        self._log_path = log_path
        self._timer_svc = TimerService(self._conn, self._clock) if self._conn is not None else None
        self._tray_icon: QSystemTrayIcon | None = None
        self._exit_requested = False

        self.setWindowTitle("Study Tracker")
        self.setWindowIcon(QIcon(str(paths.icon_path())))
        self.setMinimumSize(QSize(900, 600))
        self.resize(1100, 700)
        self._build_ui()
        self._setup_tray_icon()
        self._setup_shortcuts()
        self._setup_timers()

        self._signals.timer_state_changed.connect(self._update_timer_bar)
        self._signals.pomodoro_phase_changed.connect(self._notify_pomodoro_phase)
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
        self._notification_banner = NotificationBanner(right_col)
        right_layout.addWidget(self._notification_banner)
        right_layout.addWidget(self._timer_bar)

        self._stack = QStackedWidget(right_col)
        for name in self._PAGE_NAMES:
            if name == "Dashboard" and self._conn is not None:
                self._dashboard_page = DashboardPage(
                    self._conn,
                    self._signals,
                    self._clock,
                    on_day_selected=self._show_history_date,
                )
                self._stack.addWidget(self._dashboard_page)
            elif name == "Timer" and self._conn is not None and self._timer_svc is not None:
                self._timer_page = TimerPage(
                    self._conn, self._timer_svc, self._signals, self._clock
                )
                self._stack.addWidget(self._timer_page)
            elif name == "Records" and self._conn is not None:
                self._records_page = RecordsPage(self._conn, self._signals, self._clock)
                self._history_page = self._records_page._history_page
                self._tasks_page = self._records_page._tasks_page
                self._subjects_page = self._records_page._subjects_page
                self._exams_page = self._records_page._exams_page
                self._calendar_page = self._records_page._calendar_page
                self._stack.addWidget(self._records_page)
            elif name == "Analytics" and self._conn is not None:
                self._analytics_page = AnalyticsPage(self._conn, self._signals, self._clock)
                self._stack.addWidget(self._analytics_page)
            elif name == "Settings" and self._conn is not None:
                self._settings_page = SettingsPage(
                    self._conn,
                    self._signals,
                    self._clock,
                    on_restore=self._restore_from_settings,
                    database_path=self._database_path,
                    log_path=self._log_path,
                )
                self._stack.addWidget(self._settings_page)
            else:
                self._stack.addWidget(PlaceholderPage(name))
        right_layout.addWidget(self._stack)

        root_layout.addWidget(right_col)

        # Status bar
        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    def _setup_shortcuts(self) -> None:
        """Ctrl+1 onward navigates to the corresponding sidebar page."""
        for i in range(len(self._PAGE_NAMES)):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda idx=i: self._navigate(idx))

    def _notify_pomodoro_phase(self, phase: str) -> None:
        label = phase.replace("_", " ").title()
        message = "Pomodoro run ended" if phase == "ended" else f"Pomodoro {label} started"
        self.show_status(message, timeout_ms=10000)
        if self._tray_icon is not None:
            self._tray_icon.showMessage(
                "Study Tracker", message, QSystemTrayIcon.MessageIcon.Information, 10000
            )
        if settings_repo.get(self._conn, "pomodoro_sound") == "1":
            try:
                import winsound

                winsound.MessageBeep()
            except (ImportError, RuntimeError):
                pass

    def _setup_timers(self) -> None:
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(250)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(15000)
        self._heartbeat_timer.timeout.connect(self._on_heartbeat)
        self._heartbeat_timer.start()

        self._alert_timer = QTimer(self)
        self._alert_timer.setInterval(60000)
        self._alert_timer.timeout.connect(self._check_baseline_alert)
        self._alert_timer.start()
        QTimer.singleShot(0, self._check_baseline_alert)
        self._signals.day_changed.connect(self._check_baseline_alert)

    def _check_baseline_alert(self) -> None:
        if self._conn is None or not hasattr(self, "_notification_banner"):
            return
        try:
            alert = AlertService(self._conn, self._clock).evaluate()
        except Exception:
            log.exception("Baseline alert evaluation failed.")
            return
        if alert is None:
            return
        self._notification_banner.notify(
            "Study goal alert:",
            alert.message,
            alert.level,
            tray=self._tray_icon,
            sound=settings_repo.get(self._conn, "alert_sound") == "1",
        )
        self.show_status(alert.message, timeout_ms=10000)

    def _setup_tray_icon(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("System tray is unavailable; minimize-to-tray is disabled.")
            return

        tray = QSystemTrayIcon(QIcon(str(paths.icon_path())), self)
        tray.setToolTip("Study Tracker")
        menu = QMenu(self)
        open_action = QAction("Open Study Tracker", self)
        open_action.triggered.connect(self._restore_from_tray)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self._exit_from_tray)
        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray_icon = tray

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _exit_from_tray(self) -> None:
        self._exit_requested = True
        self.close()

    def _tray_minimize_enabled(self) -> bool:
        return (
            self._conn is not None
            and self._tray_icon is not None
            and settings_repo.get(self._conn, "tray_minimize") != "0"
        )

    def _ensure_tray_icon_visible(self) -> None:
        if self._tray_icon is not None and not self._tray_icon.isVisible():
            self._tray_icon.show()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            if self._tray_minimize_enabled():
                self._ensure_tray_icon_visible()
                QTimer.singleShot(0, self.hide)

    # ------------------------------------------------------------------
    # Timer & background handlers
    # ------------------------------------------------------------------

    def _on_tick(self) -> None:
        self._signals.timer_tick.emit()
        current_study_day = self._clock.local_date()
        if current_study_day != self._last_study_day:
            self._last_study_day = current_study_day
            self._signals.day_changed.emit()
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

        from study_tracker.ui.dialogs.recovery_dialog import RecoveryDialog

        dlg = RecoveryDialog(self._conn, state, self)
        if dlg.exec() != RecoveryDialog.DialogCode.Accepted:
            return

        if dlg.action == RecoveryDialog.SAVE:
            offset_mins = self._clock.local_utc_offset_minutes()
            sess = self._timer_svc.recover_and_save(state, utc_offset_mins=offset_mins)
            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
            if sess is not None:
                self.show_status(
                    f"Recovered session saved ({format_duration(sess.duration_secs)})."
                )
            else:
                self.show_status("Recovered Pomodoro break ended without adding study time.")
        elif dlg.action == RecoveryDialog.RESUME:
            self._timer_svc.recover_as_paused(state)
            self._signals.timer_state_changed.emit()
            self._navigate(1)
            self.show_status("Recovered session loaded (paused).")
        elif dlg.action == RecoveryDialog.RESUME_BREAK:
            self._timer_svc.recover_as_paused(state)
            self._timer_svc.resume()
            self._signals.timer_state_changed.emit()
            self._navigate(1)
            self.show_status("Pomodoro break resumed.")
        elif dlg.action == RecoveryDialog.START_NEXT_FOCUS:
            self._timer_svc.recover_as_paused(state)
            self._timer_svc.skip_break()
            self._signals.timer_state_changed.emit()
            self._navigate(1)
            self.show_status("Pomodoro focus started.")
        elif dlg.action == RecoveryDialog.END_POMODORO:
            self._timer_svc.discard()
            self.show_status("Pomodoro run ended.")
        elif dlg.action == RecoveryDialog.DISCARD:
            self._timer_svc.discard()
            self.show_status("Interrupted session discarded.")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if (
            not self._exit_requested
            and self._tray_minimize_enabled()
        ):
            self.hide()
            event.ignore()
            return
        if self._timer_svc and self._timer_svc.is_active:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Timer Active")
            msg_box.setText(
                "A study timer is currently active.\nWhat would you like to do before closing?"
            )
            stop_btn = msg_box.addButton("Stop & Save", QMessageBox.ButtonRole.AcceptRole)
            pause_btn = msg_box.addButton("Pause & Quit", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(cancel_btn)

            msg_box.exec()
            clicked = msg_box.clickedButton()

            if clicked == stop_btn:
                offset_mins = self._clock.local_utc_offset_minutes()
                try:
                    self._timer_svc.stop(utc_offset_mins=offset_mins)
                    event.accept()
                except Exception as exc:
                    warn(self, "Cannot stop timer", str(exc))
                    self._exit_requested = False
                    event.ignore()
            elif clicked == pause_btn:
                if not self._timer_svc.is_paused:
                    self._timer_svc.pause()
                event.accept()
            else:
                self._exit_requested = False
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

    def _show_history_date(self, local_date: str) -> None:
        """Navigate from a chart to the History view filtered to one day."""
        if hasattr(self, "_records_page"):
            self._records_page.show_history_date(local_date)
            self._navigate(self._PAGE_NAMES.index("Records"))

    def _restore_from_settings(self, backup_path: Path) -> None:
        """Guard a destructive database replacement behind an idle timer."""
        if self._timer_svc and self._timer_svc.is_active:
            raise DatabaseError("Stop or discard the active timer before restoring a backup.")
        if self._on_restore is None:
            raise DatabaseError("Restore is unavailable in this window.")
        self._on_restore(backup_path)

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

        from study_tracker.core.errors import AppError
        from study_tracker.db import subjects_repo
        from study_tracker.services import session_service
        from study_tracker.ui.dialogs.session_dialog import SessionDialog

        offset_mins = self._clock.local_utc_offset_minutes()

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
