"""Database snapshot adapters for the version-one undoable entities."""

from __future__ import annotations

import sqlite3
from typing import Any

from study_tracker.core.errors import ConflictError
from study_tracker.db import sessions_repo

_TABLES = {
    "session": "sessions",
    "task": "tasks",
    "subject": "subjects",
    "calendar_item": "calendar_items",
}


def snapshot(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> dict[str, Any] | None:
    if entity_type == "exam":
        row = conn.execute("SELECT * FROM exams WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        parts = conn.execute(
            "SELECT * FROM exam_parts WHERE exam_id = ? ORDER BY position, id", (entity_id,)
        ).fetchall()
        group_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='exam_group_members'"
        ).fetchone()
        groups = (
            conn.execute(
                "SELECT * FROM exam_group_members WHERE exam_id = ? ORDER BY group_id",
                (entity_id,),
            ).fetchall()
            if group_exists
            else []
        )
        return {
            "exam": dict(row),
            "parts": [dict(part) for part in parts],
            "groups": [dict(group) for group in groups],
        }
    table = _table(entity_type)
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    return dict(row) if row else None


def restore(conn: sqlite3.Connection, entity_type: str, value: dict[str, Any]) -> None:
    if entity_type == "exam":
        _restore_exam(conn, value)
        return
    table = _table(entity_type)
    if entity_type == "session":
        conflicts = sessions_repo.find_overlapping(
            conn, start_utc=value["start_utc"], end_utc=value["end_utc"]
        ) if value.get("start_utc") and value.get("end_utc") else []
        if conflicts:
            raise ConflictError(
                f"Cannot restore session because it overlaps session {conflicts[0].id}."
            )
    columns = tuple(value)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        tuple(value[column] for column in columns),
    )


def apply(conn: sqlite3.Connection, entity_type: str, value: dict[str, Any]) -> None:
    if entity_type == "exam":
        _apply_exam(conn, value)
        return
    table = _table(entity_type)
    if entity_type == "session" and value.get("start_utc") and value.get("end_utc"):
        conflicts = sessions_repo.find_overlapping(
            conn,
            start_utc=value["start_utc"],
            end_utc=value["end_utc"],
            exclude_id=value["id"],
        )
        if conflicts:
            raise ConflictError(
                f"Cannot restore session because it overlaps session {conflicts[0].id}."
            )
    columns = tuple(column for column in value if column != "id")
    cursor = conn.execute(
        f"UPDATE {table} SET {', '.join(f'{column} = ?' for column in columns)} WHERE id = ?",
        tuple(value[column] for column in columns) + (value["id"],),
    )
    if cursor.rowcount != 1:
        raise ConflictError(f"Cannot update missing {entity_type} {value['id']} during undo.")


def delete(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> None:
    if entity_type == "exam":
        conn.execute("DELETE FROM exams WHERE id = ?", (entity_id,))
        return
    table = _table(entity_type)
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (entity_id,))


def _table(entity_type: str) -> str:
    try:
        return _TABLES[entity_type]
    except KeyError as exc:
        raise ValueError(f"Undo is not supported for entity type {entity_type!r}.") from exc


def _restore_exam(conn: sqlite3.Connection, value: dict[str, Any]) -> None:
    _insert_snapshot(conn, "exams", value["exam"])
    for part in value["parts"]:
        _insert_snapshot(conn, "exam_parts", part)
    for group in value.get("groups", []):
        _insert_snapshot(conn, "exam_group_members", group)


def _apply_exam(conn: sqlite3.Connection, value: dict[str, Any]) -> None:
    exam = value["exam"]
    _apply_row(conn, "exams", exam)
    conn.execute("DELETE FROM exam_parts WHERE exam_id = ?", (exam["id"],))
    for part in value["parts"]:
        _insert_snapshot(conn, "exam_parts", part)
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='exam_group_members'"
    ).fetchone():
        conn.execute("DELETE FROM exam_group_members WHERE exam_id = ?", (exam["id"],))
        for group in value.get("groups", []):
            _insert_snapshot(conn, "exam_group_members", group)


def _insert_snapshot(conn: sqlite3.Connection, table: str, value: dict[str, Any]) -> None:
    columns = tuple(value)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        tuple(value[column] for column in columns),
    )


def _apply_row(conn: sqlite3.Connection, table: str, value: dict[str, Any]) -> None:
    columns = tuple(column for column in value if column != "id")
    cursor = conn.execute(
        f"UPDATE {table} SET {', '.join(f'{column} = ?' for column in columns)} WHERE id = ?",
        tuple(value[column] for column in columns) + (value["id"],),
    )
    if cursor.rowcount != 1:
        raise ConflictError(f"Cannot update missing {table} row {value['id']} during undo.")
