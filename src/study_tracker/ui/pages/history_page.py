"""History page – browse, filter, edit and delete sessions."""

from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
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
from study_tracker.core.formatting import format_date, format_duration, format_time
from study_tracker.db import subjects_repo
from study_tracker.db.sessions_repo import Session
from study_tracker.services import session_service, subject_service, task_service
from study_tracker.ui.dialogs.session_dialog import SessionDialog
from study_tracker.ui.dialogs.split_session_dialog import SplitSessionDialog
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.confirm import confirm, warn

log = logging.getLogger(__name__)

_TYPE_DISPLAY = {
    "timer": "Timer",
    "manual_timed": "Manual with times",
    "manual_duration": "Duration only",
    "device": "Device",
}


class HistoryPage(QWidget):
    """Session history table with filters and editing."""

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
        self._sessions: list[Session] = []

        self._build_ui()
        self._signals.sessions_changed.connect(self._refresh)
        self._signals.subjects_changed.connect(self._on_metadata_changed)
        self._signals.tasks_changed.connect(self._on_metadata_changed)
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # 1. Header & Actions
        header = QHBoxLayout()
        header.addWidget(QLabel("<h2>Study History</h2>"))
        header.addStretch()
        add_btn = QPushButton("+ Add Session")
        add_btn.clicked.connect(self._on_add)
        header.addWidget(add_btn)
        root.addLayout(header)

        # 2. Filter Bar
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        # Date range
        self._date_from_chk = QCheckBox("From:")
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        today_str = self._clock.local_date()
        qd = QDate.fromString(today_str, "yyyy-MM-dd")
        self._date_from.setDate(qd.addDays(-30))
        self._date_from.setEnabled(False)
        self._date_from_chk.toggled.connect(self._date_from.setEnabled)
        self._date_from_chk.toggled.connect(self._apply_filters)
        self._date_from.dateChanged.connect(self._apply_filters)

        self._date_to_chk = QCheckBox("To:")
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(qd)
        self._date_to.setEnabled(False)
        self._date_to_chk.toggled.connect(self._date_to.setEnabled)
        self._date_to_chk.toggled.connect(self._apply_filters)
        self._date_to.dateChanged.connect(self._apply_filters)

        # Subject filter
        self._filter_subj = QComboBox()
        self._filter_subj.currentIndexChanged.connect(self._apply_filters)

        # Task filter
        self._filter_task = QComboBox()
        self._filter_task.currentIndexChanged.connect(self._apply_filters)

        # Type filter
        self._filter_type = QComboBox()
        self._filter_type.addItem("All Types", None)
        self._filter_type.addItem("Timer", "timer")
        self._filter_type.addItem("Manual with times", "manual_timed")
        self._filter_type.addItem("Duration only", "manual_duration")
        self._filter_type.currentIndexChanged.connect(self._apply_filters)

        # Notes search
        self._search_notes = QLineEdit()
        self._search_notes.setPlaceholderText("Search notes…")
        self._search_notes.textChanged.connect(self._apply_filters)

        filter_bar.addWidget(self._date_from_chk)
        filter_bar.addWidget(self._date_from)
        filter_bar.addWidget(self._date_to_chk)
        filter_bar.addWidget(self._date_to)
        filter_bar.addWidget(self._filter_subj)
        filter_bar.addWidget(self._filter_task)
        filter_bar.addWidget(self._filter_type)
        filter_bar.addWidget(self._search_notes)
        root.addLayout(filter_bar)

        # 3. Table
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Date", "Start", "End", "Duration", "Subject", "Task", "Type", "Notes"
        ])
        self._table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        for col in range(7):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(True)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._table.itemDoubleClicked.connect(self._on_double_clicked)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._table)

        # 4. Footer
        footer = QHBoxLayout()
        self._footer_label = QLabel("Showing 0 sessions  |  Total: 0 min")
        self._footer_label.setStyleSheet("font-weight: bold; color: #1565C0;")
        footer.addWidget(self._footer_label)
        footer.addStretch()

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit)
        footer.addWidget(self._edit_btn)

        self._split_btn = QPushButton("Split unassigned")
        self._split_btn.setEnabled(False)
        self._split_btn.clicked.connect(self._on_split_unassigned)
        footer.addWidget(self._split_btn)

        self._del_btn = QPushButton("Delete")
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet("color: #D32F2F;")
        self._del_btn.clicked.connect(self._on_delete)
        footer.addWidget(self._del_btn)
        root.addLayout(footer)

    def show_date(self, local_date: str) -> None:
        """Show one calendar day; used by chart and calendar click-through."""
        value = QDate.fromString(local_date, "yyyy-MM-dd")
        self._date_from.setDate(value)
        self._date_to.setDate(value)
        self._date_from_chk.setChecked(True)
        self._date_to_chk.setChecked(True)
        self._apply_filters()

        self._populate_filter_combos()

    def _populate_filter_combos(self) -> None:
        # Subjects
        prev_s = self._filter_subj.currentData()
        self._filter_subj.clear()
        self._filter_subj.addItem("All Subjects", None)
        all_subjects = subject_service.get_all(self._conn, include_archived=True)
        for s in all_subjects:
            self._filter_subj.addItem(s.name, s.id)
        if prev_s:
            idx = self._filter_subj.findData(prev_s)
            if idx >= 0:
                self._filter_subj.setCurrentIndex(idx)

        # Tasks
        prev_t = self._filter_task.currentData()
        self._filter_task.clear()
        self._filter_task.addItem("All Tasks", None)
        all_tasks = task_service.get_all(self._conn, include_archived=True)
        for t in all_tasks:
            self._filter_task.addItem(t.title, t.id)
        if prev_t:
            idx = self._filter_task.findData(prev_t)
            if idx >= 0:
                self._filter_task.setCurrentIndex(idx)

    def _on_metadata_changed(self) -> None:
        self._populate_filter_combos()
        self._refresh()

    def _refresh(self) -> None:
        self._apply_filters()

    def _apply_filters(self) -> None:
        date_from = (
            self._date_from.date().toString("yyyy-MM-dd")
            if self._date_from_chk.isChecked()
            else None
        )
        date_to = (
            self._date_to.date().toString("yyyy-MM-dd")
            if self._date_to_chk.isChecked()
            else None
        )
        subject_id = self._filter_subj.currentData()
        task_id = self._filter_task.currentData()
        session_type = self._filter_type.currentData()
        notes_query = self._search_notes.text().strip() or None

        self._sessions = session_service.get_all(
            self._conn,
            date_from=date_from,
            date_to=date_to,
            subject_id=subject_id,
            task_id=task_id,
            session_type=session_type,
            notes_query=notes_query,
        )
        self._populate_table()

    def _populate_table(self) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._sessions))

        subj_map = {s.id: s for s in subject_service.get_all(self._conn, include_archived=True)}
        task_map = {t.id: t for t in task_service.get_all(self._conn, include_archived=True)}

        total_secs = 0

        for row, sess in enumerate(self._sessions):
            total_secs += sess.duration_secs

            # Date
            d_item = QTableWidgetItem(format_date(sess.local_date))
            d_item.setData(Qt.ItemDataRole.UserRole, sess.local_date)
            self._table.setItem(row, 0, d_item)

            # Start time
            st_str = format_time(sess.start_utc) if sess.start_utc else "—"
            st_item = QTableWidgetItem(st_str)
            st_item.setData(Qt.ItemDataRole.UserRole, sess.start_utc or "")
            self._table.setItem(row, 1, st_item)

            # End time
            et_str = format_time(sess.end_utc) if sess.end_utc else "—"
            et_item = QTableWidgetItem(et_str)
            et_item.setData(Qt.ItemDataRole.UserRole, sess.end_utc or "")
            self._table.setItem(row, 2, et_item)

            # Duration
            dur_item = QTableWidgetItem(format_duration(sess.duration_secs))
            dur_item.setData(Qt.ItemDataRole.UserRole, sess.duration_secs)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 3, dur_item)

            # Subject
            s_obj = subj_map.get(sess.subject_id)
            s_name = s_obj.name if s_obj else f"#{sess.subject_id}"
            self._table.setItem(row, 4, QTableWidgetItem(s_name))

            # Task
            t_obj = task_map.get(sess.task_id) if sess.task_id else None
            t_title = t_obj.title if t_obj else "—"
            self._table.setItem(row, 5, QTableWidgetItem(t_title))

            # Type
            type_str = _TYPE_DISPLAY.get(sess.session_type, sess.session_type)
            self._table.setItem(row, 6, QTableWidgetItem(type_str))

            # Notes
            self._table.setItem(row, 7, QTableWidgetItem(sess.notes))

        self._table.setSortingEnabled(True)
        count = len(self._sessions)
        plural = "s" if count != 1 else ""
        tot_str = format_duration(total_secs)
        self._footer_label.setText(
            f"Showing {count} session{plural}  |  Total: <b>{tot_str}</b>"
        )
        self._on_selection_changed()

    def _selected_sessions(self) -> list[Session]:
        selected_rows = sorted({index.row() for index in self._table.selectedIndexes()})
        result = []
        for r in selected_rows:
            if 0 <= r < len(self._sessions):
                result.append(self._sessions[r])
        return result

    def _on_selection_changed(self) -> None:
        sel = self._selected_sessions()
        self._edit_btn.setEnabled(len(sel) == 1)
        self._del_btn.setEnabled(len(sel) >= 1)
        subject = subjects_repo.get_by_id(self._conn, sel[0].subject_id) if len(sel) == 1 else None
        self._split_btn.setEnabled(bool(subject and subject.name.casefold() == "no subject"))

    def _on_double_clicked(self) -> None:
        if len(self._selected_sessions()) == 1:
            self._on_edit()

    def _on_add(self) -> None:
        dlg = SessionDialog(self._conn, self._clock, self)
        if dlg.exec() != SessionDialog.DialogCode.Accepted:
            return

        offset_mins = self._clock.local_utc_offset_minutes()
        now_utc = self._clock.now_utc()

        try:
            if dlg.is_timed:
                st_utc, et_utc = dlg.get_timestamps_utc(offset_mins)
                session_service.add_manual_timed(
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
                session_service.add_manual_duration(
                    self._conn,
                    subject_id=dlg.subject_id,
                    task_id=dlg.task_id,
                    local_date=dlg.local_date,
                    duration_secs=dlg.duration_secs,
                    notes=dlg.notes,
                    utc_offset_mins=offset_mins,
                    created_at=now_utc,
                )

            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot add session", str(exc))

    def _on_edit(self) -> None:
        sel = self._selected_sessions()
        if len(sel) != 1:
            return
        sess = sel[0]

        dlg = SessionDialog(self._conn, self._clock, self, session=sess)
        if dlg.exec() != SessionDialog.DialogCode.Accepted:
            return

        offset_mins = self._clock.local_utc_offset_minutes()

        try:
            if dlg.is_timed:
                st_utc, et_utc = dlg.get_timestamps_utc(offset_mins)
                session_service.update(
                    self._conn,
                    sess.id,
                    subject_id=dlg.subject_id,
                    task_id=dlg.task_id,
                    local_date=dlg.local_date,
                    start_utc=st_utc,
                    end_utc=et_utc,
                    duration_secs=dlg.duration_secs,
                    session_type="manual_timed",
                    notes=dlg.notes,
                    utc_offset_mins=offset_mins,
                    now_utc=self._clock.now_utc(),
                )
            else:
                session_service.update(
                    self._conn,
                    sess.id,
                    subject_id=dlg.subject_id,
                    task_id=dlg.task_id,
                    local_date=dlg.local_date,
                    start_utc=None,
                    end_utc=None,
                    duration_secs=dlg.duration_secs,
                    session_type="manual_duration",
                    notes=dlg.notes,
                    utc_offset_mins=offset_mins,
                )

            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot update session", str(exc))

    def _on_split_unassigned(self) -> None:
        selected = self._selected_sessions()
        if len(selected) != 1:
            return
        session = selected[0]
        dialog = SplitSessionDialog(self._conn, session, self)
        if dialog.exec() != SplitSessionDialog.DialogCode.Accepted:
            return
        allocations = dialog.allocations
        keep_unassigned_seconds = dialog.keep_unassigned_seconds
        if not allocations and keep_unassigned_seconds == session.duration_secs:
            return

        allow_timed_conversion = False
        if session.start_utc is not None:
            allow_timed_conversion = confirm(
                self,
                "Convert timed session",
                "Splitting this session will remove its start and end times.",
                "The resulting subject records will keep the date and durations only.",
            )
            if not allow_timed_conversion:
                return

        try:
            session_service.split_unassigned_session(
                self._conn,
                session.id,
                allocations,
                keep_unassigned_seconds=keep_unassigned_seconds,
                allow_timed_conversion=allow_timed_conversion,
                now_utc=self._clock.now_utc(),
            )
            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot split session", str(exc))

    def _on_delete(self) -> None:
        sel = self._selected_sessions()
        if not sel:
            return

        total_secs = sum(s.duration_secs for s in sel)
        msg = (
            f"Permanently delete {len(sel)} session{'s' if len(sel) > 1 else ''} "
            f"totaling {format_duration(total_secs)}?"
        )
        if not confirm(self, "Delete session(s)", msg):
            return

        try:
            session_service.delete_many(
                self._conn,
                [session.id for session in sel],
                now_utc=self._clock.now_utc(),
            )
            self._signals.sessions_changed.emit()
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot delete session", str(exc))
