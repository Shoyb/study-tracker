"""Integration tests for DB migrations."""

from __future__ import annotations

import pathlib

import pytest

from study_tracker.db.connection import get_connection, quick_check
from study_tracker.db.migrate import log_row_counts, run_migrations


@pytest.fixture()
def db_path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "test.db"


@pytest.fixture()
def conn(db_path):
    c = get_connection(db_path)
    yield c
    c.close()


class TestMigrations:
    def test_fresh_database_has_current_version(self, conn, db_path):
        run_migrations(conn, db_path)
        version = conn.execute("PRAGMA user_version;").fetchone()[0]
        assert version == 2

    def test_second_start_does_not_change_version(self, conn, db_path):
        run_migrations(conn, db_path)
        run_migrations(conn, db_path)  # should be a no-op
        version = conn.execute("PRAGMA user_version;").fetchone()[0]
        assert version == 2

    def test_all_tables_exist(self, conn, db_path):
        run_migrations(conn, db_path)
        expected = {"subjects", "tasks", "sessions", "timer_state", "settings",
                    "import_batches", "meta"}
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        found = {r[0] for r in rows}
        assert expected.issubset(found)

    def test_seed_subjects_present(self, conn, db_path):
        run_migrations(conn, db_path)
        rows = conn.execute("SELECT name FROM subjects ORDER BY sort_order").fetchall()
        names = [r[0] for r in rows]
        assert "Physics" in names
        assert "Mathematics" in names
        assert len(names) == 5

    def test_seed_settings_present(self, conn, db_path):
        run_migrations(conn, db_path)
        row = conn.execute(
            "SELECT value FROM settings WHERE key='week_start'"
        ).fetchone()
        assert row is not None
        assert row[0] == "saturday"

    def test_newer_version_raises(self, conn, db_path):
        run_migrations(conn, db_path)
        # Fake a newer version number.
        conn.execute("PRAGMA user_version = 999;")
        with pytest.raises(RuntimeError, match="newer"):
            run_migrations(conn, db_path)

    def test_quick_check_passes(self, conn, db_path):
        run_migrations(conn, db_path)
        assert quick_check(conn) is True

    def test_log_row_counts_does_not_raise(self, conn, db_path):
        run_migrations(conn, db_path)
        log_row_counts(conn)  # just ensure it doesn't crash
