"""Repository for ``timer_state`` – persists the running timer for crash recovery."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class TimerState:
    subject_id: int
    task_id: int | None
    start_utc: str
    last_heartbeat: str
    paused_secs: int
    is_paused: bool
    pause_start: str | None
    notes: str
    mode: str = "stopwatch"
    phase: str | None = None
    phase_target_seconds: int | None = None
    completed_focus_count: int = 0
    pomodoro_run_id: int | None = None
    preset_focus_seconds: int | None = None
    preset_short_break_seconds: int | None = None
    preset_long_break_seconds: int | None = None
    preset_cycles_before_long_break: int | None = None
    auto_start_break: bool = True
    auto_start_focus: bool = False


def _row_to_state(row: sqlite3.Row) -> TimerState:
    return TimerState(
        subject_id=row["subject_id"],
        task_id=row["task_id"],
        start_utc=row["start_utc"],
        last_heartbeat=row["last_heartbeat"],
        paused_secs=row["paused_secs"],
        is_paused=bool(row["is_paused"]),
        pause_start=row["pause_start"],
        notes=row["notes"],
        mode=row["mode"],
        phase=row["phase"],
        phase_target_seconds=row["phase_target_seconds"],
        completed_focus_count=row["completed_focus_count"],
        pomodoro_run_id=row["pomodoro_run_id"],
        preset_focus_seconds=row["preset_focus_seconds"],
        preset_short_break_seconds=row["preset_short_break_seconds"],
        preset_long_break_seconds=row["preset_long_break_seconds"],
        preset_cycles_before_long_break=row["preset_cycles_before_long_break"],
        auto_start_break=bool(row["auto_start_break"]),
        auto_start_focus=bool(row["auto_start_focus"]),
    )


def load(conn: sqlite3.Connection) -> TimerState | None:
    row = conn.execute("SELECT * FROM timer_state WHERE id = 1").fetchone()
    return _row_to_state(row) if row else None


def save(conn: sqlite3.Connection, state: TimerState) -> None:
    conn.execute(
        """INSERT INTO timer_state
           (id, subject_id, task_id, start_utc, last_heartbeat,
            paused_secs, is_paused, pause_start, notes, mode, phase,
            phase_target_seconds, completed_focus_count, pomodoro_run_id,
            preset_focus_seconds, preset_short_break_seconds, preset_long_break_seconds,
            preset_cycles_before_long_break, auto_start_break, auto_start_focus)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               subject_id=excluded.subject_id,
               task_id=excluded.task_id,
               start_utc=excluded.start_utc,
               last_heartbeat=excluded.last_heartbeat,
               paused_secs=excluded.paused_secs,
               is_paused=excluded.is_paused,
               pause_start=excluded.pause_start,
               notes=excluded.notes,
               mode=excluded.mode,
               phase=excluded.phase,
               phase_target_seconds=excluded.phase_target_seconds,
               completed_focus_count=excluded.completed_focus_count,
               pomodoro_run_id=excluded.pomodoro_run_id,
               preset_focus_seconds=excluded.preset_focus_seconds,
               preset_short_break_seconds=excluded.preset_short_break_seconds,
               preset_long_break_seconds=excluded.preset_long_break_seconds,
               preset_cycles_before_long_break=excluded.preset_cycles_before_long_break,
               auto_start_break=excluded.auto_start_break,
               auto_start_focus=excluded.auto_start_focus""",
        (state.subject_id, state.task_id, state.start_utc, state.last_heartbeat,
           state.paused_secs, int(state.is_paused), state.pause_start, state.notes,
           state.mode, state.phase, state.phase_target_seconds,
           state.completed_focus_count, state.pomodoro_run_id, state.preset_focus_seconds,
           state.preset_short_break_seconds, state.preset_long_break_seconds,
           state.preset_cycles_before_long_break, int(state.auto_start_break),
           int(state.auto_start_focus)),
    )


def clear(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM timer_state WHERE id = 1")
