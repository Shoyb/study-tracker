"""Repository for calendar notes and events."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass


@dataclass
class CalendarItem:
    id: int
    uuid: str
    kind: str
    title: str
    notes: str
    local_date: str
    start_time: str | None
    end_time: str | None
    created_at: str
    updated_at: str
    task_id: int | None
    is_done: bool
    color_hex: str | None


def _row_to_item(row: sqlite3.Row) -> CalendarItem:
    return CalendarItem(
        id=row["id"],
        uuid=row["uuid"],
        kind=row["kind"],
        title=row["title"],
        notes=row["body"],
        local_date=row["item_date"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        created_at=row["created_at_utc"],
        updated_at=row["updated_at_utc"],
        task_id=row["task_id"],
        is_done=bool(row["is_done"]),
        color_hex=row["color_hex"],
    )


def create(
    conn: sqlite3.Connection,
    *,
    kind: str,
    title: str,
    notes: str,
    local_date: str,
    start_time: str | None = None,
    end_time: str | None = None,
    task_id: int | None = None,
    color_hex: str | None = None,
    created_at: str,
) -> CalendarItem:
    item_uuid = str(uuid.uuid4())
    row = conn.execute(
        """
        INSERT INTO calendar_items (
            uuid, item_date, kind, title, body, start_time, end_time,
            task_id, color_hex, created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_uuid,
            local_date,
            kind,
            title,
            notes,
            start_time,
            end_time,
            task_id,
            color_hex,
            created_at,
            created_at,
        ),
    )
    return get_by_id(conn, row.lastrowid)


def get_by_id(conn: sqlite3.Connection, item_id: int) -> CalendarItem | None:
    row = conn.execute("SELECT * FROM calendar_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return None
    return _row_to_item(row)


def get_for_date(
    conn: sqlite3.Connection, local_date: str, cutoff_minutes: int = 180
) -> list[CalendarItem]:
    rows = conn.execute(
        "SELECT * FROM calendar_items WHERE item_date = ?",
        (local_date,),
    ).fetchall()
    def sort_key(row: sqlite3.Row) -> tuple[int, str]:
        value = row["start_time"]
        if value is None:
            return (-1, row["title"])
        minutes = int(value[:2]) * 60 + int(value[3:])
        return ((minutes - cutoff_minutes) % 1440, row["title"])

    return [_row_to_item(row) for row in sorted(rows, key=sort_key)]


def get_for_range(conn: sqlite3.Connection, date_from: str, date_to: str) -> list[CalendarItem]:
    rows = conn.execute(
        "SELECT * FROM calendar_items WHERE item_date BETWEEN ? AND ? ORDER BY item_date",
        (date_from, date_to),
    ).fetchall()
    return [_row_to_item(row) for row in rows]


def update(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    title: str,
    notes: str,
    local_date: str,
    start_time: str | None,
    end_time: str | None,
    task_id: int | None,
    color_hex: str | None,
    is_done: bool,
    updated_at: str,
) -> None:
    conn.execute(
        """UPDATE calendar_items SET title=?, body=?, item_date=?, start_time=?, end_time=?,
           task_id=?, color_hex=?, is_done=?, updated_at_utc=? WHERE id=?""",
        (
            title,
            notes,
            local_date,
            start_time,
            end_time,
            task_id,
            color_hex,
            int(is_done),
            updated_at,
            item_id,
        ),
    )


def delete(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM calendar_items WHERE id = ?", (item_id,))
