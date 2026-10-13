"""Backup service – create and validate SQLite backups.

Uses the SQLite Online Backup API (``sqlite3.Connection.backup()``) so that
even data sitting in the WAL file is included.

Restore and the backup UI live in milestone 10.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from study_tracker.core.errors import DatabaseError

log = logging.getLogger(__name__)

_STAMP_FMT = "%Y%m%d_%H%M%S_%f"


@dataclass(frozen=True)
class BackupReport:
    """Validation outcome and counts displayed before a restore."""

    ok: bool
    message: str
    user_version: int = 0
    subjects: int = 0
    tasks: int = 0
    sessions: int = 0


def _timestamp() -> str:
    return datetime.now(tz=UTC).strftime(_STAMP_FMT)


def create_backup(source_conn: sqlite3.Connection, backup_dir: Path) -> Path:
    """Copy the live database (including WAL) to *backup_dir*.

    Returns the path of the newly created backup file.

    Args:
        source_conn: An open connection to the source database.
        backup_dir:  Directory to write the backup into (created if needed).
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"study_tracker_{_timestamp()}.db"
    try:
        dest_conn = sqlite3.connect(str(dest))
        with dest_conn:
            source_conn.backup(dest_conn)
        dest_conn.close()
        log.info("Backup created: %s", dest)
    except Exception as exc:
        raise DatabaseError(f"Backup failed: {exc}") from exc
    return dest


def validate_backup(backup_path: Path) -> bool:
    """Open a backup file and run ``PRAGMA quick_check``.

    Returns ``True`` if the file is a healthy SQLite database.
    """
    return backup_report(backup_path).ok


def backup_report(backup_path: Path) -> BackupReport:
    """Validate schema, integrity and foreign keys and return useful row counts."""
    if not backup_path.exists():
        return BackupReport(False, f"Backup file does not exist: {backup_path}")
    try:
        conn = sqlite3.connect(str(backup_path))
        integrity = conn.execute("PRAGMA integrity_check;").fetchone()
        foreign_keys = conn.execute("PRAGMA foreign_key_check;").fetchall()
        version = conn.execute("PRAGMA user_version;").fetchone()[0]
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        required = {"subjects", "tasks", "sessions", "meta"}
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in required
        }
        conn.close()
        if integrity is None or integrity[0] != "ok":
            return BackupReport(False, "SQLite integrity check failed.")
        if foreign_keys:
            return BackupReport(False, "Backup contains foreign-key violations.")
        if not required.issubset(tables):
            return BackupReport(False, "Backup is missing required Study Tracker tables.")
        from study_tracker.db.migrate import latest_known_version

        if version > latest_known_version():
            return BackupReport(
                False, "Backup was made by a newer version of Study Tracker.", version
            )
        return BackupReport(
            True,
            "Backup is healthy.",
            version,
            counts["subjects"],
            counts["tasks"],
            counts["sessions"],
        )
    except Exception as exc:
        log.warning("Validate: could not open %s: %s", backup_path, exc)
        return BackupReport(False, f"Could not open backup: {exc}")


def file_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a file (for import deduplication)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def list_backups(backup_dir: Path) -> list[Path]:
    """Return backup files sorted newest-first."""
    if not backup_dir.exists():
        return []
    files = sorted(backup_dir.glob("study_tracker_*.db"), reverse=True)
    return list(files)


def prune_backups(backup_dir: Path, keep: int = 10) -> None:
    """Delete the oldest backups, keeping at most *keep* files."""
    all_backups = list_backups(backup_dir)
    for old in all_backups[keep:]:
        try:
            old.unlink()
            log.info("Pruned old backup: %s", old)
        except OSError as exc:
            log.warning("Could not delete backup %s: %s", old, exc)


def restore_backup(backup_path: Path, db_path: Path) -> None:
    """Replace the live database with a backup.

    Steps:
    1. Validate the backup.
    2. Close-and-checkpoint the WAL by opening a temporary connection.
    3. Remove stale WAL / SHM files.
    4. Atomically rename (or copy) the backup over the live file.

    The caller must close the application's normal connection *before*
    calling this function, and reopen it afterwards.
    """
    report = backup_report(backup_path)
    if not report.ok:
        raise DatabaseError(report.message)

    # Remove stale side files that would confuse SQLite after the swap.
    for suffix in ("-wal", "-shm"):
        side = db_path.with_suffix(db_path.suffix + suffix)
        if side.exists():
            try:
                side.unlink()
            except OSError as exc:
                log.warning("Could not remove %s: %s", side, exc)

    # Copy to a file in the target directory, then swap atomically. The
    # original backup remains untouched if the operation fails.
    descriptor, temporary = tempfile.mkstemp(prefix=".restore_", suffix=".db", dir=db_path.parent)
    try:
        with os.fdopen(descriptor, "wb") as target, backup_path.open("rb") as source:
            target.write(source.read())
        os.replace(temporary, db_path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    log.info("Restored %s -> %s", backup_path.name, db_path)
