"""Repository for the ``tasks`` table."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Task:
    id: int
    subject_id: int
    title: str
    status: str          # 'todo' | 'in_progress' | 'done'
    priority: str        # 'low' | 'medium' | 'high'
    archived: bool
    due_date: str | None
    estimate_secs: int | None
    notes: str
    completed_at: str | None
    created_at: str
    # Computed by JOIN – not a real column:
    time_spent_secs: int = 0


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        subject_id=row["subject_id"],
        title=row["title"],
        status=row["status"],
        priority=row["priority"],
        archived=bool(row["archived"]),
        due_date=row["due_date"],
        estimate_secs=row["estimate_secs"],
        notes=row["notes"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        time_spent_secs=row["time_spent_secs"] if "time_spent_secs" in row.keys() else 0,
    )


def get_all(
    conn: sqlite3.Connection,
    *,
    include_archived: bool = False,
    subject_id: int | None = None,
    status: str | None = None,
) -> list[Task]:
    sql = """
        SELECT t.*,
               COALESCE(SUM(s.duration_secs), 0) AS time_spent_secs
        FROM tasks t
        LEFT JOIN sessions s ON s.task_id = t.id
        WHERE 1=1
    """
    params: list = []
    if not include_archived:
        sql += " AND t.archived = 0"
    if subject_id is not None:
        sql += " AND t.subject_id = ?"
        params.append(subject_id)
    if status is not None:
        sql += " AND t.status = ?"
        params.append(status)
    sql += " GROUP BY t.id ORDER BY t.created_at DESC"
    return [_row_to_task(r) for r in conn.execute(sql, params).fetchall()]


def get_by_id(conn: sqlite3.Connection, task_id: int) -> Task | None:
    sql = """
        SELECT t.*,
               COALESCE(SUM(s.duration_secs), 0) AS time_spent_secs
        FROM tasks t
        LEFT JOIN sessions s ON s.task_id = t.id
        WHERE t.id = ?
        GROUP BY t.id
    """
    row = conn.execute(sql, (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def insert(
    conn: sqlite3.Connection,
    *,
    subject_id: int,
    title: str,
    status: str = "todo",
    priority: str = "medium",
    due_date: str | None = None,
    estimate_secs: int | None = None,
    notes: str = "",
    completed_at: str | None = None,
    created_at: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO tasks
           (subject_id, title, status, priority, due_date,
            estimate_secs, notes, completed_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (subject_id, title, status, priority, due_date,
         estimate_secs, notes, completed_at, created_at),
    )
    return cur.lastrowid  # type: ignore[return-value]


def update(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    subject_id: int,
    title: str,
    status: str,
    priority: str,
    archived: bool,
    due_date: str | None,
    estimate_secs: int | None,
    notes: str,
    completed_at: str | None,
) -> None:
    conn.execute(
        """UPDATE tasks SET subject_id=?, title=?, status=?, priority=?,
           archived=?, due_date=?, estimate_secs=?, notes=?, completed_at=?
           WHERE id=?""",
        (subject_id, title, status, priority, int(archived),
         due_date, estimate_secs, notes, completed_at, task_id),
    )


def delete(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def has_sessions(conn: sqlite3.Connection, task_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE task_id = ? LIMIT 1", (task_id,)
    ).fetchone()
    return row is not None
