"""Repository for the ``tasks`` table."""

from __future__ import annotations

import logging
import sqlite3
import uuid as uuid_module
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Task:
    id: int
    subject_id: int
    title: str
    status: str  # 'todo' | 'in_progress' | 'done'
    priority: str  # 'low' | 'medium' | 'high'
    archived: bool
    due_date: str | None
    estimate_secs: int | None
    notes: str
    completed_at: str | None
    created_at: str
    # Computed by JOIN – not a real column:
    time_spent_secs: int = 0
    session_count: int = 0
    uuid: str | None = None
    scheduled_date: str | None = None


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        uuid=row["uuid"] if "uuid" in row.keys() else None,
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
        scheduled_date=row["scheduled_date"] if "scheduled_date" in row.keys() else None,
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


def ensure_uuids(conn: sqlite3.Connection) -> None:
    """Backfill stable identifiers for tasks created before migration 002."""
    for row in conn.execute("SELECT id FROM tasks WHERE uuid IS NULL").fetchall():
        conn.execute(
            "UPDATE tasks SET uuid = ? WHERE id = ?", (str(uuid_module.uuid4()), row["id"])
        )


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


def get_by_uuid(conn: sqlite3.Connection, task_uuid: str) -> Task | None:
    """Return a task by its stable CSV identity."""
    row = conn.execute("SELECT * FROM tasks WHERE uuid = ?", (task_uuid,)).fetchone()
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
    created_at: str,
    completed_at: str | None = None,
    uuid: str | None = None,
) -> int:
    uuid = uuid or str(uuid_module.uuid4())
    cur = conn.execute(
        """INSERT INTO tasks
           (uuid, subject_id, title, status, priority, due_date,
            estimate_secs, notes, completed_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            uuid,
            subject_id,
            title,
            status,
            priority,
            due_date,
            estimate_secs,
            notes,
            completed_at,
            created_at,
        ),
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
    scheduled_date: str | None = None,
) -> None:
    conn.execute(
        """UPDATE tasks SET subject_id=?, title=?, status=?, priority=?,
           archived=?, due_date=?, estimate_secs=?, notes=?, completed_at=?, scheduled_date=?
           WHERE id=?""",
        (
            subject_id,
            title,
            status,
            priority,
            int(archived),
            due_date,
            estimate_secs,
            notes,
            completed_at,
            scheduled_date,
            task_id,
        ),
    )


def delete(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def has_sessions(conn: sqlite3.Connection, task_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM sessions WHERE task_id = ? LIMIT 1", (task_id,)).fetchone()
    return row is not None
