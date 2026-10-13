"""Repository for the ``settings`` table."""

from __future__ import annotations

import sqlite3

_DEFAULTS: dict[str, str] = {
    "week_start": "saturday",
    "theme": "dark",
    "streak_threshold_hrs": "6",
    "min_session_secs": "60",
    "chart_range_days": "30",
    "auto_backup": "1",
    "backup_copies": "10",
    "day_cutoff_minutes": "180",
    "wake_minutes": "420",
    "break_overhead_percent": "20",
    "alert_margins_minutes": "120,60,20",
    "baseline_alerts_enabled": "1",
    "alert_sound": "0",
    "tray_minimize": "1",
    "undo_keep_entries": "500",
    "undo_keep_days": "30",
    "pomodoro_sound": "0",
    "subject_daily_goals": "{}",
}


def get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else _DEFAULTS.get(key)


def get_all(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    result = dict(_DEFAULTS)
    for row in rows:
        result[row["key"]] = row["value"]
    return result


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def set_many(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    for key, value in values.items():
        set_value(conn, key, value)
