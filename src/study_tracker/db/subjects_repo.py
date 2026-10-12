"""Repository for the ``subjects`` table."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Subject:
    id: int
    name: str
    colour: str
    sort_order: int
    archived: bool
    created_at: str


def _row_to_subject(row: sqlite3.Row) -> Subject:
    return Subject(
        id=row["id"],
        name=row["name"],
        colour=row["colour"],
        sort_order=row["sort_order"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
    )


def get_all(conn: sqlite3.Connection, include_archived: bool = True) -> list[Subject]:
    sql = "SELECT * FROM subjects"
    if not include_archived:
        sql += " WHERE archived = 0"
    sql += " ORDER BY sort_order, id"
    return [_row_to_subject(r) for r in conn.execute(sql).fetchall()]


def get_by_id(conn: sqlite3.Connection, subject_id: int) -> Subject | None:
    row = conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
    return _row_to_subject(row) if row else None


def get_by_name(conn: sqlite3.Connection, name: str) -> Subject | None:
    row = conn.execute(
        "SELECT * FROM subjects WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return _row_to_subject(row) if row else None


def insert(
    conn: sqlite3.Connection,
    *,
    name: str,
    colour: str,
    sort_order: int,
    created_at: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO subjects(name, colour, sort_order, created_at) VALUES (?, ?, ?, ?)",
        (name, colour, sort_order, created_at),
    )
    return cur.lastrowid  # type: ignore[return-value]


def update(
    conn: sqlite3.Connection,
    subject_id: int,
    *,
    name: str,
    colour: str,
    sort_order: int,
    archived: bool,
) -> None:
    conn.execute(
        "UPDATE subjects SET name=?, colour=?, sort_order=?, archived=? WHERE id=?",
        (name, colour, sort_order, int(archived), subject_id),
    )


def delete(conn: sqlite3.Connection, subject_id: int) -> None:
    conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))


def max_sort_order(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM subjects").fetchone()
    return row[0]
