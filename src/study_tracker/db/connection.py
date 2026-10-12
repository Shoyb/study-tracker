"""Database connection factory.

Every caller gets a connection with the required pragmas already set.
Never share a connection across threads – call ``get_connection()`` per thread.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# SQLite pragmas applied to every connection we open.
_PRAGMAS = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA mmap_size = 134217728;",  # 128 MB
]


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open (or create) the database and apply pragmas.

    The caller is responsible for closing the connection.
    Use as a context manager for automatic commit/rollback::

        with get_connection(db_path) as conn:
            conn.execute("INSERT ...")
    """
    conn = sqlite3.connect(
        str(db_path),
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,  # We manage transactions explicitly.
    )
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    return conn


def quick_check(conn: sqlite3.Connection) -> bool:
    """Run SQLite integrity check.  Returns ``True`` if the database is healthy."""
    row = conn.execute("PRAGMA quick_check;").fetchone()
    ok = row is not None and row[0] == "ok"
    if not ok:
        log.error("Database quick_check failed: %s", row[0] if row else "no result")
    return ok
