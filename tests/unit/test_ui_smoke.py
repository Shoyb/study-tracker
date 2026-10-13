"""UI smoke tests using pytest-qt."""

from __future__ import annotations

import pathlib

import pytest
from PySide6.QtCore import QDate, Qt, QTime

from study_tracker.core.clock import FakeClock
from study_tracker.core.formatting import format_duration
from study_tracker.db import pomodoro_repo, sessions_repo
from study_tracker.db.connection import get_connection
from study_tracker.db.exams_repo import ExamPart
from study_tracker.db.migrate import run_migrations
from study_tracker.services import (
    day_plan_service,
    exam_service,
    session_service,
    subject_daily_goal_service,
    subject_service,
    task_service,
)
from study_tracker.services.timer_service import TimerService
from study_tracker.ui.dialogs.day_plan_dialog import DayPlanDialog
from study_tracker.ui.dialogs.exam_dialog import ExamPartDialog
from study_tracker.ui.dialogs.session_dialog import SessionDialog
from study_tracker.ui.dialogs.split_session_dialog import SplitSessionDialog
from study_tracker.ui.dialogs.subject_dialog import SubjectDialog
from study_tracker.ui.main_window import MainWindow
from study_tracker.ui.pages.analytics_page import AnalyticsPage
from study_tracker.ui.pages.calendar_page import CalendarPage
from study_tracker.ui.pages.history_page import HistoryPage
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

    window._navigate(2)
    window._records_page._tabs.setCurrentWidget(window._subjects_page)
    assert window._stack.currentIndex() == 2
    assert hasattr(window, "_subjects_page")


def test_page_scrolling_and_dashboard_reflow(qtbot, db_conn):
    window = MainWindow(AppSignals(), conn=db_conn, clock=FakeClock())
    window.resize(900, 600)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(50)

    dashboard = window._dashboard_page
    assert dashboard._scroll_area.widgetResizable()
    assert dashboard._tile_columns == 2
    window.resize(1400, 800)
    qtbot.wait(50)
    assert dashboard._tile_columns == 4

    window._navigate(4)
    qtbot.wait(50)
    assert window._settings_page._scroll_area.verticalScrollBar().maximum() > 0

    window._navigate(2)
    window._records_page._tabs.setCurrentWidget(window._calendar_page)
    qtbot.wait(50)
    calendar_page = window._calendar_page
    assert calendar_page._grid.height() == 330
    assert calendar_page._grid.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert calendar_page._details_scroll.verticalScrollBar().maximum() > 0

    window.resize(900, 600)
    window._navigate(1)
    qtbot.wait(50)
    assert window._timer_page._scroll_area.verticalScrollBar().maximum() > 0


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

    # Open task records from the Records workspace.
    window._navigate(2)
    assert window._stack.currentIndex() == 2
    window._records_page._tabs.setCurrentWidget(window._tasks_page)
    assert hasattr(window, "_tasks_page")

    # Smoke test: quick add a task
    tasks_page = window._tasks_page
    tasks_page._quick_title.setText("Smoke task")
    tasks_page._on_quick_add()
    assert tasks_page._table.rowCount() == 1
    assert not hasattr(window, "_undo_action")
    assert not hasattr(window, "_redo_action")


def test_main_window_navigates_to_history(qtbot, db_conn):
    clock = FakeClock()
    signals = AppSignals()
    window = MainWindow(signals, conn=db_conn, clock=clock)
    qtbot.addWidget(window)
    window.show()

    window._navigate(2)
    window._records_page._tabs.setCurrentWidget(window._history_page)
    assert window._stack.currentIndex() == 2
    assert hasattr(window, "_history_page")


def test_main_window_opens_calendar_planner(qtbot, db_conn):
    window = MainWindow(AppSignals(), conn=db_conn, clock=FakeClock())
    qtbot.addWidget(window)
    window._navigate(2)
    window._records_page._tabs.setCurrentWidget(window._calendar_page)
    assert window._stack.currentIndex() == 2
    assert hasattr(window, "_calendar_page")


def test_main_window_opens_exams_page(qtbot, db_conn):
    window = MainWindow(AppSignals(), conn=db_conn, clock=FakeClock())
    qtbot.addWidget(window)
    window._navigate(2)
    window._records_page._tabs.setCurrentWidget(window._exams_page)
    assert window._stack.currentIndex() == 2
    assert hasattr(window, "_exams_page")


def test_records_workspace_lists_editable_daily_plans(qtbot, db_conn):
    clock = FakeClock("2026-10-13T12:00:00Z")
    day_plan_service.save_day_plan(
        db_conn,
        "2026-10-13",
        study_goal_secs=3600,
        exam_goal_type="count",
        exam_goal_value=1,
        is_rest_day=False,
        now_utc=clock.now_utc(),
    )
    window = MainWindow(AppSignals(), conn=db_conn, clock=clock)
    qtbot.addWidget(window)

    tabs = window._records_page._tabs
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "Sessions", "Tasks", "Subjects", "Exams", "Calendar", "Daily plans"
    ]
    plans_page = window._records_page._day_plans_page
    assert plans_page._table.rowCount() == 1
    plans_page._table.selectRow(0)
    assert plans_page._edit_button.isEnabled()


def test_subject_target_settings_and_dashboard_progress(qtbot, db_conn):
    clock = FakeClock("2026-10-13T12:00:00Z")
    physics = next(
        subject for subject in subject_service.get_active(db_conn) if subject.name == "Physics"
    )
    session_service.add_manual_duration(
        db_conn,
        subject_id=physics.id,
        local_date=clock.local_date(),
        duration_secs=1800,
        created_at=clock.now_utc(),
    )
    window = MainWindow(AppSignals(), conn=db_conn, clock=clock)
    qtbot.addWidget(window)

    window._navigate(4)
    settings = window._settings_page
    settings._subject_goal_subject.setCurrentIndex(
        settings._subject_goal_subject.findData(physics.id)
    )
    settings._subject_goal_minutes.setValue(60)
    settings._save_subject_daily_goal()
    assert subject_daily_goal_service.get_daily_goal_seconds(db_conn, physics.id) == 3600

    window._dashboard_page.refresh()
    assert (
        f"Physics: 30 min of {format_duration(3600)}"
        in window._dashboard_page._subject_goals.text()
    )


def test_settings_saves_optional_daily_baselines(qtbot, db_conn):
    window = MainWindow(AppSignals(), conn=db_conn, clock=FakeClock())
    qtbot.addWidget(window)
    window._navigate(4)
    settings = window._settings_page
    weekday = 1
    settings._goal_weekday.setCurrentIndex(settings._goal_weekday.findData(weekday))
    settings._goal_hours.setValue(6.5)
    settings._goal_exam_count.setValue(3)
    settings._save_weekday_goal()

    row = db_conn.execute(
        "SELECT study_goal_secs, exam_goal_type, exam_goal_value "
        "FROM weekday_defaults WHERE weekday = ?",
        (weekday,),
    ).fetchone()
    assert row["study_goal_secs"] == 6.5 * 3600
    assert row["exam_goal_type"] == "count"
    assert row["exam_goal_value"] == 3

    settings._goal_hours.setValue(0)
    settings._goal_exam_count.setValue(0)
    settings._save_weekday_goal()
    row = db_conn.execute(
        "SELECT study_goal_secs, exam_goal_type, exam_goal_value "
        "FROM weekday_defaults WHERE weekday = ?",
        (weekday,),
    ).fetchone()
    assert row["study_goal_secs"] == 0
    assert row["exam_goal_type"] == "none"
    assert row["exam_goal_value"] == 0


def test_repeated_tray_visibility_requests_only_show_icon_once(qtbot, db_conn):
    class FakeTrayIcon:
        def __init__(self):
            self.visible = False
            self.show_count = 0

        def isVisible(self):
            return self.visible

        def show(self):
            self.visible = True
            self.show_count += 1

    window = MainWindow(AppSignals(), conn=db_conn, clock=FakeClock())
    qtbot.addWidget(window)
    tray = FakeTrayIcon()
    window._tray_icon = tray

    window._ensure_tray_icon_visible()
    window._ensure_tray_icon_visible()
    window._ensure_tray_icon_visible()

    assert tray.show_count == 1


def test_no_subject_is_available_for_timer_and_manual_sessions(qtbot, db_conn):
    clock = FakeClock("2026-10-13T12:00:00Z")
    window = MainWindow(AppSignals(), conn=db_conn, clock=clock)
    qtbot.addWidget(window)
    subject = next(
        subject for subject in subject_service.get_active(db_conn)
        if subject.name == "No subject"
    )

    assert window._timer_page._subject_combo.findData(subject.id) >= 0
    dialog = SessionDialog(db_conn, clock)
    qtbot.addWidget(dialog)
    assert dialog._subject_combo.findData(subject.id) >= 0


def test_no_subject_category_name_is_read_only(qtbot, db_conn):
    subject = next(
        subject for subject in subject_service.get_active(db_conn)
        if subject.name == "No subject"
    )
    dialog = SubjectDialog(db_conn, subject=subject)
    qtbot.addWidget(dialog)

    assert dialog._name_edit.isReadOnly()


def test_split_dialog_supports_exact_time_weights_and_unassigned_remainder(qtbot, db_conn):
    no_subject = next(
        subject for subject in subject_service.get_active(db_conn)
        if subject.name == "No subject"
    )
    physics = next(
        subject for subject in subject_service.get_active(db_conn) if subject.name == "Physics"
    )
    mathematics = next(
        subject for subject in subject_service.get_active(db_conn)
        if subject.name == "Mathematics"
    )
    session = session_service.add_manual_duration(
        db_conn,
        subject_id=no_subject.id,
        local_date="2026-10-13",
        duration_secs=3600,
        created_at="2026-10-13T12:00:00Z",
    )
    dialog = SplitSessionDialog(db_conn, session)
    qtbot.addWidget(dialog)
    for row, subject_id in ((0, physics.id), (1, mathematics.id)):
        combo = dialog._table.cellWidget(row, 0)
        combo.setCurrentIndex(combo.findData(subject_id))

    dialog._table.cellWidget(0, 2).setValue(30)
    dialog._table.cellWidget(1, 2).setValue(15)
    dialog._keep_remainder.setChecked(True)
    dialog._remainder_minutes.setValue(15)
    assert dialog.allocations == {physics.id: 1800, mathematics.id: 900}
    assert dialog.keep_unassigned_seconds == 900

    dialog._mode.setCurrentIndex(dialog._mode.findData("weight"))
    dialog._table.cellWidget(0, 3).setValue(1)
    dialog._table.cellWidget(1, 3).setValue(2)
    dialog._remainder_minutes.setValue(30)
    assert dialog.allocations == {physics.id: 600, mathematics.id: 1200}
    assert dialog.keep_unassigned_seconds == 1800
    dialog._accept()
    assert dialog.result() == dialog.DialogCode.Accepted


def test_history_enables_split_for_no_subject_session(qtbot, db_conn):
    clock = FakeClock("2026-10-13T12:00:00Z")
    no_subject = next(
        subject for subject in subject_service.get_active(db_conn)
        if subject.name == "No subject"
    )
    session_service.add_manual_duration(
        db_conn,
        subject_id=no_subject.id,
        local_date=clock.local_date(),
        duration_secs=1800,
        created_at=clock.now_utc(),
    )
    page = HistoryPage(db_conn, AppSignals(), clock)
    qtbot.addWidget(page)

    page._table.selectRow(0)

    assert page._split_btn.isEnabled()


def test_day_plan_dialog_saves_goals_and_rest_day(qtbot, db_conn):
    clock = FakeClock("2026-10-13T12:00:00Z")
    dialog = DayPlanDialog(db_conn, "2026-10-13", clock)
    qtbot.addWidget(dialog)
    dialog._study_minutes.setValue(240)
    dialog._goal_type.setCurrentIndex(dialog._goal_type.findData("questions"))
    dialog._goal_value.setValue(60)
    dialog._save()

    assert dialog.result() == dialog.DialogCode.Accepted
    assert day_plan_service.get_study_goal_seconds(db_conn, "2026-10-13") == 14400
    assert day_plan_service.get_exam_goal(db_conn, "2026-10-13").value == 60

    rest_dialog = DayPlanDialog(db_conn, "2026-10-13", clock)
    qtbot.addWidget(rest_dialog)
    rest_dialog._rest_day.setChecked(True)
    rest_dialog._save()
    assert day_plan_service.is_rest_day(db_conn, "2026-10-13")
    assert day_plan_service.get_study_goal_seconds(db_conn, "2026-10-13") == 0
    assert day_plan_service.get_exam_goal(db_conn, "2026-10-13").goal_type == "none"


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


def test_timer_page_countdown_auto_saves_session(qtbot, db_conn):
    clock = FakeClock("2026-10-13T10:00:00Z")
    window = MainWindow(AppSignals(), conn=db_conn, clock=clock)
    qtbot.addWidget(window)
    page = window._timer_page
    page._mode_combo.setCurrentIndex(page._mode_combo.findData("countdown"))
    page._countdown_minutes.setValue(1)

    page._on_start()
    assert window._timer_svc.mode == "countdown"
    assert window._timer_svc.remaining_seconds == 60

    clock.advance(seconds=60)
    page._on_tick()

    sessions = sessions_repo.get_all(db_conn)
    assert len(sessions) == 1
    assert sessions[0].duration_secs == 60
    assert not window._timer_svc.is_active
    assert page._status_label.text() == "Countdown complete. Session saved."


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
