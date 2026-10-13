"""Timer page – interactive stopwatch and today's session summary."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.errors import AppError
from study_tracker.core.formatting import format_duration, format_duration_short, format_time
from study_tracker.services import session_service, subject_service, task_service
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

        self._build_ui()
        self._signals.timer_tick.connect(self._on_tick)
        self._signals.timer_state_changed.connect(self._sync_with_timer_state)
        self._signals.sessions_changed.connect(self._refresh_today_sessions)
        self._signals.subjects_changed.connect(self._on_subjects_changed)
        self._signals.tasks_changed.connect(self._on_tasks_changed)
        self._refresh_today_sessions()
        self._sync_with_timer_state()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
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
        root.addWidget(self._today_table)

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

        if active:
            s_idx = self._subject_combo.findData(self._timer.subject_id)
            if s_idx >= 0 and self._subject_combo.currentIndex() != s_idx:
                self._subject_combo.setCurrentIndex(s_idx)
            t_idx = self._task_combo.findData(self._timer.task_id)
            if t_idx >= 0 and self._task_combo.currentIndex() != t_idx:
                self._task_combo.setCurrentIndex(t_idx)
            if self._notes_edit.text() != self._timer.notes:
                self._notes_edit.setText(self._timer.notes)

            self._pause_btn.setText("▶  Resume" if paused else "⏸  Pause")
            self._status_label.setText("Paused" if paused else "Running…")
            self._status_label.setStyleSheet(
                "font-size: 11pt; color: #FFB870;" if paused else "font-size: 11pt; color: #7FE3A2;"
            )
        else:
            self._pause_btn.setText("⏸  Pause")
            self._status_label.setText("Idle")
            self._status_label.setStyleSheet("font-size: 11pt; color: #C4D3E1;")
            self._display.setText("00:00:00")

    def _on_tick(self) -> None:
        if self._timer.is_active:
            secs = self._timer.elapsed_seconds()
            self._display.setText(format_duration_short(secs))

    def _on_start(self) -> None:
        subj_id = self._subject_combo.currentData()
        if not subj_id:
            warn(self, "No subject", "Please select a subject first.")
            return
        task_id = self._task_combo.currentData()
        notes = self._notes_edit.text()

        try:
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

        dur = self._timer.elapsed_seconds()
        # If under 60 seconds, ask to save or discard
        if dur < 60:
            msg = f"This session is only {dur} seconds. Save it anyway?"
            if not confirm(self, "Short session", msg):
                self._timer.discard()
                self._sync_with_timer_state()
                self._signals.timer_state_changed.emit()
                return

        offset = datetime.now().astimezone().utcoffset()
        offset_mins = int(offset.total_seconds() // 60) if offset else 0

        try:
            self._timer.stop(utc_offset_mins=offset_mins)
            self._sync_with_timer_state()
            self._notes_edit.clear()
            self._signals.timer_state_changed.emit()
            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot stop timer", str(exc))

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
        sessions = session_service.get_all(self._conn, date_from=today, date_to=today)
        self._today_table.setRowCount(len(sessions))

        subj_map = {s.id: s for s in subject_service.get_all(self._conn, include_archived=True)}
        task_map = {t.id: t for t in task_service.get_all(self._conn, include_archived=True)}

        total_secs = 0
        for row, s in enumerate(sessions):
            total_secs += s.duration_secs

            time_str = (
                f"{format_time(s.start_utc)} – {format_time(s.end_utc)}"
                if s.start_utc
                else "Duration only"
            )
            self._today_table.setItem(row, 0, QTableWidgetItem(time_str))
            self._today_table.setItem(row, 1, QTableWidgetItem(format_duration(s.duration_secs)))

            s_name = subj_map[s.subject_id].name if s.subject_id in subj_map else f"#{s.subject_id}"
            self._today_table.setItem(row, 2, QTableWidgetItem(s_name))

            t_title = task_map[s.task_id].title if s.task_id and s.task_id in task_map else "—"
            self._today_table.setItem(row, 3, QTableWidgetItem(t_title))

            self._today_table.setItem(row, 4, QTableWidgetItem(s.notes))

        self._today_total_label.setText(f"<b>Today's total: {format_duration(total_secs)}</b>")
