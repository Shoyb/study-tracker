"""Unit tests for TimerService with FakeClock."""

from __future__ import annotations

import pathlib

import pytest

from study_tracker.core.clock import FakeClock
from study_tracker.core.errors import ConflictError
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services.timer_service import TimerService


@pytest.fixture()
def conn(tmp_path: pathlib.Path):
    db_path = tmp_path / "test.db"
    c = get_connection(db_path)
    run_migrations(c, db_path)
    yield c
    c.close()


class TestStopwatchLogic:
    def test_run_pause_run_exact_duration(self, conn):
        clock = FakeClock("2026-10-13T10:00:00Z")
        svc = TimerService(conn, clock)

        # Start timer
        svc.start(subject_id=1)
        assert svc.is_running

        # Run 10 min (600s)
        clock.advance(minutes=10)
        assert svc.elapsed_seconds() == 600

        # Pause 5 min (300s) - should NOT count
        svc.pause()
        assert svc.is_paused
        clock.advance(minutes=5)
        assert svc.elapsed_seconds() == 600

        # Resume & run 10 min (600s)
        svc.resume()
        clock.advance(minutes=10)
        assert svc.elapsed_seconds() == 1200

        # Stop
        sess = svc.stop()
        assert sess.duration_secs == 1200
        assert not svc.is_active

    def test_starting_second_timer_raises_conflict(self, conn):
        clock = FakeClock("2026-10-13T10:00:00Z")
        svc = TimerService(conn, clock)
        svc.start(subject_id=1)

        with pytest.raises(ConflictError):
            svc.start(subject_id=2)

    def test_discard_clears_timer(self, conn):
        clock = FakeClock("2026-10-13T10:00:00Z")
        svc = TimerService(conn, clock)
        svc.start(subject_id=1)
        clock.advance(minutes=15)
        svc.discard()

        assert not svc.is_active
        assert svc.load_persisted_state() is None

    def test_inactivity_gap_auto_pauses(self, conn):
        clock = FakeClock("2026-10-13T10:00:00Z")
        svc = TimerService(conn, clock)
        svc.start(subject_id=1)

        # Advance 15 seconds without tick
        clock.advance(seconds=15)
        gap = svc.check_inactivity_gap()
        assert gap == 15
        assert svc.is_paused

    def test_backwards_clock_jump_keeps_duration(self, conn):
        clock = FakeClock("2026-10-13T10:00:00Z")
        svc = TimerService(conn, clock)
        svc.start(subject_id=1)

        clock.advance(minutes=20)
        # Wall clock jumps backward to 09:50:00Z!
        clock.set_utc("2026-10-13T09:50:00Z")

        sess = svc.stop()
        assert sess.duration_secs == 1200
        assert sess.end_utc > sess.start_utc


class TestCountdownLogic:
    def test_countdown_pauses_and_saves_when_target_expires(self, conn):
        clock = FakeClock("2026-10-13T10:00:00Z")
        service = TimerService(conn, clock)
        service.start_countdown(subject_id=1, target_seconds=120)

        clock.advance(seconds=90)
        assert service.remaining_seconds == 30
        service.pause()
        clock.advance(seconds=60)
        assert service.remaining_seconds == 30
        service.resume()
        clock.advance(seconds=30)

        session = service.advance_countdown_if_due()

        assert session is not None
        assert session.duration_secs == 120
        assert not service.is_active
        assert service.load_persisted_state() is None

    def test_countdown_mode_and_target_survive_crash_recovery(self, conn):
        clock = FakeClock("2026-10-13T10:00:00Z")
        service = TimerService(conn, clock)
        service.start_countdown(subject_id=1, target_seconds=300)
        clock.advance(seconds=60)
        service.heartbeat()

        recovered_service = TimerService(conn, clock)
        state = recovered_service.load_persisted_state()
        assert state is not None
        assert state.mode == "countdown"
        assert state.countdown_target_seconds == 300

        recovered_service.recover_as_paused(state)
        assert recovered_service.is_paused
        assert recovered_service.remaining_seconds == 240
        session = recovered_service.recover_and_save(state)

        assert session is not None
        assert session.duration_secs == 60


class TestCrashRecovery:
    def test_recovery_stops_at_last_heartbeat(self, conn):
        clock = FakeClock("2026-10-13T10:00:00Z")
        svc1 = TimerService(conn, clock)
        svc1.start(subject_id=1)

        # Run 10 minutes
        clock.advance(minutes=10)
        svc1.heartbeat()  # last heartbeat at 10:10:00Z

        # Imagine app crashes 30 minutes later!
        # When user opens app again:
        clock.advance(minutes=30)  # current time is now 10:40:00Z

        svc2 = TimerService(conn, clock)
        state = svc2.load_persisted_state()
        assert state is not None
        assert state.last_heartbeat == "2026-10-13T10:10:00Z"

        # Recover and save: must only count up to last heartbeat (10 min), NOT up to now (40 min)!
        sess = svc2.recover_and_save(state)
        assert sess.duration_secs == 600
        assert sess.end_utc == "2026-10-13T10:10:00Z"
        assert svc2.load_persisted_state() is None
