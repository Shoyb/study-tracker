"""Fake-clock tests for Pomodoro focus, breaks, and persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from study_tracker.core.clock import FakeClock
from study_tracker.core.errors import ValidationError
from study_tracker.db import pomodoro_repo, sessions_repo, timer_state_repo
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services.pomodoro_service import PomodoroService
from study_tracker.services.timer_service import TimerService


@pytest.fixture()
def setup_timer(tmp_path: Path):
    db_path = tmp_path / "pomodoro.db"
    conn = get_connection(db_path)
    run_migrations(conn, db_path)
    clock = FakeClock("2026-10-13T10:00:00Z")
    timer = TimerService(conn, clock)
    service = PomodoroService(conn, timer)
    yield conn, clock, timer, service
    conn.close()


def test_full_cycle_records_focus_only_and_pauses_for_next_focus(setup_timer):
    conn, clock, timer, service = setup_timer
    preset = service.create_preset(
        name="Test",
        focus_seconds=60,
        short_break_seconds=30,
        long_break_seconds=60,
        cycles_before_long_break=2,
    )
    service.start(preset.id, subject_id=1, task_id=None, notes="practice")
    clock.advance(seconds=60)
    completed = timer.advance_pomodoro_if_due()
    assert completed is not None
    assert completed.duration_secs == 60
    assert completed.pomodoro_completed is True
    assert timer.phase == "short_break"

    clock.advance(seconds=30)
    timer.advance_pomodoro_if_due()
    assert timer.phase == "focus"
    assert timer.is_paused
    assert sessions_repo.get_all(conn)[0].duration_secs == 60

    timer.resume()
    clock.advance(seconds=60)
    timer.advance_pomodoro_if_due()
    assert timer.phase == "long_break"
    assert timer.remaining_seconds == 60
    assert len(sessions_repo.get_all(conn)) == 2


def test_partial_focus_saves_incomplete_and_break_stop_saves_no_session(setup_timer):
    conn, clock, timer, service = setup_timer
    preset = pomodoro_repo.get_presets(conn)[0]
    service.start(preset.id, subject_id=1, task_id=None, notes="")
    clock.advance(seconds=90)
    partial = timer.stop()
    assert partial is not None
    assert partial.duration_secs == 90
    assert partial.pomodoro_completed is False

    service.start(preset.id, subject_id=1, task_id=None, notes="")
    clock.advance(seconds=preset.focus_seconds)
    timer.advance_pomodoro_if_due()
    assert timer.phase == "short_break"
    timer.stop()
    assert len(sessions_repo.get_all(conn)) == 2


def test_pause_does_not_count_and_phase_survives_timer_state_reload(setup_timer):
    conn, clock, timer, service = setup_timer
    preset = service.create_preset(
        name="Reload test",
        focus_seconds=120,
        short_break_seconds=30,
        long_break_seconds=60,
        cycles_before_long_break=4,
    )
    service.start(preset.id, subject_id=1, task_id=None, notes="")
    clock.advance(seconds=20)
    timer.pause()
    clock.advance(minutes=20)
    assert timer.elapsed_seconds() == 20
    state = timer_state_repo.load(conn)
    assert state is not None and state.mode == "pomodoro" and state.phase == "focus"
    recovered = TimerService(conn, clock)
    recovered.recover_as_paused(state)
    assert recovered.mode == "pomodoro"
    assert recovered.phase == "focus"
    assert recovered.elapsed_seconds() == 20


def test_run_uses_copied_preset_after_preset_is_edited(setup_timer):
    conn, clock, timer, service = setup_timer
    preset = service.create_preset(
        name="Copied",
        focus_seconds=60,
        short_break_seconds=30,
        long_break_seconds=60,
        cycles_before_long_break=2,
    )
    service.start(preset.id, subject_id=1, task_id=None, notes="")
    service.update_preset(
        preset.id,
        name="Copied, edited",
        focus_seconds=120,
        short_break_seconds=60,
        long_break_seconds=120,
        cycles_before_long_break=3,
        auto_start_break=True,
        auto_start_focus=False,
    )

    clock.advance(seconds=60)
    timer.advance_pomodoro_if_due()
    assert timer.phase == "short_break"
    run = conn.execute(
        "SELECT * FROM pomodoro_runs WHERE id = ?", (timer._pomodoro_run_id,)
    ).fetchone()
    assert run["focus_seconds"] == 60
    assert run["short_break_seconds"] == 30


def test_break_recovery_keeps_phase_and_never_saves_break_as_study(setup_timer):
    conn, clock, timer, service = setup_timer
    preset = pomodoro_repo.get_presets(conn)[0]
    service.start(preset.id, subject_id=1, task_id=None, notes="")
    clock.advance(seconds=preset.focus_seconds)
    timer.advance_pomodoro_if_due()
    state = timer_state_repo.load(conn)
    assert state is not None and state.phase == "short_break"

    recovered = TimerService(conn, clock)
    recovered.recover_as_paused(state)
    assert recovered.mode == "pomodoro"
    assert recovered.phase == "short_break"
    assert recovered.recover_and_save(state) is None
    assert len(sessions_repo.get_all(conn)) == 1


def test_four_focus_periods_save_four_sessions_with_one_long_break(setup_timer):
    conn, clock, timer, service = setup_timer
    preset = service.create_preset(
        name="Four-cycle",
        focus_seconds=60,
        short_break_seconds=10,
        long_break_seconds=30,
        cycles_before_long_break=4,
    )
    service.start(preset.id, subject_id=1, task_id=None, notes="")
    for cycle in range(4):
        clock.advance(seconds=60)
        timer.advance_pomodoro_if_due()
        if cycle < 3:
            assert timer.phase == "short_break"
            clock.advance(seconds=10)
            timer.advance_pomodoro_if_due()
            timer.resume()

    sessions = sessions_repo.get_all(conn)
    assert len(sessions) == 4
    assert all(session.pomodoro_completed is True for session in sessions)
    assert all(session.duration_secs == 60 for session in sessions)
    assert timer.phase == "long_break"
    assert timer.remaining_seconds == 30


def test_preset_validation_rejects_invalid_focus_length(setup_timer):
    _, _, _, service = setup_timer
    with pytest.raises(ValidationError):
        service.create_preset(
            name="Bad",
            focus_seconds=10,
            short_break_seconds=5,
            long_break_seconds=10,
            cycles_before_long_break=4,
        )
