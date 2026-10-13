from __future__ import annotations

from pathlib import Path

import pytest

from study_tracker.core.clock import FakeClock
from study_tracker.db import settings_repo
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services.alert_service import AlertService


@pytest.fixture()
def alert_context(tmp_path: Path):
    db_path = tmp_path / "alerts.db"
    conn = get_connection(db_path)
    run_migrations(conn, db_path)
    clock = FakeClock("2026-10-13T23:00:00Z")
    conn.execute(
        "UPDATE weekday_defaults SET study_goal_secs = ? WHERE weekday = ?",
        (3 * 60 * 60, 1),
    )
    settings_repo.set_many(
        conn,
        {
            "baseline_alerts_enabled": "1",
            "wake_minutes": "420",
            "break_overhead_percent": "20",
            "alert_margins_minutes": "120,60,20",
        },
    )
    yield conn, clock
    conn.close()


def test_baseline_alert_reports_slack_and_only_fires_once_per_level(alert_context):
    conn, clock = alert_context
    service = AlertService(conn, clock)

    alert = service.evaluate()

    assert alert is not None
    assert alert.study_day == "2026-10-13"
    assert alert.level == "warning"
    assert alert.studied_seconds == 0
    assert alert.target_seconds == 3 * 60 * 60
    assert alert.slack_minutes == 24
    assert service.evaluate() is None


def test_disabled_baseline_alert_does_not_write_alert_log(alert_context):
    conn, clock = alert_context
    settings_repo.set_value(conn, "baseline_alerts_enabled", "0")

    assert AlertService(conn, clock).evaluate() is None
    assert conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0] == 0
