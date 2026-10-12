"""Repository for the ``sessions`` table."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Session:
    id: int
    uuid: str
    subject_id: int
    task_id: int | None
    local_date: str
    start_utc: str | None
    end_utc: str | None
    duration_secs: int
    session_type: str
    notes: str
    utc_offset_mins: int
    source: str | None
    source_id: str | None
    created_at: str


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        uuid=row["uuid"],
        subject_id=row["subject_id"],
        task_id=row["task_id"],
        local_date=row["local_date"],
        start_utc=row["start_utc"],
        end_utc=row["end_utc"],
        duration_secs=row["duration_secs"],
        session_type=row["session_type"],
        notes=row["notes"],
        utc_offset_mins=row["utc_offset_mins"],
        source=row["source"],
        source_id=row["source_id"],
        created_at=row["created_at"],
    )


def get_all(
    conn: sqlite3.Connection,
    *,
    subject_id: int | None = None,
    task_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session_type: str | None = None,
) -> list[Session]:
    sql = "SELECT * FROM sessions WHERE 1=1"
    params: list = []
    if subject_id is not None:
        sql += " AND subject_id = ?"
        params.append(subject_id)
    if task_id is not None:
        sql += " AND task_id = ?"
        params.append(task_id)
    if date_from is not None:
        sql += " AND local_date >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND local_date <= ?"
        params.append(date_to)
    if session_type is not None:
        sql += " AND session_type = ?"
        params.append(session_type)
    sql += " ORDER BY local_date DESC, COALESCE(start_utc, created_at) DESC"
    return [_row_to_session(r) for r in conn.execute(sql, params).fetchall()]


def get_by_id(conn: sqlite3.Connection, session_id: int) -> Session | None:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _row_to_session(row) if row else None


def get_by_uuid(conn: sqlite3.Connection, uuid: str) -> Session | None:
    row = conn.execute("SELECT * FROM sessions WHERE uuid = ?", (uuid,)).fetchone()
    return _row_to_session(row) if row else None


def get_for_date(conn: sqlite3.Connection, local_date: str) -> list[Session]:
    rows = conn.execute(
        "SELECT * FROM sessions WHERE local_date = ? ORDER BY COALESCE(start_utc, created_at)",
        (local_date,),
    ).fetchall()
    return [_row_to_session(r) for r in rows]


def get_timed_for_date(conn: sqlite3.Connection, local_date: str) -> list[Session]:
    """Return only sessions that have start/end times (overlap checking)."""
    rows = conn.execute(
        """SELECT * FROM sessions
           WHERE local_date = ? AND start_utc IS NOT NULL
           ORDER BY start_utc""",
        (local_date,),
    ).fetchall()
    return [_row_to_session(r) for r in rows]


def insert(
    conn: sqlite3.Connection,
    *,
    uuid: str,
    subject_id: int,
    task_id: int | None,
    local_date: str,
    start_utc: str | None,
    end_utc: str | None,
    duration_secs: int,
    session_type: str,
    notes: str,
    utc_offset_mins: int,
    source: str | None = None,
    source_id: str | None = None,
    created_at: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO sessions
           (uuid, subject_id, task_id, local_date, start_utc, end_utc,
            duration_secs, session_type, notes, utc_offset_mins,
            source, source_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uuid, subject_id, task_id, local_date, start_utc, end_utc,
         duration_secs, session_type, notes, utc_offset_mins,
         source, source_id, created_at),
    )
    return cur.lastrowid  # type: ignore[return-value]


def update(
    conn: sqlite3.Connection,
    session_id: int,
    *,
    subject_id: int,
    task_id: int | None,
    local_date: str,
    start_utc: str | None,
    end_utc: str | None,
    duration_secs: int,
    session_type: str,
    notes: str,
    utc_offset_mins: int,
) -> None:
    conn.execute(
        """UPDATE sessions SET subject_id=?, task_id=?, local_date=?,
           start_utc=?, end_utc=?, duration_secs=?, session_type=?,
           notes=?, utc_offset_mins=?
           WHERE id=?""",
        (subject_id, task_id, local_date, start_utc, end_utc,
         duration_secs, session_type, notes, utc_offset_mins, session_id),
    )


def delete(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def total_secs_for_date(conn: sqlite3.Connection, local_date: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(duration_secs), 0) FROM sessions WHERE local_date = ?",
        (local_date,),
    ).fetchone()
    return row[0]


def daily_totals(
    conn: sqlite3.Connection,
    *,
    date_from: str,
    date_to: str,
    subject_id: int | None = None,
) -> list[tuple[str, int]]:
    """Return ``[(local_date, total_secs), ...]`` for the given range."""
    sql = """
        SELECT local_date, SUM(duration_secs) AS total
        FROM sessions
        WHERE local_date BETWEEN ? AND ?
    """
    params: list = [date_from, date_to]
    if subject_id is not None:
        sql += " AND subject_id = ?"
        params.append(subject_id)
    sql += " GROUP BY local_date ORDER BY local_date"
    return [(r["local_date"], r["total"]) for r in conn.execute(sql, params).fetchall()]
