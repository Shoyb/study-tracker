"""Integration tests for backup_service – create, validate, prune, restore."""

from __future__ import annotations

import pathlib
import sqlite3

import pytest

from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services.backup_service import (
    create_backup,
    list_backups,
    prune_backups,
    restore_backup,
    validate_backup,
)


@pytest.fixture()
def live_db(tmp_path: pathlib.Path):
    """Return (conn, db_path) for a fresh migrated database with one session."""
    db_path = tmp_path / "live.db"
    conn = get_connection(db_path)
    run_migrations(conn, db_path)
    # Insert a recognisable row to check it survives backup/restore.
    sid = conn.execute("SELECT id FROM subjects LIMIT 1").fetchone()[0]
    conn.execute(
        """INSERT INTO sessions(uuid,subject_id,local_date,duration_secs,
           session_type,notes,utc_offset_mins,created_at)
           VALUES('test-uuid',?,?,3600,'timer','backup test',0,'2026-01-01T00:00:00Z')""",
        (sid, "2026-10-13"),
    )
    yield conn, db_path
    conn.close()


class TestCreateAndValidate:
    def test_backup_created(self, live_db, tmp_path):
        conn, db_path = live_db
        backup_dir = tmp_path / "backups"
        path = create_backup(conn, backup_dir)
        assert path.exists()
        assert path.suffix == ".db"

    def test_backup_contains_wal_data(self, live_db, tmp_path):
        """Data written since last checkpoint must appear in the backup."""
        conn, db_path = live_db
        backup_dir = tmp_path / "backups"
        path = create_backup(conn, backup_dir)
        # Open backup independently and check the session row exists.
        bconn = sqlite3.connect(str(path))
        row = bconn.execute(
            "SELECT notes FROM sessions WHERE uuid='test-uuid'"
        ).fetchone()
        bconn.close()
        assert row is not None
        assert row[0] == "backup test"

    def test_validate_good_backup(self, live_db, tmp_path):
        conn, db_path = live_db
        path = create_backup(conn, tmp_path / "backups")
        assert validate_backup(path) is True

    def test_validate_missing_file(self, tmp_path):
        assert validate_backup(tmp_path / "nonexistent.db") is False

    def test_validate_corrupt_file(self, tmp_path):
        bad = tmp_path / "corrupt.db"
        bad.write_bytes(b"this is not a sqlite file at all")
        assert validate_backup(bad) is False


class TestPrune:
    def test_prune_keeps_n_newest(self, live_db, tmp_path):
        conn, db_path = live_db
        backup_dir = tmp_path / "backups"
        # Create 5 backups.
        for _ in range(5):
            create_backup(conn, backup_dir)
        prune_backups(backup_dir, keep=3)
        assert len(list_backups(backup_dir)) == 3


class TestRestore:
    def test_restore_replaces_database(self, live_db, tmp_path):
        conn, db_path = live_db
        backup_dir = tmp_path / "backups"
        backup_path = create_backup(conn, backup_dir)
        conn.close()

        # Wipe the live file.
        db_path.write_bytes(b"")

        restore_backup(backup_path, db_path)

        # Reopen and verify.
        new_conn = get_connection(db_path)
        row = new_conn.execute(
            "SELECT notes FROM sessions WHERE uuid='test-uuid'"
        ).fetchone()
        new_conn.close()
        assert row is not None
        assert row[0] == "backup test"

    def test_restore_no_wal_side_files(self, live_db, tmp_path):
        conn, db_path = live_db
        backup_dir = tmp_path / "backups"
        backup_path = create_backup(conn, backup_dir)
        conn.close()

        restore_backup(backup_path, db_path)

        wal = db_path.with_suffix(db_path.suffix + "-wal")
        shm = db_path.with_suffix(db_path.suffix + "-shm")
        assert not wal.exists()
        assert not shm.exists()

    def test_restore_validates_first(self, tmp_path):
        bad = tmp_path / "bad.db"
        bad.write_bytes(b"garbage")
        from study_tracker.core.errors import DatabaseError
        with pytest.raises(DatabaseError):
            restore_backup(bad, tmp_path / "live.db")
