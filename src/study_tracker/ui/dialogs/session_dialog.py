"""SessionDialog for adding or editing study sessions."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.errors import AppError
from study_tracker.core.formatting import format_duration
from study_tracker.db.sessions_repo import Session
from study_tracker.services import subject_service, task_service
from study_tracker.ui.widgets.confirm import warn


class SessionDialog(QDialog):
    """Add / Edit study session dialog with timed and duration-only modes."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock,
        parent: QWidget | None = None,
        session: Session | None = None,
        default_subject_id: int | None = None,
        default_task_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._clock = clock
        self._session = session
        self._default_subject_id = default_subject_id
        self._default_task_id = default_task_id

        self.setWindowTitle("Edit Session" if session else "Add Session")
        self.setMinimumWidth(440)
        self._build_ui()
        if session:
            self._populate(session)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Mode Selection
        mode_row = QWidget()
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self._timed_radio = QRadioButton("Start & end times")
        self._duration_radio = QRadioButton("Duration only")
        self._timed_radio.setChecked(True)

        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._timed_radio)
        self._mode_group.addButton(self._duration_radio)
        self._timed_radio.toggled.connect(self._on_mode_toggled)

        mode_layout.addWidget(self._timed_radio)
        mode_layout.addWidget(self._duration_radio)
        mode_layout.addStretch()
        form.addRow("Session mode:", mode_row)

        # Subject
        self._subject_combo = QComboBox()
        self._subjects = subject_service.get_active(self._conn)
        if self._session and self._session.subject_id not in [s.id for s in self._subjects]:
            self._subjects = subject_service.get_all(self._conn, include_archived=True)

        for s in self._subjects:
            self._subject_combo.addItem(s.name, s.id)
        self._subject_combo.currentIndexChanged.connect(self._on_subject_changed)

        if self._default_subject_id:
            idx = self._subject_combo.findData(self._default_subject_id)
            if idx >= 0:
                self._subject_combo.setCurrentIndex(idx)
        form.addRow("Subject:", self._subject_combo)

        # Task (optional, filtered to open tasks of selected subject)
        self._task_combo = QComboBox()
        self._update_task_combo()
        form.addRow("Task (optional):", self._task_combo)

        # Date
        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        today_str = self._clock.local_date()
        self._date_edit.setDate(QDate.fromString(today_str, "yyyy-MM-dd"))
        form.addRow("Date:", self._date_edit)

        # Timed Widgets Container
        self._timed_container = QWidget()
        timed_layout = QFormLayout(self._timed_container)
        timed_layout.setContentsMargins(0, 0, 0, 0)

        times_row = QWidget()
        times_layout = QHBoxLayout(times_row)
        times_layout.setContentsMargins(0, 0, 0, 0)

        self._start_time = QTimeEdit()
        self._start_time.setDisplayFormat("HH:mm")
        self._start_time.setTime(QTime(9, 0))
        self._start_time.timeChanged.connect(self._update_calculated_duration)

        self._end_time = QTimeEdit()
        self._end_time.setDisplayFormat("HH:mm")
        self._end_time.setTime(QTime(10, 0))
        self._end_time.timeChanged.connect(self._update_calculated_duration)

        times_layout.addWidget(QLabel("From:"))
        times_layout.addWidget(self._start_time)
        times_layout.addWidget(QLabel("To:"))
        times_layout.addWidget(self._end_time)
        times_layout.addStretch()
        timed_layout.addRow("Time:", times_row)

        self._calc_dur_label = QLabel("Calculated duration: <b>1 h 00 min</b>")
        timed_layout.addRow("", self._calc_dur_label)
        form.addRow(self._timed_container)

        # Duration-only Widgets Container
        self._dur_container = QWidget()
        dur_layout = QHBoxLayout(self._dur_container)
        dur_layout.setContentsMargins(0, 0, 0, 0)

        self._hours_spin = QSpinBox()
        self._hours_spin.setRange(0, 24)
        self._hours_spin.setSuffix(" h")
        self._hours_spin.setValue(1)

        self._mins_spin = QSpinBox()
        self._mins_spin.setRange(0, 59)
        self._mins_spin.setSuffix(" min")
        self._mins_spin.setSingleStep(5)
        self._mins_spin.setValue(0)

        dur_layout.addWidget(self._hours_spin)
        dur_layout.addWidget(self._mins_spin)
        dur_layout.addStretch()

        self._dur_container.hide()
        form.addRow("Duration:", self._dur_container)

        # Notes
        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setMaximumHeight(80)
        self._notes_edit.setPlaceholderText("Optional notes on what was studied…")
        form.addRow("Notes:", self._notes_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_calculated_duration()

    def _on_mode_toggled(self) -> None:
        is_timed = self._timed_radio.isChecked()
        self._timed_container.setVisible(is_timed)
        self._dur_container.setVisible(not is_timed)

    def _on_subject_changed(self) -> None:
        self._update_task_combo()

    def _update_task_combo(self) -> None:
        prev_data = self._task_combo.currentData()
        self._task_combo.clear()
        self._task_combo.addItem("None (general study)", None)

        subj_id = self._subject_combo.currentData()
        if subj_id:
            tasks = task_service.get_all(self._conn, subject_id=subj_id, include_archived=False)
            for t in tasks:
                self._task_combo.addItem(t.title, t.id)

        target = self._default_task_id or prev_data
        if target:
            idx = self._task_combo.findData(target)
            if idx >= 0:
                self._task_combo.setCurrentIndex(idx)

    def _update_calculated_duration(self) -> None:
        st = self._start_time.time()
        et = self._end_time.time()
        st_secs = st.hour() * 3600 + st.minute() * 60
        et_secs = et.hour() * 3600 + et.minute() * 60

        diff = et_secs - st_secs
        if diff <= 0:
            # Crosses midnight into next day
            diff += 86400
        self._calc_dur_label.setText(f"Calculated duration: <b>{format_duration(diff)}</b>")

    def _populate(self, sess: Session) -> None:
        # Subject
        idx = self._subject_combo.findData(sess.subject_id)
        if idx >= 0:
            self._subject_combo.setCurrentIndex(idx)

        # Task
        if sess.task_id:
            idx = self._task_combo.findData(sess.task_id)
            if idx >= 0:
                self._task_combo.setCurrentIndex(idx)

        # Date
        self._date_edit.setDate(QDate.fromString(sess.local_date, "yyyy-MM-dd"))

        # Mode & times
        if sess.start_utc and sess.end_utc:
            self._timed_radio.setChecked(True)
            offset = timedelta(minutes=sess.utc_offset_mins)
            s_dt = datetime.strptime(sess.start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + offset
            e_dt = datetime.strptime(sess.end_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + offset
            self._start_time.setTime(QTime(s_dt.hour, s_dt.minute))
            self._end_time.setTime(QTime(e_dt.hour, e_dt.minute))
            self._update_calculated_duration()
        else:
            self._duration_radio.setChecked(True)
            h = sess.duration_secs // 3600
            m = (sess.duration_secs % 3600) // 60
            self._hours_spin.setValue(h)
            self._mins_spin.setValue(m)

        self._notes_edit.setPlainText(sess.notes)

    def _on_accept(self) -> None:
        if self._subject_combo.count() == 0:
            warn(self, "No subjects", "Please create a subject first.")
            return

        if not self._timed_radio.isChecked():
            # Duration mode
            dur = self._hours_spin.value() * 3600 + self._mins_spin.value() * 60
            if dur <= 0:
                warn(self, "Invalid duration", "Duration must be greater than zero.")
                return
            if dur > 86400:
                warn(self, "Invalid duration", "Duration cannot exceed 24 hours.")
                return

        self.accept()

    # ------------------------------------------------------------------
    @property
    def is_timed(self) -> bool:
        return self._timed_radio.isChecked()

    @property
    def subject_id(self) -> int:
        return self._subject_combo.currentData()

    @property
    def task_id(self) -> int | None:
        return self._task_combo.currentData()

    @property
    def local_date(self) -> str:
        return self._date_edit.date().toString("yyyy-MM-dd")

    @property
    def notes(self) -> str:
        return self._notes_edit.toPlainText().strip()

    @property
    def duration_secs(self) -> int:
        if not self.is_timed:
            return self._hours_spin.value() * 3600 + self._mins_spin.value() * 60
        st = self._start_time.time()
        et = self._end_time.time()
        st_secs = st.hour() * 3600 + st.minute() * 60
        et_secs = et.hour() * 3600 + et.minute() * 60
        diff = et_secs - st_secs
        if diff <= 0:
            diff += 86400
        return diff

    def get_timestamps_utc(self, utc_offset_mins: int) -> tuple[str, str]:
        """Convert local date and QTime to UTC ISO timestamps."""
        qd = self._date_edit.date()
        st = self._start_time.time()
        et = self._end_time.time()

        start_local = datetime(qd.year(), qd.month(), qd.day(), st.hour(), st.minute(), 0)
        end_local = datetime(qd.year(), qd.month(), qd.day(), et.hour(), et.minute(), 0)
        if end_local <= start_local:
            # Crossed midnight
            end_local += timedelta(days=1)

        offset = timedelta(minutes=utc_offset_mins)
        start_utc = start_local - offset
        end_utc = end_local - offset

        return (
            start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
