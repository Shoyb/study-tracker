"""Tasks page – full task management."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
from study_tracker.core.formatting import format_date, format_duration
from study_tracker.db.tasks_repo import Task
from study_tracker.domain.stats import estimated_work_remaining, is_overdue, next_up, overdue_days
from study_tracker.services import subject_service, task_service
from study_tracker.ui.dialogs.task_dialog import TaskDialog
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.confirm import confirm, warn

log = logging.getLogger(__name__)


class TasksPage(QWidget):
    """Tasks management page with Next Up panel, quick-add, filtering and table."""

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
        self._all_tasks: list[Task] = []

        self._build_ui()
        self._signals.tasks_changed.connect(self._refresh)
        self._signals.subjects_changed.connect(self._on_subjects_changed)
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # 1. Header & Next Up Summary Strip
        self._next_up_panel = QFrame()
        self._next_up_panel.setStyleSheet(
            "QFrame { background-color: #1F2A32; border: 1px solid #3A4F5F; "
            "border-radius: 10px; padding: 10px; }"
        )
        next_up_layout = QVBoxLayout(self._next_up_panel)
        next_up_layout.setContentsMargins(8, 8, 8, 8)

        self._next_up_title = QLabel("<b>Next Up</b>")
        self._next_up_title.setStyleSheet("color: #F3F8FF;")
        self._next_up_content = QLabel("Loading…")
        self._next_up_content.setWordWrap(True)
        self._next_up_content.setStyleSheet("color: #E6EDF3;")
        self._work_rem_label = QLabel()
        self._work_rem_label.setStyleSheet("color: #C7D5E3; font-size: 9pt;")

        next_up_layout.addWidget(self._next_up_title)
        next_up_layout.addWidget(self._next_up_content)
        next_up_layout.addWidget(self._work_rem_label)
        root.addWidget(self._next_up_panel)

        # 2. Quick Add Bar
        quick_add_bar = QHBoxLayout()
        quick_add_bar.setSpacing(8)

        self._quick_title = QLineEdit()
        self._quick_title.setPlaceholderText("Quick add: type a task title and press Enter…")
        self._quick_title.returnPressed.connect(self._on_quick_add)

        self._quick_subj_combo = QComboBox()

        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._on_quick_add)

        full_add_btn = QPushButton("+ Detailed Task…")
        full_add_btn.setProperty("flat", True)
        full_add_btn.clicked.connect(self._on_detailed_add)

        quick_add_bar.addWidget(self._quick_title, stretch=3)
        quick_add_bar.addWidget(self._quick_subj_combo, stretch=1)
        quick_add_bar.addWidget(add_btn)
        quick_add_bar.addWidget(full_add_btn)
        root.addLayout(quick_add_bar)

        # 3. Filter Bar
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search tasks…")
        self._search_edit.textChanged.connect(self._apply_filters)

        self._filter_subj = QComboBox()
        self._filter_subj.addItem("All Subjects", None)
        self._filter_subj.currentIndexChanged.connect(self._apply_filters)

        self._filter_status = QComboBox()
        self._filter_status.addItem("All Open", "open")
        self._filter_status.addItem("All Statuses", "all")
        self._filter_status.addItem("To do", "todo")
        self._filter_status.addItem("In progress", "in_progress")
        self._filter_status.addItem("Done", "done")
        self._filter_status.currentIndexChanged.connect(self._apply_filters)

        self._filter_priority = QComboBox()
        self._filter_priority.addItem("All Priorities", None)
        self._filter_priority.addItem("High", "high")
        self._filter_priority.addItem("Medium", "medium")
        self._filter_priority.addItem("Low", "low")
        self._filter_priority.currentIndexChanged.connect(self._apply_filters)

        self._filter_due = QComboBox()
        self._filter_due.addItem("All Due Dates", None)
        self._filter_due.addItem("Overdue", "overdue")
        self._filter_due.addItem("Due in next 7 days", "next7")
        self._filter_due.addItem("No due date", "nodue")
        self._filter_due.currentIndexChanged.connect(self._apply_filters)

        self._filter_scheduled = QComboBox()
        self._filter_scheduled.addItem("Any schedule", None)
        self._filter_scheduled.addItem("Scheduled", "scheduled")
        self._filter_scheduled.addItem("Unscheduled", "unscheduled")
        self._filter_scheduled.currentIndexChanged.connect(self._apply_filters)

        self._filter_archived = QCheckBox("Show archived")
        self._filter_archived.toggled.connect(self._apply_filters)

        filter_bar.addWidget(self._search_edit, stretch=2)
        filter_bar.addWidget(self._filter_subj, stretch=1)
        filter_bar.addWidget(self._filter_status, stretch=1)
        filter_bar.addWidget(self._filter_priority, stretch=1)
        filter_bar.addWidget(self._filter_due, stretch=1)
        filter_bar.addWidget(self._filter_scheduled, stretch=1)
        filter_bar.addWidget(self._filter_archived)
        root.addLayout(filter_bar)

        # 4. Tasks Table
        self._table = QTableWidget()
        self._table.setStyleSheet(
            "background: #1F2A32; color: #E6EDF3; border: 1px solid #3A4F5F; "
            "selection-background-color: #175987; selection-color: #FFFFFF;"
        )
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Status", "Title", "Subject", "Priority", "Due Date", "Scheduled", "Progress", "Actions"
        ])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in (0, 2, 3, 4, 5, 6, 7):
            self._table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents
            )
        self._table.setSortingEnabled(True)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._table)

        self._populate_subject_combos()

    def _populate_subject_combos(self) -> None:
        subjects = subject_service.get_active(self._conn)
        prev_quick_id = self._quick_subj_combo.currentData()
        self._quick_subj_combo.clear()
        for s in subjects:
            self._quick_subj_combo.addItem(s.name, s.id)
        if prev_quick_id:
            idx = self._quick_subj_combo.findData(prev_quick_id)
            if idx >= 0:
                self._quick_subj_combo.setCurrentIndex(idx)

        # Filter combo
        prev_filt_id = self._filter_subj.currentData()
        self._filter_subj.clear()
        self._filter_subj.addItem("All Subjects", None)
        all_subjects = subject_service.get_all(self._conn, include_archived=True)
        for s in all_subjects:
            self._filter_subj.addItem(s.name, s.id)
        if prev_filt_id:
            idx = self._filter_subj.findData(prev_filt_id)
            if idx >= 0:
                self._filter_subj.setCurrentIndex(idx)

    def _on_subjects_changed(self) -> None:
        self._populate_subject_combos()
        self._refresh()

    def _refresh(self) -> None:
        self._all_tasks = task_service.get_all(self._conn, include_archived=True)
        self._update_next_up_panel()
        self._apply_filters()

    def _update_next_up_panel(self) -> None:
        today = self._clock.local_date()
        top_tasks = next_up(self._all_tasks, today=today, limit=5)
        rem_secs, no_est = estimated_work_remaining(self._all_tasks)

        overdue_cnt = sum(1 for t in self._all_tasks if is_overdue(t, today))

        if top_tasks:
            parts = []
            for i, t in enumerate(top_tasks, 1):
                overdue_badge = (
                    f" <font color='#D32F2F'><b>[Overdue {overdue_days(t, today)}d]</b></font>"
                    if is_overdue(t, today)
                    else ""
                )
                parts.append(f"{i}. <b>{t.title}</b> ({t.priority}){overdue_badge}")
            self._next_up_content.setText("  •  ".join(parts))
        else:
            self._next_up_content.setText("No open tasks. You're all caught up!")

        rem_text = f"Estimated work remaining: <b>{format_duration(rem_secs)}</b>"
        if no_est > 0:
            rem_text += f" (and {no_est} open task{'s have' if no_est > 1 else ' has'} no estimate)"
        if overdue_cnt > 0:
            rem_text += f"  |  <font color='#D32F2F'><b>{overdue_cnt} task(s) overdue</b></font>"
        self._work_rem_label.setText(rem_text)

    def _apply_filters(self) -> None:
        query = self._search_edit.text().strip().lower()
        sel_subj = self._filter_subj.currentData()
        status_mode = self._filter_status.currentData()
        sel_prio = self._filter_priority.currentData()
        sel_due = self._filter_due.currentData()
        scheduled_mode = self._filter_scheduled.currentData()
        show_archived = self._filter_archived.isChecked()
        today = self._clock.local_date()

        filtered: list[Task] = []
        for t in self._all_tasks:
            if not show_archived and t.archived:
                continue

            if sel_subj is not None and t.subject_id != sel_subj:
                continue

            if status_mode == "open":
                if t.status == "done":
                    continue
            elif status_mode != "all":
                if t.status != status_mode:
                    continue

            if sel_prio is not None and t.priority != sel_prio:
                continue

            if sel_due == "overdue":
                if not is_overdue(t, today):
                    continue
            elif sel_due == "next7":
                if not t.due_date:
                    continue
                next7 = (
                    datetime.strptime(today, "%Y-%m-%d") + timedelta(days=7)
                ).strftime("%Y-%m-%d")
                if not (today <= t.due_date <= next7) or t.status == "done":
                    continue
            elif sel_due == "nodue":
                if t.due_date is not None:
                    continue

            if scheduled_mode == "scheduled" and t.scheduled_date is None:
                continue
            if scheduled_mode == "unscheduled" and t.scheduled_date is not None:
                continue

            if query:
                if query not in t.title.lower() and query not in t.notes.lower():
                    continue

            filtered.append(t)

        self._populate_table(filtered)

    def _populate_table(self, tasks: list[Task]) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(tasks))
        today = self._clock.local_date()
        all_subjects_map = {
            s.id: s for s in subject_service.get_all(self._conn, include_archived=True)
        }

        for row, t in enumerate(tasks):
            # 0. Status Toggle / Complete button
            status_item = QTableWidgetItem(t.status.capitalize())
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, status_item)

            # 1. Title
            title_text = t.title
            if t.archived:
                title_text += " [archived]"
            title_item = QTableWidgetItem(title_text)
            if t.status == "done" or t.archived:
                title_item.setForeground(Qt.GlobalColor.gray)
            self._table.setItem(row, 1, title_item)

            # 2. Subject
            subj = all_subjects_map.get(t.subject_id)
            subj_name = subj.name if subj else f"Subject #{t.subject_id}"
            subj_item = QTableWidgetItem(subj_name)
            self._table.setItem(row, 2, subj_item)

            # 3. Priority
            prio_item = QTableWidgetItem(t.priority.capitalize())
            # For numeric sort
            prio_rank = {"high": 1, "medium": 2, "low": 3}.get(t.priority, 2)
            prio_item.setData(Qt.ItemDataRole.UserRole, prio_rank)
            if t.priority == "high":
                prio_item.setForeground(Qt.GlobalColor.red)
            self._table.setItem(row, 3, prio_item)

            # 4. Due Date
            if is_overdue(t, today):
                days = overdue_days(t, today)
                due_text = f"{format_date(t.due_date)} (Overdue {days}d)"
            elif t.due_date:
                due_text = format_date(t.due_date)
            else:
                due_text = "—"
            due_item = QTableWidgetItem(due_text)
            due_item.setData(Qt.ItemDataRole.UserRole, t.due_date or "9999-99-99")
            if is_overdue(t, today):
                due_item.setForeground(Qt.GlobalColor.red)
            self._table.setItem(row, 4, due_item)

            scheduled_text = format_date(t.scheduled_date) if t.scheduled_date else "—"
            scheduled_item = QTableWidgetItem(scheduled_text)
            scheduled_item.setData(Qt.ItemDataRole.UserRole, t.scheduled_date or "9999-99-99")
            self._table.setItem(row, 5, scheduled_item)

            # 6. Progress / Estimate
            spent_str = format_duration(t.time_spent_secs)
            if t.estimate_secs:
                est_str = format_duration(t.estimate_secs)
                prog_text = f"{spent_str} of {est_str}"
            else:
                prog_text = spent_str
            prog_item = QTableWidgetItem(prog_text)
            prog_item.setData(Qt.ItemDataRole.UserRole, t.time_spent_secs)
            self._table.setItem(row, 6, prog_item)

            # 7. Action buttons
            actions_widget = _TaskRowActions(t, self._conn, self._signals, self._clock, self)
            self._table.setCellWidget(row, 7, actions_widget)

        self._table.setSortingEnabled(True)

    def _on_quick_add(self) -> None:
        title = self._quick_title.text().strip()
        if not title:
            return
        subject_id = self._quick_subj_combo.currentData()
        if not subject_id:
            warn(self, "No subject", "Please create a subject first.")
            return

        try:
            task_service.quick_add(
                self._conn,
                subject_id=subject_id,
                title=title,
                created_at=self._clock.now_utc(),
            )
            self._quick_title.clear()
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot add task", str(exc))

    def _on_detailed_add(self) -> None:
        default_subj = self._quick_subj_combo.currentData()
        dlg = TaskDialog(self._conn, self._clock, self, default_subject_id=default_subj)
        if dlg.exec() != TaskDialog.DialogCode.Accepted:
            return

        try:
            task_service.create(
                self._conn,
                subject_id=dlg.subject_id,
                title=dlg.title,
                status=dlg.status,
                priority=dlg.priority,
                due_date=dlg.due_date,
                estimate_secs=dlg.estimate_secs,
                notes=dlg.notes,
                created_at=self._clock.now_utc(),
            )
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot add task", str(exc))


class _TaskRowActions(QWidget):
    """Action buttons inside a task row: Complete/Reopen, Edit, Archive, Delete."""

    def __init__(
        self,
        task: Task,
        conn: sqlite3.Connection,
        signals: AppSignals,
        clock,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._conn = conn
        self._signals = signals
        self._clock = clock

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        if task.status == "done":
            reopen_btn = QPushButton("Reopen")
            reopen_btn.setProperty("flat", True)
            reopen_btn.clicked.connect(self._on_reopen)
            layout.addWidget(reopen_btn)
        else:
            done_btn = QPushButton("Done")
            done_btn.setProperty("flat", True)
            done_btn.clicked.connect(self._on_complete)
            layout.addWidget(done_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setProperty("flat", True)
        edit_btn.clicked.connect(self._on_edit)
        layout.addWidget(edit_btn)

        schedule_btn = QPushButton("Unplan" if task.scheduled_date else "Schedule")
        schedule_btn.setProperty("flat", True)
        schedule_btn.clicked.connect(self._on_schedule)
        layout.addWidget(schedule_btn)

        if task.archived:
            unarc_btn = QPushButton("Unarchive")
            unarc_btn.setProperty("flat", True)
            unarc_btn.clicked.connect(self._on_unarchive)
            layout.addWidget(unarc_btn)
        else:
            arc_btn = QPushButton("Archive")
            arc_btn.setProperty("flat", True)
            arc_btn.clicked.connect(self._on_archive)
            layout.addWidget(arc_btn)

        del_btn = QPushButton("Del")
        del_btn.setProperty("flat", True)
        del_btn.setStyleSheet("color: #D32F2F;")
        del_btn.clicked.connect(self._on_delete)
        layout.addWidget(del_btn)

    def _on_complete(self) -> None:
        task_service.complete(self._conn, self._task.id, completed_at=self._clock.now_utc())
        self._signals.tasks_changed.emit()

    def _on_reopen(self) -> None:
        task_service.reopen(self._conn, self._task.id, self._clock.now_utc())
        self._signals.tasks_changed.emit()

    def _on_edit(self) -> None:
        dlg = TaskDialog(self._conn, self._clock, self, task=self._task)
        if dlg.exec() != TaskDialog.DialogCode.Accepted:
            return
        try:
            completed_at = self._task.completed_at
            if dlg.status == "done" and not completed_at:
                completed_at = self._clock.now_utc()
            task_service.update(
                self._conn,
                self._task.id,
                subject_id=dlg.subject_id,
                title=dlg.title,
                status=dlg.status,
                priority=dlg.priority,
                archived=self._task.archived,
                due_date=dlg.due_date,
                estimate_secs=dlg.estimate_secs,
                notes=dlg.notes,
                completed_at=completed_at,
                scheduled_date=self._task.scheduled_date,
                now_utc=self._clock.now_utc(),
            )
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot update task", str(exc))

    def _on_schedule(self) -> None:
        now_utc = self._clock.now_utc()
        if self._task.scheduled_date:
            task_service.schedule(self._conn, self._task.id, None, now_utc)
            self._signals.tasks_changed.emit()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Schedule task")
        form = QFormLayout(dialog)
        date_edit = QDateEdit(QDate.fromString(self._clock.local_date(), "yyyy-MM-dd"))
        date_edit.setCalendarPopup(True)
        form.addRow("Study day:", date_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        scheduled_date = date_edit.date().toString("yyyy-MM-dd")
        task_service.schedule(self._conn, self._task.id, scheduled_date, now_utc)
        self._signals.tasks_changed.emit()

    def _on_archive(self) -> None:
        task_service.archive(self._conn, self._task.id, self._clock.now_utc())
        self._signals.tasks_changed.emit()

    def _on_unarchive(self) -> None:
        task_service.unarchive(self._conn, self._task.id, self._clock.now_utc())
        self._signals.tasks_changed.emit()

    def _on_delete(self) -> None:
        if not confirm(self, "Delete task", f"Permanently delete \"{self._task.title}\"?"):
            return
        try:
            task_service.delete(self._conn, self._task.id, self._clock.now_utc())
            self._signals.tasks_changed.emit()
        except AppError as exc:
            warn(self, "Cannot delete task", str(exc))
