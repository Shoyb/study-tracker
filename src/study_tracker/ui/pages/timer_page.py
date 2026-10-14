"""Timer page – interactive stopwatch and today's session summary."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.errors import AppError
from study_tracker.core.formatting import format_duration, format_duration_short, format_time
from study_tracker.db import settings_repo
from study_tracker.domain.allocation import allocate_by_day
from study_tracker.services import session_service, subject_service, task_service
from study_tracker.services.pomodoro_service import PomodoroService
from study_tracker.services.timer_service import TimerService
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.confirm import confirm, warn

log = logging.getLogger(__name__)


class TimerPage(QWidget):
    """Timer page with large stopwatch display, controls, and today's sessions."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        timer_svc: TimerService,
        signals: AppSignals,
        clock,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._timer = timer_svc
        self._signals = signals
        self._clock = clock
        self._pomodoro = PomodoroService(conn, timer_svc)
        self._floating_clock: QDialog | None = None
        self._floating_header: QWidget | None = None
        self._floating_title: QLabel | None = None
        self._floating_indicator: QLabel | None = None
        self._floating_pause_btn: QPushButton | None = None
        self._floating_display: QLabel | None = None
        self._floating_status: QLabel | None = None
        self._floating_drag_offset: QPoint | None = None

        self._build_ui()
        self._signals.timer_tick.connect(self._on_tick)
        self._signals.timer_state_changed.connect(self._sync_with_timer_state)
        self._signals.sessions_changed.connect(self._refresh_today_sessions)
        self._signals.subjects_changed.connect(self._on_subjects_changed)
        self._signals.tasks_changed.connect(self._on_tasks_changed)
        self._refresh_today_sessions()
        self._sync_with_timer_state()

    def _build_ui(self) -> None:
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self._scroll_area.setWidget(content)
        page_layout.addWidget(self._scroll_area)

        root = QVBoxLayout(content)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # 1. Stopwatch Card
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #1F2A32; border: 1px solid #3A4F5F; "
            "border-radius: 12px; padding: 20px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        mode_row = QHBoxLayout()
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Stopwatch", "stopwatch")
        self._mode_combo.addItem("Pomodoro", "pomodoro")
        self._mode_combo.addItem("Countdown", "countdown")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._preset_combo = QComboBox()
        for preset in self._pomodoro.presets():
            self._preset_combo.addItem(preset.name, preset.id)
        self._skip_break_btn = QPushButton("Skip break")
        self._skip_break_btn.clicked.connect(self._skip_break)
        self._skip_break_btn.setEnabled(False)
        self._float_btn = QPushButton("Float clock")
        self._float_btn.clicked.connect(self._show_floating_clock)
        mode_row.addWidget(QLabel("Mode:"))
        mode_row.addWidget(self._mode_combo)
        mode_row.addWidget(QLabel("Preset:"))
        mode_row.addWidget(self._preset_combo)
        mode_row.addWidget(self._skip_break_btn)
        mode_row.addWidget(self._float_btn)
        mode_row.addStretch()
        card_layout.addLayout(mode_row)

        self._countdown_controls = QWidget()
        countdown_row = QHBoxLayout(self._countdown_controls)
        countdown_row.setContentsMargins(0, 0, 0, 0)
        self._countdown_hours = QSpinBox()
        self._countdown_hours.setRange(0, 24)
        self._countdown_hours.setSuffix(" h")
        self._countdown_minutes = QSpinBox()
        self._countdown_minutes.setRange(0, 59)
        self._countdown_minutes.setSuffix(" min")
        self._countdown_minutes.setSingleStep(5)
        self._countdown_minutes.setValue(25)
        countdown_row.addWidget(QLabel("Countdown length:"))
        countdown_row.addWidget(self._countdown_hours)
        countdown_row.addWidget(self._countdown_minutes)
        countdown_row.addStretch()
        card_layout.addWidget(self._countdown_controls)

        # Elapsed display
        self._display = QLabel("00:00:00")
        self._display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._display.setStyleSheet(
            "font-size: 52pt; font-weight: bold; color: #8AC7FF; "
            "font-family: 'Consolas', monospace;"
        )
        card_layout.addWidget(self._display)

        # Status text
        self._status_label = QLabel("Idle")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet("font-size: 11pt; color: #C4D3E1; font-weight: 500;")
        card_layout.addWidget(self._status_label)

        # Subject & Task Pickers
        picker_row = QHBoxLayout()
        picker_row.setSpacing(12)

        self._subject_combo = QComboBox()
        self._subject_combo.setMinimumWidth(180)
        self._populate_subjects()
        self._subject_combo.currentIndexChanged.connect(self._on_subject_changed)

        self._task_combo = QComboBox()
        self._task_combo.setMinimumWidth(220)
        self._populate_tasks()

        picker_row.addWidget(QLabel("Subject:"))
        picker_row.addWidget(self._subject_combo)
        picker_row.addWidget(QLabel("Task:"))
        picker_row.addWidget(self._task_combo)
        picker_row.addStretch()
        card_layout.addLayout(picker_row)

        # Notes input
        notes_row = QHBoxLayout()
        notes_row.setSpacing(8)
        self._notes_edit = QLineEdit()
        self._notes_edit.setPlaceholderText("Notes for this study session (optional)…")
        self._notes_edit.textChanged.connect(self._on_notes_changed)
        notes_row.addWidget(QLabel("Notes:"))
        notes_row.addWidget(self._notes_edit)
        card_layout.addLayout(notes_row)

        # Control Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._start_btn = QPushButton("▶  Start")
        self._start_btn.setMinimumHeight(40)
        self._start_btn.setMinimumWidth(120)
        self._start_btn.clicked.connect(self._on_start)

        self._pause_btn = QPushButton("⏸  Pause")
        self._pause_btn.setMinimumHeight(40)
        self._pause_btn.setMinimumWidth(120)
        self._pause_btn.clicked.connect(self._on_pause_resume)

        self._stop_btn = QPushButton("⏹  Stop & Save")
        self._stop_btn.setMinimumHeight(40)
        self._stop_btn.setMinimumWidth(130)
        self._stop_btn.clicked.connect(self._on_stop)

        self._discard_btn = QPushButton("Discard")
        self._discard_btn.setProperty("flat", True)
        self._discard_btn.setMinimumHeight(40)
        self._discard_btn.setStyleSheet("color: #D32F2F;")
        self._discard_btn.clicked.connect(self._on_discard)

        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._pause_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addWidget(self._discard_btn)
        card_layout.addLayout(btn_row)

        root.addWidget(card)

        # 2. Today's Sessions Section
        today_header = QHBoxLayout()
        self._today_title = QLabel("<h3>Today's Study Sessions</h3>")
        self._today_total_label = QLabel("<b>Today's total: 0 min</b>")
        self._today_total_label.setStyleSheet("color: #8AC7FF; font-size: 11pt;")
        today_header.addWidget(self._today_title)
        today_header.addStretch()
        today_header.addWidget(self._today_total_label)
        root.addLayout(today_header)

        self._today_table = QTableWidget()
        self._today_table.setStyleSheet(
            "background: #1F2A32; color: #E6EDF3; border: 1px solid #3A4F5F; "
            "selection-background-color: #175987; selection-color: #FFFFFF;"
        )
        self._today_table.setColumnCount(5)
        self._today_table.setHorizontalHeaderLabels([
            "Time", "Duration", "Subject", "Task", "Notes"
        ])
        self._today_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        for col in range(4):
            self._today_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self._today_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._today_table.setMinimumHeight(180)
        root.addWidget(self._today_table)
        self._on_mode_changed()

    def _populate_subjects(self) -> None:
        prev = self._subject_combo.currentData()
        self._subject_combo.clear()
        subjects = subject_service.get_active(self._conn)
        for s in subjects:
            self._subject_combo.addItem(s.name, s.id)
        if prev:
            idx = self._subject_combo.findData(prev)
            if idx >= 0:
                self._subject_combo.setCurrentIndex(idx)

    def _populate_tasks(self) -> None:
        prev = self._task_combo.currentData()
        self._task_combo.clear()
        self._task_combo.addItem("None (general study)", None)
        subj_id = self._subject_combo.currentData()
        if subj_id:
            tasks = task_service.get_all(
                self._conn, subject_id=subj_id, status="open", include_archived=False
            )
            for t in tasks:
                self._task_combo.addItem(t.title, t.id)
        if prev:
            idx = self._task_combo.findData(prev)
            if idx >= 0:
                self._task_combo.setCurrentIndex(idx)

    def _on_subjects_changed(self) -> None:
        self._populate_subjects()
        self._populate_tasks()

    def _on_tasks_changed(self) -> None:
        self._populate_tasks()

    def _on_subject_changed(self) -> None:
        self._populate_tasks()

    def _on_notes_changed(self, text: str) -> None:
        if self._timer.is_active:
            self._timer.set_notes(text)

    def _sync_with_timer_state(self) -> None:
        active = self._timer.is_active
        paused = self._timer.is_paused

        self._start_btn.setEnabled(not active)
        self._pause_btn.setEnabled(active)
        self._stop_btn.setEnabled(active)
        self._discard_btn.setEnabled(active)

        self._subject_combo.setEnabled(not active)
        self._task_combo.setEnabled(not active)
        self._mode_combo.setEnabled(not active)
        self._preset_combo.setEnabled(not active)
        self._countdown_hours.setEnabled(not active)
        self._countdown_minutes.setEnabled(not active)
        self._skip_break_btn.setEnabled(
            active
            and self._timer.mode == "pomodoro"
            and self._timer.phase in {"short_break", "long_break"}
        )

        if active:
            if self._timer.mode in {"pomodoro", "countdown"}:
                self._mode_combo.setCurrentIndex(self._mode_combo.findData(self._timer.mode))
            s_idx = self._subject_combo.findData(self._timer.subject_id)
            if s_idx >= 0 and self._subject_combo.currentIndex() != s_idx:
                self._subject_combo.setCurrentIndex(s_idx)
            t_idx = self._task_combo.findData(self._timer.task_id)
            if t_idx >= 0 and self._task_combo.currentIndex() != t_idx:
                self._task_combo.setCurrentIndex(t_idx)
            if self._notes_edit.text() != self._timer.notes:
                self._notes_edit.setText(self._timer.notes)

            self._pause_btn.setText("▶  Resume" if paused else "⏸  Pause")
            if self._timer.mode in {"pomodoro", "countdown"}:
                phase = (
                    (self._timer.phase or "focus").replace("_", " ").title()
                    if self._timer.mode == "pomodoro"
                    else "Countdown"
                )
                status = "Paused" if paused else phase
                self._status_label.setText(status)
                self._display.setText(format_duration_short(self._timer.remaining_seconds))
            else:
                self._status_label.setText("Paused" if paused else "Running…")
            self._status_label.setStyleSheet(
                "font-size: 11pt; color: #FFB870;" if paused else "font-size: 11pt; color: #7FE3A2;"
            )
        else:
            self._pause_btn.setText("⏸  Pause")
            self._status_label.setText("Idle")
            self._status_label.setStyleSheet("font-size: 11pt; color: #C4D3E1;")
            self._display.setText("00:00:00")
        self._refresh_floating_clock()

    def _show_floating_clock(self) -> None:
        if self._floating_clock is None:
            self._floating_clock = QDialog(
                self.window(),
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint,
            )
            self._floating_clock.setObjectName("FloatingClock")
            self._floating_clock.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self._floating_clock.setFixedSize(330, 186)
            self._floating_clock.setStyleSheet(
                "QDialog#FloatingClock { background: transparent; }"
                "QFrame#FloatingClockSurface { background-color: #1F2A32; "
                "border: 1px solid #3A4F5F; border-radius: 14px; }"
                "QLabel#FloatingClockTitle { color: #AAB9C5; font-size: 8pt; "
                "font-weight: 700; }"
                "QLabel#FloatingClockDisplay { color: #90CAF9; font-family: Consolas; "
                "font-size: 31pt; font-weight: 700; }"
                "QLabel#FloatingClockStatus { color: #D3DDE5; font-size: 9pt; }"
                "QLabel#FloatingClockIndicator { color: #7FE3A2; font-size: 11pt; }"
                "QPushButton#FloatingClockClose { background: transparent; color: #AAB9C5; "
                "border: none; border-radius: 14px; min-width: 28px; max-width: 28px; "
                "min-height: 28px; max-height: 28px; padding: 0; font-size: 15pt; }"
                "QPushButton#FloatingClockClose:hover { background: #3A4F5F; color: #FFFFFF; }"
                "QPushButton#FloatingClockPause { background: #1976D2; color: #FFFFFF; "
                "border: none; border-radius: 6px; padding: 5px 14px; min-width: 70px; }"
                "QPushButton#FloatingClockPause:hover { background: #2D8BE0; }"
                "QPushButton#FloatingClockOpen { background: transparent; color: #C4D3E1; "
                "border: 1px solid #52616D; border-radius: 6px; padding: 5px 12px; }"
                "QPushButton#FloatingClockOpen:hover { background: #2B3943; }"
            )

            window_layout = QVBoxLayout(self._floating_clock)
            window_layout.setContentsMargins(10, 10, 10, 10)
            surface = QFrame()
            surface.setObjectName("FloatingClockSurface")
            shadow = QGraphicsDropShadowEffect(surface)
            shadow.setBlurRadius(24)
            shadow.setOffset(0, 6)
            shadow.setColor(QColor(0, 0, 0, 110))
            surface.setGraphicsEffect(shadow)
            window_layout.addWidget(surface)

            layout = QVBoxLayout(surface)
            layout.setContentsMargins(15, 10, 15, 12)
            layout.setSpacing(4)
            self._floating_header = QWidget()
            header_row = QHBoxLayout(self._floating_header)
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(7)
            self._floating_indicator = QLabel("●")
            self._floating_indicator.setObjectName("FloatingClockIndicator")
            self._floating_title = QLabel("STUDY TIMER")
            self._floating_title.setObjectName("FloatingClockTitle")
            close_button = QPushButton("×")
            close_button.setObjectName("FloatingClockClose")
            close_button.setToolTip("Hide floating clock")
            close_button.clicked.connect(self._floating_clock.hide)
            header_row.addWidget(self._floating_indicator)
            header_row.addWidget(self._floating_title)
            header_row.addStretch()
            header_row.addWidget(close_button)
            draggable_widgets = (
                self._floating_header,
                self._floating_indicator,
                self._floating_title,
            )
            for draggable in draggable_widgets:
                draggable.installEventFilter(self)

            self._floating_display = QLabel("00:00:00")
            self._floating_display.setObjectName("FloatingClockDisplay")
            self._floating_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._floating_status = QLabel("Idle")
            self._floating_status.setObjectName("FloatingClockStatus")
            self._floating_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._floating_pause_btn = QPushButton("Pause")
            self._floating_pause_btn.setObjectName("FloatingClockPause")
            self._floating_pause_btn.clicked.connect(self._on_pause_resume)
            self._floating_open_btn = QPushButton("Open timer")
            self._floating_open_btn.setObjectName("FloatingClockOpen")
            self._floating_open_btn.clicked.connect(self._return_to_timer)
            controls = QHBoxLayout()
            controls.setContentsMargins(0, 3, 0, 0)
            controls.addWidget(self._floating_pause_btn)
            controls.addStretch()
            controls.addWidget(self._floating_open_btn)
            layout.addWidget(self._floating_header)
            layout.addWidget(self._floating_display)
            layout.addWidget(self._floating_status)
            layout.addLayout(controls)

        self._refresh_floating_clock()
        self._floating_clock.show()
        self._floating_clock.raise_()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        draggable_widgets = (
            self._floating_header,
            self._floating_title,
            self._floating_indicator,
        )
        if watched in draggable_widgets and isinstance(event, QMouseEvent):
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._floating_drag_offset = (
                    event.globalPosition().toPoint()
                    - self._floating_clock.frameGeometry().topLeft()
                )
                return True
            if event.type() == QEvent.Type.MouseMove and self._floating_drag_offset is not None:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    self._floating_clock.move(
                        event.globalPosition().toPoint() - self._floating_drag_offset
                    )
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._floating_drag_offset = None
        return super().eventFilter(watched, event)

    def _return_to_timer(self) -> None:
        self._floating_clock.hide()
        window = self.window()
        navigate = getattr(window, "_navigate", None)
        if navigate is not None:
            navigate(1)
        window.showNormal()
        window.raise_()
        window.activateWindow()

    def _refresh_floating_clock(self) -> None:
        if self._floating_clock is None or not self._floating_clock.isVisible():
            return
        assert self._floating_display is not None
        assert self._floating_status is not None
        assert self._floating_pause_btn is not None
        self._floating_display.setText(self._display.text())
        self._floating_pause_btn.setEnabled(self._timer.is_active)
        self._floating_pause_btn.setText("Resume" if self._timer.is_paused else "Pause")
        status = self._status_label.text()
        self._floating_indicator.setStyleSheet(
            "color: #FFB870;" if self._timer.is_paused else "color: #7FE3A2;"
        )
        if self._timer.is_active:
            details = [status, self._subject_combo.currentText()]
            task = self._task_combo.currentText()
            if task and task != "None (general study)":
                details.append(task)
            status = " · ".join(details)
        self._floating_status.setText(status)
        self._floating_status.setToolTip(status)

    def _on_tick(self) -> None:
        if self._timer.is_active:
            previous_phase = self._timer.phase
            previous_mode = self._timer.mode
            if previous_mode == "countdown":
                completed = self._timer.advance_countdown_if_due(
                    self._clock.local_utc_offset_minutes()
                )
            else:
                completed = self._timer.advance_pomodoro_if_due(
                    self._clock.local_utc_offset_minutes()
                )
            if completed is not None:
                self._signals.sessions_changed.emit()
                self._signals.tasks_changed.emit()
                if previous_mode == "countdown":
                    self._signals.timer_state_changed.emit()
                    self._sync_with_timer_state()
                    self._status_label.setText("Countdown complete. Session saved.")
                    self._refresh_floating_clock()
                    return
            if previous_phase != self._timer.phase and self._timer.phase is not None:
                self._signals.pomodoro_phase_changed.emit(self._timer.phase)
            self._sync_with_timer_state()
            secs = self._timer.elapsed_seconds()
            if self._timer.mode in {"pomodoro", "countdown"}:
                self._display.setText(format_duration_short(self._timer.remaining_seconds))
            else:
                self._display.setText(format_duration_short(secs))
            self._refresh_floating_clock()

    def _on_start(self) -> None:
        subj_id = self._subject_combo.currentData()
        if not subj_id:
            warn(self, "No subject", "Please select a subject first.")
            return
        task_id = self._task_combo.currentData()
        notes = self._notes_edit.text()

        try:
            if self._mode_combo.currentData() == "pomodoro":
                preset_id = self._preset_combo.currentData()
                if preset_id is None:
                    warn(self, "No Pomodoro preset", "Create or select a Pomodoro preset first.")
                    return
                self._pomodoro.start(
                    preset_id, subject_id=subj_id, task_id=task_id, notes=notes
                )
                self._signals.pomodoro_phase_changed.emit("focus")
            elif self._mode_combo.currentData() == "countdown":
                target_seconds = (
                    self._countdown_hours.value() * 3600
                    + self._countdown_minutes.value() * 60
                )
                if target_seconds <= 0:
                    warn(self, "Invalid countdown", "Choose a countdown longer than 0 minutes.")
                    return
                self._timer.start_countdown(
                    subject_id=subj_id,
                    target_seconds=target_seconds,
                    task_id=task_id,
                    notes=notes,
                )
            else:
                self._timer.start(subject_id=subj_id, task_id=task_id, notes=notes)
            self._sync_with_timer_state()
            self._signals.timer_state_changed.emit()
        except AppError as exc:
            warn(self, "Cannot start timer", str(exc))

    def _on_pause_resume(self) -> None:
        if not self._timer.is_active:
            return
        if self._timer.is_paused:
            self._timer.resume()
        else:
            self._timer.pause()
        self._sync_with_timer_state()
        self._signals.timer_state_changed.emit()

    def _on_stop(self) -> None:
        if not self._timer.is_active:
            return

        mode = self._timer.mode
        dur = self._timer.elapsed_seconds()
        # If under 60 seconds, ask to save or discard
        if dur < 60 and not (
            self._timer.mode == "pomodoro"
            and self._timer.phase in {"short_break", "long_break"}
        ):
            msg = f"This session is only {dur} seconds. Save it anyway?"
            if not confirm(self, "Short session", msg):
                self._timer.discard()
                self._sync_with_timer_state()
                self._signals.timer_state_changed.emit()
                return

        offset_mins = self._clock.local_utc_offset_minutes()

        try:
            self._timer.stop(utc_offset_mins=offset_mins)
            self._sync_with_timer_state()
            self._notes_edit.clear()
            self._signals.timer_state_changed.emit()
            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
            if mode == "pomodoro":
                self._signals.pomodoro_phase_changed.emit("ended")
        except AppError as exc:
            warn(self, "Cannot stop timer", str(exc))

    def _on_mode_changed(self) -> None:
        mode = self._mode_combo.currentData()
        self._preset_combo.setVisible(mode == "pomodoro")
        self._countdown_controls.setVisible(mode == "countdown")

    def _skip_break(self) -> None:
        self._timer.skip_break()
        self._sync_with_timer_state()
        self._signals.timer_state_changed.emit()
        self._signals.pomodoro_phase_changed.emit("focus")

    def _on_discard(self) -> None:
        if not self._timer.is_active:
            return
        msg = "Are you sure you want to discard this study session?"
        if not confirm(self, "Discard session", msg):
            return
        self._timer.discard()
        self._sync_with_timer_state()
        self._notes_edit.clear()
        self._signals.timer_state_changed.emit()

    def _refresh_today_sessions(self) -> None:
        today = self._clock.local_date()
        cutoff_minutes = int(settings_repo.get(self._conn, "day_cutoff_minutes") or "180")
        previous = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        sessions = session_service.get_all(self._conn, date_from=previous, date_to=today)
        allocated = [
            (session, allocate_by_day(session, cutoff_minutes).get(today, 0))
            for session in sessions
        ]
        allocated = [item for item in allocated if item[1] > 0]
        self._today_table.setRowCount(len(allocated))

        subj_map = {s.id: s for s in subject_service.get_all(self._conn, include_archived=True)}
        task_map = {t.id: t for t in task_service.get_all(self._conn, include_archived=True)}

        total_secs = 0
        for row, (s, allocated_secs) in enumerate(allocated):
            total_secs += allocated_secs

            time_str = (
                f"{format_time(s.start_utc)} – {format_time(s.end_utc)}"
                if s.start_utc
                else "Duration only"
            )
            self._today_table.setItem(row, 0, QTableWidgetItem(time_str))
            self._today_table.setItem(row, 1, QTableWidgetItem(format_duration(allocated_secs)))

            s_name = subj_map[s.subject_id].name if s.subject_id in subj_map else f"#{s.subject_id}"
            self._today_table.setItem(row, 2, QTableWidgetItem(s_name))

            t_title = task_map[s.task_id].title if s.task_id and s.task_id in task_map else "—"
            self._today_table.setItem(row, 3, QTableWidgetItem(t_title))

            self._today_table.setItem(row, 4, QTableWidgetItem(s.notes))

        self._today_total_label.setText(f"<b>Today's total: {format_duration(total_secs)}</b>")
