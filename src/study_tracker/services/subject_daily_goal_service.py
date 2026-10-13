"""Business rules for recurring per-subject daily study targets."""

from __future__ import annotations

import sqlite3

from study_tracker.core.errors import NotFoundError, ValidationError
from study_tracker.db import subject_daily_goals_repo, subjects_repo


def get_all_daily_goals_seconds(conn: sqlite3.Connection) -> dict[int, int]:
    return subject_daily_goals_repo.get_all(conn)


def get_daily_goal_seconds(conn: sqlite3.Connection, subject_id: int) -> int:
    return get_all_daily_goals_seconds(conn).get(subject_id, 0)


def set_daily_goal_seconds(
    conn: sqlite3.Connection, subject_id: int, seconds: int
) -> None:
    if not isinstance(seconds, int) or isinstance(seconds, bool) or not 0 <= seconds <= 86400:
        raise ValidationError("A subject daily target must be between 0 and 24 hours.")
    if subjects_repo.get_by_id(conn, subject_id) is None:
        raise NotFoundError(f"Subject {subject_id} not found.")
    subject_daily_goals_repo.set_for_subject(conn, subject_id, seconds)
