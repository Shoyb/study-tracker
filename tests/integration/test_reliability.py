"""Regression tests for high-risk timer, import, and database behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from study_tracker.core.clock import FakeClock
from study_tracker.core.errors import ValidationError
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services.timer_service import TimerService


@pytest.fixture()
def conn(tmp_path: Path):
    path = tmp_path / "reliability.db"
    connection = get_connection(path)
    run_migrations(connection, path)
    yield connection
    connection.close()


def test_sleep_gap_is_not_counted_after_the_last_redraw(conn):
    clock = FakeClock("2026-10-13T10:00:00Z")
    service = TimerService(conn, clock)
    service.start(1)
    clock.advance(seconds=5)
    assert service.check_inactivity_gap() is None  # normal redraw
    clock.advance(minutes=46)
    assert service.check_inactivity_gap() == 2760
    assert service.is_paused
    assert service.elapsed_seconds() == 5


def test_timer_cannot_save_more_than_24_hours(conn):
    clock = FakeClock("2026-10-13T10:00:00Z")
    service = TimerService(conn, clock)
    service.start(1)
    clock.advance(hours=25)
    with pytest.raises(ValidationError, match="24 hours"):
        service.stop()
    assert service.is_active


def test_double_stop_creates_only_one_session(conn):
    clock = FakeClock("2026-10-13T10:00:00Z")
    service = TimerService(conn, clock)
    service.start(1)
    clock.advance(minutes=10)
    service.stop()
    with pytest.raises(ValidationError, match="No timer"):
        service.stop()
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
