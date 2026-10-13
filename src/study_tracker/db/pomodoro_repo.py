"""Persistence for Pomodoro presets and runs."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class PomodoroPreset:
    id: int
    name: str
    focus_seconds: int
    short_break_seconds: int
    long_break_seconds: int
    cycles_before_long_break: int
    auto_start_break: bool
    auto_start_focus: bool


@dataclass(frozen=True)
class PomodoroRun:
    id: int
    uuid: str
    preset_name: str
    focus_seconds: int
    short_break_seconds: int
    long_break_seconds: int
    cycles_before_long_break: int
    started_at_utc: str
    ended_at_utc: str | None


def _row_to_preset(row: sqlite3.Row) -> PomodoroPreset:
    return PomodoroPreset(
        id=row["id"],
        name=row["name"],
        focus_seconds=row["focus_seconds"],
        short_break_seconds=row["short_break_seconds"],
        long_break_seconds=row["long_break_seconds"],
        cycles_before_long_break=row["cycles_before_long_break"],
        auto_start_break=bool(row["auto_start_break"]),
        auto_start_focus=bool(row["auto_start_focus"]),
    )


def get_preset_by_id(conn: sqlite3.Connection, preset_id: int) -> PomodoroPreset | None:
    row = conn.execute(
        "SELECT * FROM pomodoro_presets WHERE id = ? AND is_archived = 0", (preset_id,)
    ).fetchone()
    return _row_to_preset(row) if row else None


def get_presets(conn: sqlite3.Connection) -> list[PomodoroPreset]:
    rows = conn.execute(
        "SELECT * FROM pomodoro_presets WHERE is_archived = 0 ORDER BY sort_order, id"
    ).fetchall()
    return [_row_to_preset(row) for row in rows]


def create_preset(
    conn: sqlite3.Connection,
    *,
    name: str,
    focus_seconds: int,
    short_break_seconds: int,
    long_break_seconds: int,
    cycles_before_long_break: int,
    auto_start_break: bool = True,
    auto_start_focus: bool = False,
) -> PomodoroPreset:
    cursor = conn.execute(
        """INSERT INTO pomodoro_presets (
            name, focus_seconds, short_break_seconds, long_break_seconds,
            cycles_before_long_break, auto_start_break, auto_start_focus, sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1
                                         FROM pomodoro_presets))""",
        (
            name.strip(),
            focus_seconds,
            short_break_seconds,
            long_break_seconds,
            cycles_before_long_break,
            int(auto_start_break),
            int(auto_start_focus),
        ),
    )
    preset = get_preset_by_id(conn, cursor.lastrowid)
    assert preset is not None
    return preset


def update_preset(
    conn: sqlite3.Connection,
    preset_id: int,
    *,
    name: str,
    focus_seconds: int,
    short_break_seconds: int,
    long_break_seconds: int,
    cycles_before_long_break: int,
    auto_start_break: bool,
    auto_start_focus: bool,
) -> None:
    conn.execute(
        """UPDATE pomodoro_presets SET name=?, focus_seconds=?, short_break_seconds=?,
           long_break_seconds=?, cycles_before_long_break=?, auto_start_break=?,
           auto_start_focus=? WHERE id=?""",
        (
            name.strip(),
            focus_seconds,
            short_break_seconds,
            long_break_seconds,
            cycles_before_long_break,
            int(auto_start_break),
            int(auto_start_focus),
            preset_id,
        ),
    )


def create_run(conn: sqlite3.Connection, preset: PomodoroPreset, started_at_utc: str) -> int:
    cursor = conn.execute(
        """INSERT INTO pomodoro_runs (
            uuid, preset_name, focus_seconds, short_break_seconds, long_break_seconds,
            cycles_before_long_break, started_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()),
            preset.name,
            preset.focus_seconds,
            preset.short_break_seconds,
            preset.long_break_seconds,
            preset.cycles_before_long_break,
            started_at_utc,
        ),
    )
    return cursor.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, ended_at_utc: str) -> None:
    conn.execute(
        "UPDATE pomodoro_runs SET ended_at_utc = ? WHERE id = ?",
        (ended_at_utc, run_id),
    )
