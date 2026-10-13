"""Integration tests for DB migrations."""

from __future__ import annotations

import pathlib

import pytest

from study_tracker.db import settings_repo
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
        assert version == 11

    def test_second_start_does_not_change_version(self, conn, db_path):
        run_migrations(conn, db_path)
        run_migrations(conn, db_path)  # should be a no-op
        version = conn.execute("PRAGMA user_version;").fetchone()[0]
        assert version == 11

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
        assert "No subject" in names
        assert len(names) == 6

    def test_seed_settings_present(self, conn, db_path):
        run_migrations(conn, db_path)
        row = conn.execute(
            "SELECT value FROM settings WHERE key='week_start'"
        ).fetchone()
        assert row is not None
        assert row[0] == "saturday"
        theme = conn.execute(
            "SELECT value FROM settings WHERE key='theme'"
        ).fetchone()
        assert theme is not None
        assert theme[0] == "dark"
        cutoff = conn.execute(
            "SELECT value FROM settings WHERE key='day_cutoff_minutes'"
        ).fetchone()
        assert cutoff[0] == "180"
        calendar_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='calendar_items'"
        ).fetchone()
        assert calendar_table is not None
        task_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        assert "scheduled_date" in task_columns
        pomodoro_presets = conn.execute(
            "SELECT COUNT(*) FROM pomodoro_presets"
        ).fetchone()[0]
        assert pomodoro_presets == 2
        exam_levels = conn.execute("SELECT COUNT(*) FROM exam_levels").fetchone()[0]
        exam_categories = conn.execute("SELECT COUNT(*) FROM exam_categories").fetchone()[0]
        assert exam_levels == 2
        assert exam_categories == 6

    def test_upgrade_changes_light_default_to_dark(self, conn, db_path):
        run_migrations(conn, db_path)
        settings_repo.set_value(conn, "theme", "light")
        migration_path = (
            pathlib.Path(__file__).parents[2]
            / "src/study_tracker/db/migrations/009_theme_dark.sql"
        )
        conn.executescript(migration_path.read_text(encoding="utf-8"))

        assert settings_repo.get(conn, "theme") == "dark"

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
