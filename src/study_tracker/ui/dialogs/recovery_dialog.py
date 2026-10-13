"""Recovery dialog for recovering after app crash or unexpected exit."""

from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.formatting import format_datetime, format_duration
from study_tracker.db import subjects_repo
from study_tracker.db.timer_state_repo import TimerState


class RecoveryDialog(QDialog):
    """Offers choices when a previous timer was interrupted."""

    SAVE = 1
    RESUME = 2
    DISCARD = 3
    RESUME_BREAK = 4
    START_NEXT_FOCUS = 5
    END_POMODORO = 6

    def __init__(
        self,
        conn: sqlite3.Connection,
        state: TimerState,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._state = state
        self._action = self.SAVE

        self.setWindowTitle("Study Session Recovery")
        self.setMinimumWidth(450)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        subj = subjects_repo.get_by_id(self._conn, self._state.subject_id)
        subj_name = subj.name if subj else "Unknown Subject"

        # Calculate duration up to last heartbeat
        from datetime import datetime
        s_dt = datetime.strptime(self._state.start_utc, "%Y-%m-%dT%H:%M:%SZ")
        h_dt = datetime.strptime(self._state.last_heartbeat, "%Y-%m-%dT%H:%M:%SZ")
        dur = max(1, self._state.paused_secs + int((h_dt - s_dt).total_seconds()))
        if self._state.mode == "countdown" and self._state.countdown_target_seconds is not None:
            dur = min(dur, self._state.countdown_target_seconds)

        is_pomodoro_break = self._state.mode == "pomodoro" and self._state.phase != "focus"
        title_lbl = QLabel(
            "<h3>Pomodoro break interrupted</h3>"
            if is_pomodoro_break
            else "<h3>Unsaved Study Session Found</h3>"
        )
        layout.addWidget(title_lbl)

        if is_pomodoro_break:
            info_text = (
                f"<p>The {self._state.phase.replace('_', ' ')} was interrupted.</p>"
                "<p>Break time is never added to study totals.</p>"
            )
        else:
            info_text = (
            f"<p>An interrupted timer session was recovered:</p>"
            f"<ul>"
            f"<li><b>Subject:</b> {subj_name}</li>"
            f"<li><b>Started:</b> {format_datetime(self._state.start_utc)}</li>"
            f"<li><b>Last recorded activity:</b> {format_datetime(self._state.last_heartbeat)}</li>"
            f"<li><b>Duration:</b> {format_duration(dur)}</li>"
            f"</ul>"
            f"<p><i>Time after the last recorded activity is not counted.</i></p>"
            )
            if self._state.mode == "countdown" and self._state.countdown_target_seconds is not None:
                remaining = max(0, self._state.countdown_target_seconds - dur)
                info_text += f"<p><b>Countdown remaining:</b> {format_duration(remaining)}</p>"
        info_lbl = QLabel(info_text)
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if is_pomodoro_break:
            for label, action in (
                ("Resume break", self.RESUME_BREAK),
                ("Start next focus", self.START_NEXT_FOCUS),
                ("End run", self.END_POMODORO),
            ):
                button = QPushButton(label)
                button.clicked.connect(lambda checked=False, value=action: self._choose(value))
                btn_row.addWidget(button)
        else:
            save_btn = QPushButton("Save Session")
            save_btn.clicked.connect(self._on_save)
            resume_btn = QPushButton("Resume (Paused)")
            resume_btn.setProperty("flat", True)
            resume_btn.clicked.connect(self._on_resume)
            discard_btn = QPushButton("Discard")
            discard_btn.setProperty("flat", True)
            discard_btn.setStyleSheet("color: #D32F2F;")
            discard_btn.clicked.connect(self._on_discard)
            btn_row.addWidget(save_btn)
            btn_row.addWidget(resume_btn)
            btn_row.addWidget(discard_btn)
        layout.addLayout(btn_row)

    def _on_save(self) -> None:
        self._action = self.SAVE
        self.accept()

    def _on_resume(self) -> None:
        self._action = self.RESUME
        self.accept()

    def _on_discard(self) -> None:
        self._action = self.DISCARD
        self.accept()

    def _choose(self, action: int) -> None:
        self._action = action
        self.accept()

    @property
    def action(self) -> int:
        return self._action
