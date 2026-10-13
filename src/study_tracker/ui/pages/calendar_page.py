"""Monthly calendar of daily study totals."""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from study_tracker.core.errors import AppError
from study_tracker.core.formatting import format_duration
from study_tracker.db import calendar_repo, settings_repo
from study_tracker.domain.allocation import allocate_by_day
from study_tracker.services import calendar_service, session_service, subject_service, task_service
from study_tracker.services.stats_service import totals_for_range
from study_tracker.ui.dialogs.calendar_item_dialog import CalendarItemDialog
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.confirm import confirm, warn


class CalendarPage(QWidget):
    """A clickable month grid with a compact selected-day session list."""

    def __init__(self, conn: sqlite3.Connection, signals: AppSignals, clock, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._signals = signals
        self._clock = clock
        today = date.fromisoformat(clock.local_date())
        self._year, self._month = today.year, today.month
        self._selected_day = today.isoformat()
        self._build_ui()
        signals.sessions_changed.connect(self.refresh)
        signals.tasks_changed.connect(self.refresh)
        signals.calendar_changed.connect(self.refresh)
        signals.day_changed.connect(self._today)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        controls = QHBoxLayout()
        previous = QPushButton("‹ Previous")
        previous.clicked.connect(lambda: self._shift_month(-1))
        self._title = QLabel()
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        following = QPushButton("Next ›")
        following.clicked.connect(lambda: self._shift_month(1))
        today = QPushButton("Today")
        today.clicked.connect(self._today)
        controls.addWidget(previous)
        controls.addWidget(self._title, 1)
        controls.addWidget(today)
        controls.addWidget(following)
        root.addLayout(controls)

        layers = QHBoxLayout()
        saved_layers = set(
            (settings_repo.get(self._conn, "calendar_layers") or "study,tasks,items").split(",")
        )
        self._layer_study = QCheckBox("Study time")
        self._layer_tasks = QCheckBox("Tasks")
        self._layer_items = QCheckBox("Notes and events")
        self._layer_study.setChecked("study" in saved_layers)
        self._layer_tasks.setChecked("tasks" in saved_layers)
        self._layer_items.setChecked("items" in saved_layers)
        for checkbox in (self._layer_study, self._layer_tasks, self._layer_items):
            checkbox.toggled.connect(self._save_layers)
            layers.addWidget(checkbox)
        layers.addStretch()
        root.addLayout(layers)

        self._grid = QTableWidget(6, 7)
        self._grid.setHorizontalHeaderLabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        self._grid.verticalHeader().hide()
        self._grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._grid.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._grid.cellClicked.connect(self._select_cell)
        root.addWidget(self._grid)

        self._day_title = QLabel()
        self._day_title.setStyleSheet("font-size: 13pt; font-weight: bold; padding-top: 8px;")
        root.addWidget(self._day_title)
        carryover = QHBoxLayout()
        self._carryover_label = QLabel()
        self._carryover_label.setWordWrap(True)
        self._carryover_button = QPushButton("Move to this day")
        self._carryover_button.clicked.connect(self._move_carryover_tasks)
        carryover.addWidget(self._carryover_label, 1)
        carryover.addWidget(self._carryover_button)
        root.addLayout(carryover)
        self._sessions = QTableWidget(0, 4)
        self._sessions.setHorizontalHeaderLabels(["Time", "Duration", "Subject", "Task"])
        self._sessions.verticalHeader().hide()
        self._sessions.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._sessions)

        self._calendar_items = QListWidget()
        root.addWidget(self._calendar_items)
        actions = QHBoxLayout()
        self._add_note = QPushButton("Add note")
        self._add_event = QPushButton("Add event")
        self._edit_item = QPushButton("Edit item")
        self._delete_item = QPushButton("Delete item")
        self._schedule_task = QPushButton("Schedule task")
        self._add_note.clicked.connect(lambda: self._add_calendar_item("note"))
        self._add_event.clicked.connect(lambda: self._add_calendar_item("event"))
        self._edit_item.clicked.connect(self._edit_calendar_item)
        self._delete_item.clicked.connect(self._delete_calendar_item)
        self._schedule_task.clicked.connect(self._schedule_task_on_day)
        self._calendar_items.itemDoubleClicked.connect(lambda _: self._edit_calendar_item())
        for button in (
            self._add_note,
            self._add_event,
            self._edit_item,
            self._delete_item,
            self._schedule_task,
        ):
            actions.addWidget(button)
        root.addLayout(actions)

    def _shift_month(self, amount: int) -> None:
        self._month += amount
        if self._month == 0:
            self._year, self._month = self._year - 1, 12
        elif self._month == 13:
            self._year, self._month = self._year + 1, 1
        self._selected_day = date(self._year, self._month, 1).isoformat()
        self.refresh()

    def _today(self) -> None:
        value = date.fromisoformat(self._clock.local_date())
        self._year, self._month = value.year, value.month
        self._selected_day = value.isoformat()
        self.refresh()

    def _select_cell(self, row: int, column: int) -> None:
        item = self._grid.item(row, column)
        if item and item.data(Qt.ItemDataRole.UserRole):
            self._selected_day = item.data(Qt.ItemDataRole.UserRole)
            self._refresh_sessions()

    def _save_layers(self) -> None:
        enabled = [
            name
            for name, checkbox in (
                ("study", self._layer_study),
                ("tasks", self._layer_tasks),
                ("items", self._layer_items),
            )
            if checkbox.isChecked()
        ]
        settings_repo.set_value(self._conn, "calendar_layers", ",".join(enabled))
        self.refresh()

    def refresh(self) -> None:
        first = date(self._year, self._month, 1)
        last = date(self._year, self._month, calendar.monthrange(self._year, self._month)[1])
        totals = totals_for_range(self._conn, start=first.isoformat(), end=last.isoformat())
        items = calendar_service.get_items_for_range(
            self._conn, first.isoformat(), last.isoformat()
        )
        tasks = task_service.get_all(self._conn, include_archived=True)
        tasks_by_date: dict[str, list[str]] = {}
        if self._layer_tasks.isChecked():
            for task in tasks:
                if task.archived or task.status == "done":
                    continue
                for task_date in {task.due_date, task.scheduled_date}:
                    if task_date and first.isoformat() <= task_date <= last.isoformat():
                        tasks_by_date.setdefault(task_date, []).append(task.title)
        items_by_date: dict[str, list] = {}
        if self._layer_items.isChecked():
            for calendar_item in items:
                items_by_date.setdefault(calendar_item.local_date, []).append(calendar_item)
        self._title.setText(first.strftime("%B %Y"))
        self._grid.clearContents()
        for day in range(1, last.day + 1):
            value = date(self._year, self._month, day)
            day_text = value.isoformat()
            seconds = totals[day_text]
            chips = []
            if self._layer_study.isChecked() and seconds:
                chips.append(format_duration(seconds))
            chips.extend(f"Task: {title}" for title in tasks_by_date.get(day_text, []))
            chips.extend(
                f"{calendar_item.kind.title()}: {calendar_item.title}"
                for calendar_item in items_by_date.get(day_text, [])
            )
            content = chips[:3]
            if len(chips) > 3:
                content.append(f"+{len(chips) - 3} more")
            item = QTableWidgetItem("\n".join([str(day), *content]))
            item.setData(Qt.ItemDataRole.UserRole, day_text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            if seconds and self._layer_study.isChecked():
                item.setBackground(Qt.GlobalColor.cyan)
            self._grid.setItem((first.weekday() + day - 1) // 7, value.weekday(), item)
        self._refresh_sessions()

    def _refresh_sessions(self) -> None:
        cutoff_minutes = int(settings_repo.get(self._conn, "day_cutoff_minutes") or "180")
        previous_day = (
            date.fromisoformat(self._selected_day) - timedelta(days=1)
        ).isoformat()
        sessions = session_service.get_all(
            self._conn, date_from=previous_day, date_to=self._selected_day
        )
        allocated_sessions = [
            (session, allocate_by_day(session, cutoff_minutes).get(self._selected_day, 0))
            for session in sessions
        ]
        allocated_sessions = [item for item in allocated_sessions if item[1] > 0]
        subjects = {
            s.id: s.name for s in subject_service.get_all(self._conn, include_archived=True)
        }
        tasks = {t.id: t.title for t in task_service.get_all(self._conn, include_archived=True)}
        self._carryover_tasks = [
            task
            for task in task_service.get_all(self._conn, include_archived=False)
            if task.status != "done"
            and task.scheduled_date is not None
            and task.scheduled_date < self._selected_day
        ]
        self._carryover_label.setText(
            f"{len(self._carryover_tasks)} task(s) were scheduled earlier. Move them here?"
            if self._carryover_tasks
            else ""
        )
        self._carryover_button.setVisible(bool(self._carryover_tasks))
        total = format_duration(sum(seconds for _, seconds in allocated_sessions))
        self._day_title.setText(f"Sessions for {self._selected_day} ({total})")
        self._sessions.setRowCount(len(allocated_sessions))
        for row, (session, allocated_secs) in enumerate(allocated_sessions):
            time = session.start_utc[11:16] if session.start_utc else "Duration only"
            self._sessions.setItem(row, 0, QTableWidgetItem(time))
            self._sessions.setItem(row, 1, QTableWidgetItem(format_duration(allocated_secs)))
            subject = subjects.get(session.subject_id, "Unknown")
            self._sessions.setItem(row, 2, QTableWidgetItem(subject))
            self._sessions.setItem(row, 3, QTableWidgetItem(tasks.get(session.task_id, "—")))

        self._calendar_items.clear()
        for calendar_item in calendar_service.get_items_for_date(
            self._conn, self._selected_day, cutoff_minutes
        ):
            time_text = f"{calendar_item.start_time} " if calendar_item.start_time else ""
            row = QListWidgetItem(f"{time_text}{calendar_item.kind.title()}: {calendar_item.title}")
            row.setData(Qt.ItemDataRole.UserRole, calendar_item.id)
            self._calendar_items.addItem(row)

    def _move_carryover_tasks(self) -> None:
        task_service.schedule_many(
            self._conn,
            [task.id for task in self._carryover_tasks],
            self._selected_day,
            self._clock.now_utc(),
        )
        self._signals.tasks_changed.emit()

    def _add_calendar_item(self, kind: str) -> None:
        dialog = CalendarItemDialog(self._conn, self._selected_day, parent=self)
        dialog._kind.setCurrentIndex(dialog._kind.findData(kind))
        if dialog.exec() != CalendarItemDialog.DialogCode.Accepted:
            return
        try:
            if dialog.kind == "note":
                calendar_service.add_note(
                    self._conn,
                    title=dialog.title,
                    notes=dialog.notes,
                    local_date=dialog.local_date,
                    created_at=self._clock.now_utc(),
                )
            else:
                calendar_service.add_event(
                    self._conn,
                    title=dialog.title,
                    notes=dialog.notes,
                    local_date=dialog.local_date,
                    start_time=dialog.start_time,
                    end_time=dialog.end_time,
                    created_at=self._clock.now_utc(),
                )
            self._signals.calendar_changed.emit()
        except AppError as exc:
            warn(self, "Cannot save calendar item", str(exc))

    def _edit_calendar_item(self) -> None:
        selected = self._calendar_items.currentItem()
        if selected is None:
            return
        item_id = selected.data(Qt.ItemDataRole.UserRole)
        item = calendar_repo.get_by_id(self._conn, item_id)
        if item is None:
            return
        dialog = CalendarItemDialog(self._conn, item.local_date, item, parent=self)
        if dialog.exec() != CalendarItemDialog.DialogCode.Accepted:
            return
        try:
            calendar_service.update(
                self._conn,
                item.id,
                title=dialog.title,
                notes=dialog.notes,
                local_date=dialog.local_date,
                start_time=dialog.start_time,
                end_time=dialog.end_time,
                task_id=item.task_id,
                color_hex=item.color_hex,
                is_done=item.is_done,
                updated_at=self._clock.now_utc(),
            )
            self._signals.calendar_changed.emit()
        except AppError as exc:
            warn(self, "Cannot edit calendar item", str(exc))

    def _delete_calendar_item(self) -> None:
        selected = self._calendar_items.currentItem()
        if selected is None:
            return
        item_id = selected.data(Qt.ItemDataRole.UserRole)
        if not confirm(self, "Delete calendar item", "Delete the selected note or event?"):
            return
        try:
            calendar_service.delete(self._conn, item_id, self._clock.now_utc())
            self._signals.calendar_changed.emit()
        except AppError as exc:
            warn(self, "Cannot delete calendar item", str(exc))

    def _schedule_task_on_day(self) -> None:
        tasks = [
            task
            for task in task_service.get_all(self._conn, include_archived=False)
            if task.status != "done"
        ]
        if not tasks:
            return
        title, accepted = QInputDialog.getItem(
            self,
            "Schedule task",
            "Task:",
            [task.title for task in tasks],
            0,
            False,
        )
        if not accepted:
            return
        task = next(task for task in tasks if task.title == title)
        task_service.schedule(self._conn, task.id, self._selected_day, self._clock.now_utc())
        self._signals.tasks_changed.emit()
