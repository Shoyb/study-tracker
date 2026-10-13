"""Persistence for weekday defaults and per-study-day plans."""

from __future__ import annotations

import sqlite3


def get_alert(conn: sqlite3.Connection, local_date: str, alert_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM alert_log WHERE local_date = ? AND alert_key = ?",
        (local_date, alert_key),
    ).fetchone()


def record_alert(
    conn: sqlite3.Connection, *, local_date: str, alert_key: str, fired_at_utc: str
) -> bool:
    cursor = conn.execute(
        "INSERT OR IGNORE INTO alert_log (local_date, alert_key, fired_at_utc) "
        "VALUES (?, ?, ?)",
        (local_date, alert_key, fired_at_utc),
    )
    return cursor.rowcount == 1


def get_weekday_default(conn: sqlite3.Connection, weekday: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM weekday_defaults WHERE weekday = ?", (weekday,)
    ).fetchone()


def upsert_weekday_default(
    conn: sqlite3.Connection,
    *,
    weekday: int,
    study_goal_secs: int,
    exam_goal_type: str,
    exam_goal_value: int,
) -> None:
    conn.execute(
        """INSERT INTO weekday_defaults (
            weekday, study_goal_secs, exam_goal_type, exam_goal_value
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT(weekday) DO UPDATE SET
            study_goal_secs=excluded.study_goal_secs,
            exam_goal_type=excluded.exam_goal_type,
            exam_goal_value=excluded.exam_goal_value""",
        (weekday, study_goal_secs, exam_goal_type, exam_goal_value),
    )


def get_day_plan(conn: sqlite3.Connection, local_date: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM day_plans WHERE local_date = ?", (local_date,)
    ).fetchone()


def upsert_day_plan(
    conn: sqlite3.Connection,
    *,
    local_date: str,
    study_goal_secs: int | None,
    exam_goal_type: str | None,
    exam_goal_value: int | None,
    is_rest_day: bool,
    notes: str,
    updated_at_utc: str,
) -> None:
    conn.execute(
        """INSERT INTO day_plans (
            local_date, study_goal_secs, exam_goal_type, exam_goal_value,
            is_rest_day, notes, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(local_date) DO UPDATE SET
            study_goal_secs=excluded.study_goal_secs,
            exam_goal_type=excluded.exam_goal_type,
            exam_goal_value=excluded.exam_goal_value,
            is_rest_day=excluded.is_rest_day,
            notes=excluded.notes,
            updated_at_utc=excluded.updated_at_utc""",
        (
            local_date,
            study_goal_secs,
            exam_goal_type,
            exam_goal_value,
            int(is_rest_day),
            notes,
            updated_at_utc,
        ),
    )
