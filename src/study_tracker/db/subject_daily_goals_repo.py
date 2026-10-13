"""Persistence for recurring per-subject daily study targets."""

from __future__ import annotations

import json
import sqlite3

from study_tracker.db import settings_repo


def get_all(conn: sqlite3.Connection) -> dict[int, int]:
    raw = settings_repo.get(conn, "subject_daily_goals") or "{}"
    try:
        stored = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(stored, dict):
        return {}
    goals: dict[int, int] = {}
    for subject_id, seconds in stored.items():
        try:
            parsed_id = int(subject_id)
        except (TypeError, ValueError):
            continue
        if type(seconds) is int and 0 <= seconds <= 86400:
            goals[parsed_id] = seconds
    return goals


def set_for_subject(conn: sqlite3.Connection, subject_id: int, seconds: int) -> None:
    goals = get_all(conn)
    if seconds:
        goals[subject_id] = seconds
    else:
        goals.pop(subject_id, None)
    settings_repo.set_value(
        conn,
        "subject_daily_goals",
        json.dumps({str(key): value for key, value in goals.items()}, sort_keys=True),
    )


def remove_subject(conn: sqlite3.Connection, subject_id: int) -> None:
    goals = get_all(conn)
    if subject_id in goals:
        goals.pop(subject_id)
        settings_repo.set_value(
            conn,
            "subject_daily_goals",
            json.dumps({str(key): value for key, value in goals.items()}, sort_keys=True),
        )
