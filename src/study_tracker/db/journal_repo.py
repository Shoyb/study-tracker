"""Repository for the change journal used by undo/redo."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass
class ChangeEntry:
    id: int
    group_id: str
    entity_type: str
    entity_id: int
    action: str
    summary: str
    before_json: str | None
    after_json: str | None
    created_at_utc: str
    undone_at_utc: str | None = None


def append(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    entity_type: str,
    entity_id: int,
    action: str,
    summary: str,
    before_json: Any | None = None,
    after_json: Any | None = None,
    created_at_utc: str,
) -> ChangeEntry:
    row = conn.execute(
        """
        INSERT INTO change_journal (
            group_id, entity_type, entity_id, action, summary,
            before_json, after_json, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            group_id,
            entity_type,
            entity_id,
            action,
            summary,
            None if before_json is None else json.dumps(before_json, sort_keys=True),
            None if after_json is None else json.dumps(after_json, sort_keys=True),
            created_at_utc,
        ),
    )
    entry_id = row.lastrowid
    return get_by_id(conn, entry_id)


def get_by_id(conn: sqlite3.Connection, entry_id: int) -> ChangeEntry | None:
    row = conn.execute("SELECT * FROM change_journal WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        return None
    return ChangeEntry(
        id=row["id"],
        group_id=row["group_id"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        action=row["action"],
        summary=row["summary"],
        before_json=row["before_json"],
        after_json=row["after_json"],
        created_at_utc=row["created_at_utc"],
        undone_at_utc=row["undone_at_utc"],
    )


def list_recent(conn: sqlite3.Connection, limit: int = 50) -> list[ChangeEntry]:
    rows = conn.execute(
        "SELECT * FROM change_journal ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        ChangeEntry(
            id=r["id"],
            group_id=r["group_id"],
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            action=r["action"],
            summary=r["summary"],
            before_json=r["before_json"],
            after_json=r["after_json"],
            created_at_utc=r["created_at_utc"],
            undone_at_utc=r["undone_at_utc"],
        )
        for r in rows
    ]


def entries_for_group(
    conn: sqlite3.Connection, group_id: str, *, newest_first: bool
) -> list[ChangeEntry]:
    order = "DESC" if newest_first else "ASC"
    rows = conn.execute(
        f"SELECT * FROM change_journal WHERE group_id = ? ORDER BY id {order}", (group_id,)
    ).fetchall()
    return [get_by_id(conn, row["id"]) for row in rows]


def latest_group(conn: sqlite3.Connection, *, undone: bool) -> str | None:
    condition = "IS NOT NULL" if undone else "IS NULL"
    row = conn.execute(
        f"SELECT group_id FROM change_journal WHERE undone_at_utc {condition} "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["group_id"] if row else None


def mark_group_undone(conn: sqlite3.Connection, group_id: str, at_utc: str | None) -> None:
    conn.execute(
        "UPDATE change_journal SET undone_at_utc = ? WHERE group_id = ?",
        (at_utc, group_id),
    )


def clear_redo(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM change_journal WHERE undone_at_utc IS NOT NULL")


def purge(
    conn: sqlite3.Connection, *, keep_entries: int = 500, before_utc: str | None = None
) -> int:
    """Delete entries outside either retention bound and return rows removed."""
    cursor = conn.execute(
        "DELETE FROM change_journal WHERE group_id NOT IN "
        "(SELECT group_id FROM change_journal GROUP BY group_id "
        "ORDER BY MAX(id) DESC LIMIT ?)",
        (keep_entries,),
    )
    removed = cursor.rowcount
    if before_utc is not None:
        cursor = conn.execute(
            "DELETE FROM change_journal WHERE created_at_utc < ?", (before_utc,)
        )
        removed += cursor.rowcount
    return removed
