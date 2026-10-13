"""Repository for exam manual groups."""

from __future__ import annotations

import sqlite3


def create_group(conn: sqlite3.Connection, *, name: str, created_at: str) -> int:
    row = conn.execute(
        "INSERT INTO exam_groups (name, created_at) VALUES (?, ?)",
        (name, created_at),
    )
    return row.lastrowid


def add_exam_to_group(conn: sqlite3.Connection, *, exam_id: int, group_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO exam_group_members (exam_id, group_id) VALUES (?, ?)",
        (exam_id, group_id),
    )
