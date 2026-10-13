"""UI smoke tests using pytest-qt."""

from __future__ import annotations

import pathlib

import pytest
from PySide6.QtCore import QDate, QTime

from study_tracker.core.clock import FakeClock
from study_tracker.db import pomodoro_repo, sessions_repo
from study_tracker.db.connection import get_connection
from study_tracker.db.exams_repo import ExamPart
from study_tracker.db.migrate import run_migrations
from study_tracker.services import exam_service, session_service, task_service
from study_tracker.services.timer_service import TimerService
from study_tracker.ui.dialogs.exam_dialog import ExamPartDialog
from study_tracker.ui.dialogs.session_dialog import SessionDialog
from study_tracker.ui.main_window import MainWindow
from study_tracker.ui.pages.analytics_page import AnalyticsPage
from study_tracker.ui.pages.calendar_page import CalendarPage
from study_tracker.ui.pages.timer_page import TimerPage
from study_tracker.ui.signals import AppSignals


@pytest.fixture()
def db_conn(tmp_path: pathlib.Path):
    db = tmp_path / "smoke.db"
    conn = get_connection(db)
    run_migrations(conn, db)
    yield conn
    conn.close()


def test_main_window_navigates_to_subjects(qtbot, db_conn):
    clock = FakeClock()
    signals = AppSignals()
    window = MainWindow(signals, conn=db_conn, clock=clock)
    qtbot.addWidget(window)
    window.show()

    # Navigate to subjects page (index 6)
    window._navigate(7)
    assert window._stack.currentIndex() == 7
    assert hasattr(window, "_subjects_page")


def test_session_dialog_resolves_early_time_to_next_calendar_day(qtbot, db_conn):
    dialog = SessionDialog(db_conn, FakeClock("2026-10-13T12:00:00Z"))
    qtbot.addWidget(dialog)
    dialog._date_edit.setDate(QDate(2026, 10, 13))
    dialog._start_time.setTime(QTime(1, 0))
    dialog._end_time.setTime(QTime(2, 0))

    assert dialog.get_timestamps_utc(0) == (
        "2026-10-14T01:00:00Z",
        "2026-10-14T02:00:00Z",
    )
    assert "14 Oct 2026, 01:00" in dialog._resolved_start_label.text()


def test_main_window_navigates_to_tasks(qtbot, db_conn):
    clock = FakeClock()
    signals = AppSignals()
    window = MainWindow(signals, conn=db_conn, clock=clock)
    qtbot.addWidget(window)
    window.show()

    # Navigate to tasks page (index 2)
    window._navigate(2)
    assert window._stack.currentIndex() == 2
    assert hasattr(window, "_tasks_page")

    # Smoke test: quick add a task
    tasks_page = window._tasks_page
    tasks_page._quick_title.setText("Smoke task")
    tasks_page._on_quick_add()
    assert tasks_page._table.rowCount() == 1
    assert window._undo_action.isEnabled()
    window._undo()
    assert tasks_page._table.rowCount() == 0
    assert window._redo_action.isEnabled()
    window._redo()
    assert tasks_page._table.rowCount() == 1


def test_main_window_navigates_to_history(qtbot, db_conn):
    clock = FakeClock()
    signals = AppSignals()
    window = MainWindow(signals, conn=db_conn, clock=clock)
    qtbot.addWidget(window)
    window.show()

    # Navigate to history page (index 3)
    window._navigate(4)
    assert window._stack.currentIndex() == 4
    assert hasattr(window, "_history_page")


def test_main_window_opens_calendar_planner(qtbot, db_conn):
    window = MainWindow(AppSignals(), conn=db_conn, clock=FakeClock())
    qtbot.addWidget(window)
    window._navigate(5)
    assert window._stack.currentIndex() == 5
    assert hasattr(window, "_calendar_page")


def test_main_window_opens_exams_page(qtbot, db_conn):
    window = MainWindow(AppSignals(), conn=db_conn, clock=FakeClock())
    qtbot.addWidget(window)
    window._navigate(3)
    assert window._stack.currentIndex() == 3
    assert hasattr(window, "_exams_page")


def test_exam_part_autofills_skipped_count_from_total_and_attempts(qtbot, db_conn):
    dialog = ExamPartDialog(db_conn, kind="mcq")
    qtbot.addWidget(dialog)
    dialog._total.setValue(20)
    dialog._correct.setValue(12)
    dialog._incorrect.setValue(5)
    assert dialog._skipped.value() == 3


def test_analytics_exams_tab_filters_by_category_and_level(qtbot, db_conn):
    category_id = db_conn.execute(
        "SELECT id FROM exam_categories WHERE name = 'Daily'"
    ).fetchone()[0]
    level_id = db_conn.execute(
        "SELECT id FROM exam_levels WHERE name = 'Engineering'"
    ).fetchone()[0]
    exam_service.create_exam(
        db_conn,
        title="Daily physics",
        exam_date="2026-10-13",
        category_id=category_id,
        level_id=level_id,
        parts=(
            ExamPart(
                kind="mcq",
                total_questions=10,
                correct=8,
                incorrect=1,
                skipped=1,
                marks_per_correct_milli=1000,
                penalty_per_incorrect_milli=250,
                marks_per_skipped_milli=0,
            ),
        ),
        count_as_study=False,
        now_utc="2026-10-13T12:00:00Z",
    )
    page = AnalyticsPage(db_conn, AppSignals(), FakeClock("2026-10-13T12:00:00Z"))
    qtbot.addWidget(page)

    assert page._exam_statistics.rowCount() == 1
    page._exam_level.setCurrentIndex(page._exam_level.findData(level_id))
    page._exam_category.setCurrentIndex(page._exam_category.findData(category_id))
    assert page._exam_statistics.rowCount() == 1


def test_calendar_day_detail_uses_cutoff_allocated_session_time(qtbot, db_conn):
    clock = FakeClock("2026-10-13T12:00:00Z")
    session_service.add_manual_timed(
        db_conn,
        subject_id=1,
        start_utc="2026-10-13T02:30:00Z",
        end_utc="2026-10-13T03:30:00Z",
        utc_offset_mins=0,
        created_at=clock.now_utc(),
    )
    page = CalendarPage(db_conn, AppSignals(), clock)
    qtbot.addWidget(page)
    page._selected_day = "2026-10-13"
    page._refresh_sessions()

    assert page._sessions.rowCount() == 1
    assert page._sessions.item(0, 1).text() == "30 min"


def test_calendar_carryover_moves_earlier_tasks(qtbot, db_conn):
    clock = FakeClock("2026-10-14T12:00:00Z")
    task = task_service.quick_add(
        db_conn, subject_id=1, title="Earlier task", created_at=clock.now_utc()
    )
    task_service.schedule(db_conn, task.id, "2026-10-13", clock.now_utc())
    page = CalendarPage(db_conn, AppSignals(), clock)
    qtbot.addWidget(page)
    page._selected_day = "2026-10-14"
    page._refresh_sessions()

    assert page._carryover_label.text().startswith("1 task")
    page._move_carryover_tasks()
    assert task_service.get_by_id(db_conn, task.id).scheduled_date == "2026-10-14"


def test_calendar_layer_choice_is_persisted(qtbot, db_conn):
    page = CalendarPage(db_conn, AppSignals(), FakeClock())
    qtbot.addWidget(page)
    page._layer_items.setChecked(False)
    value = db_conn.execute(
        "SELECT value FROM settings WHERE key = 'calendar_layers'"
    ).fetchone()[0]
    assert "items" not in value.split(",")


def test_timer_page_pomodoro_mode_saves_focus_and_skips_break(qtbot, db_conn):
    preset = pomodoro_repo.create_preset(
        db_conn,
        name="UI test",
        focus_seconds=60,
        short_break_seconds=30,
        long_break_seconds=60,
        cycles_before_long_break=2,
    )
    clock = FakeClock("2026-10-13T10:00:00Z")
    timer = TimerService(db_conn, clock)
    page = TimerPage(db_conn, timer, AppSignals(), clock)
    qtbot.addWidget(page)
    page._mode_combo.setCurrentIndex(page._mode_combo.findData("pomodoro"))
    page._preset_combo.setCurrentIndex(page._preset_combo.findData(preset.id))
    page._on_start()
    assert timer.mode == "pomodoro"

    clock.advance(seconds=60)
    page._on_tick()
    assert timer.phase == "short_break"
    assert len(sessions_repo.get_all(db_conn)) == 1
    assert sessions_repo.get_all(db_conn)[0].duration_secs == 60

    page._skip_break()
    assert timer.phase == "focus"
    assert timer.is_running
    timer.discard()


def test_main_window_navigates_to_timer_and_timer_bar(qtbot, db_conn):
    clock = FakeClock()
    signals = AppSignals()
    window = MainWindow(signals, conn=db_conn, clock=clock)
    qtbot.addWidget(window)
    window.show()

    # Navigate to timer page (index 1)
    window._navigate(1)
    assert window._stack.currentIndex() == 1
    assert hasattr(window, "_timer_page")

    # Start timer from UI
    window._timer_page._on_start()
    assert window._timer_svc.is_active

    # TimerBar should be hidden on Timer page
    assert not window._timer_bar.isVisible()

    # Navigate to Tasks page (index 2) -> TimerBar must become visible
    window._navigate(2)
    assert window._stack.currentIndex() == 2
    assert window._timer_bar.isVisible()

    # Stop timer via TimerBar
    window._timer_bar._on_pause_resume_clicked()
    assert window._timer_svc.is_paused
    window._timer_svc.discard()
    signals.timer_state_changed.emit()
    assert not window._timer_bar.isVisible()
