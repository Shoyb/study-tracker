"""Tests for recurring per-subject daily study targets."""

from __future__ import annotations

import pathlib

import pytest

from study_tracker.core.errors import NotFoundError, ValidationError
from study_tracker.db import settings_repo
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services import (
    session_service,
    stats_service,
    subject_daily_goal_service,
    subject_service,
)


@pytest.fixture()
def conn(tmp_path: pathlib.Path):
    db_path = tmp_path / "subject-goals.db"
    connection = get_connection(db_path)
    run_migrations(connection, db_path)
    yield connection
    connection.close()


def test_subject_daily_goal_is_saved_and_zero_clears_it(conn):
    subject = subject_service.create(
        conn, name="Art", colour="#1976D2", created_at="2026-10-13T00:00:00Z"
    )
    subject_daily_goal_service.set_daily_goal_seconds(conn, subject.id, 5400)
    assert subject_daily_goal_service.get_daily_goal_seconds(conn, subject.id) == 5400
    assert subject_daily_goal_service.get_all_daily_goals_seconds(conn) == {subject.id: 5400}

    subject_daily_goal_service.set_daily_goal_seconds(conn, subject.id, 0)
    assert subject_daily_goal_service.get_daily_goal_seconds(conn, subject.id) == 0


@pytest.mark.parametrize("seconds", [-1, 86401, True])
def test_invalid_subject_daily_goal_is_rejected(conn, seconds):
    with pytest.raises(ValidationError, match="between 0 and 24 hours"):
        subject_daily_goal_service.set_daily_goal_seconds(conn, 1, seconds)


def test_missing_subject_goal_is_rejected(conn):
    with pytest.raises(NotFoundError, match="Subject 999 not found"):
        subject_daily_goal_service.set_daily_goal_seconds(conn, 999, 3600)


def test_deleting_subject_clears_its_daily_goal(conn):
    subject = subject_service.create(
        conn, name="Art", colour="#1976D2", created_at="2026-10-13T00:00:00Z"
    )
    subject_daily_goal_service.set_daily_goal_seconds(conn, subject.id, 3600)

    subject_service.delete(conn, subject.id, "2026-10-13T00:00:00Z")

    assert subject_daily_goal_service.get_all_daily_goals_seconds(conn) == {}


def test_subject_time_uses_the_study_day_cutoff(conn):
    settings_repo.set_value(conn, "day_cutoff_minutes", "180")
    session_service.add_manual_timed(
        conn,
        subject_id=1,
        start_utc="2026-10-13T02:30:00Z",
        end_utc="2026-10-13T03:30:00Z",
        utc_offset_mins=0,
        created_at="2026-10-13T04:00:00Z",
    )

    assert stats_service.subject_time_for_range(
        conn, start="2026-10-13", end="2026-10-13"
    ) == {1: 1800}
