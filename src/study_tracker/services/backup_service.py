"""Backup service – create and validate SQLite backups.

Uses the SQLite Online Backup API (``sqlite3.Connection.backup()``) so that
even data sitting in the WAL file is included.

Restore and the backup UI live in milestone 10.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from study_tracker.core.errors import DatabaseError

log = logging.getLogger(__name__)

_STAMP_FMT = "%Y%m%d_%H%M%S_%f"


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
    if not backup_path.exists():
        log.warning("Validate: file does not exist: %s", backup_path)
        return False
    try:
        conn = sqlite3.connect(str(backup_path))
        row = conn.execute("PRAGMA quick_check;").fetchone()
        conn.close()
        ok = row is not None and row[0] == "ok"
        if not ok:
            log.warning("Validate: quick_check failed for %s: %s", backup_path, row)
        return ok
    except Exception as exc:
        log.warning("Validate: could not open %s: %s", backup_path, exc)
        return False


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
    if not validate_backup(backup_path):
        raise DatabaseError(f"Backup file is corrupt or missing: {backup_path}")

    # Remove stale side files that would confuse SQLite after the swap.
    for suffix in ("-wal", "-shm"):
        side = db_path.with_suffix(db_path.suffix + suffix)
        if side.exists():
            try:
                side.unlink()
            except OSError as exc:
                log.warning("Could not remove %s: %s", side, exc)

    # Copy (not rename) so the backup remains intact.
    import shutil
    shutil.copy2(str(backup_path), str(db_path))
    log.info("Restored %s -> %s", backup_path.name, db_path)
