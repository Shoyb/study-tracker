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
    )


def load(conn: sqlite3.Connection) -> TimerState | None:
    row = conn.execute("SELECT * FROM timer_state WHERE id = 1").fetchone()
    return _row_to_state(row) if row else None


def save(conn: sqlite3.Connection, state: TimerState) -> None:
    conn.execute(
        """INSERT INTO timer_state
           (id, subject_id, task_id, start_utc, last_heartbeat,
            paused_secs, is_paused, pause_start, notes)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               subject_id=excluded.subject_id,
               task_id=excluded.task_id,
               start_utc=excluded.start_utc,
               last_heartbeat=excluded.last_heartbeat,
               paused_secs=excluded.paused_secs,
               is_paused=excluded.is_paused,
               pause_start=excluded.pause_start,
               notes=excluded.notes""",
        (state.subject_id, state.task_id, state.start_utc, state.last_heartbeat,
         state.paused_secs, int(state.is_paused), state.pause_start, state.notes),
    )


def clear(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM timer_state WHERE id = 1")
