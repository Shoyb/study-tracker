"""Repository for idempotent CSV-import batch records."""

from __future__ import annotations

import sqlite3


def has_hash(conn: sqlite3.Connection, file_hash: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM import_batches WHERE file_hash = ? LIMIT 1", (file_hash,)
        ).fetchone()
        is not None
    )


def add(
    conn: sqlite3.Connection, *, filename: str, file_hash: str, imported_at: str, row_count: int
) -> None:
    conn.execute(
        "INSERT INTO import_batches(filename, file_hash, imported_at, row_count) "
        "VALUES (?, ?, ?, ?)",
        (filename, file_hash, imported_at, row_count),
    )
