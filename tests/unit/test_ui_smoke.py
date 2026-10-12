"""UI smoke tests using pytest-qt."""

from __future__ import annotations

import pathlib

import pytest

from study_tracker.core.clock import FakeClock
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.ui.main_window import MainWindow
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
    window._navigate(6)
    assert window._stack.currentIndex() == 6
    assert hasattr(window, "_subjects_page")
