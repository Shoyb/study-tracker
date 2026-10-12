"""Unit + integration tests for subject_service."""

from __future__ import annotations

import pathlib

import pytest

from study_tracker.core.clock import FakeClock
from study_tracker.core.errors import ConflictError, NotFoundError, ValidationError
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services import subject_service


@pytest.fixture()
def conn(tmp_path: pathlib.Path):
    db_path = tmp_path / "test.db"
    c = get_connection(db_path)
    run_migrations(c, db_path)
    yield c
    c.close()


CLOCK = FakeClock("2026-10-13T00:00:00Z")


class TestCreate:
    def test_create_returns_subject(self, conn):
        s = subject_service.create(conn, name="History", colour="#FF5722",
                                   created_at=CLOCK.now_utc())
        assert s.id > 0
        assert s.name == "History"
        assert s.colour == "#FF5722"
        assert not s.archived

    def test_create_strips_whitespace(self, conn):
        s = subject_service.create(conn, name="  Art  ", colour="#9C27B0",
                                   created_at=CLOCK.now_utc())
        assert s.name == "Art"

    def test_create_duplicate_raises_conflict(self, conn):
        subject_service.create(conn, name="Physics 2", colour="#1976D2",
                               created_at=CLOCK.now_utc())
        with pytest.raises(ConflictError):
            subject_service.create(conn, name="Physics 2", colour="#1976D2",
                                   created_at=CLOCK.now_utc())

    def test_create_case_insensitive_duplicate_raises(self, conn):
        subject_service.create(conn, name="Chemistry 2", colour="#388E3C",
                               created_at=CLOCK.now_utc())
        with pytest.raises(ConflictError):
            subject_service.create(conn, name="CHEMISTRY 2", colour="#388E3C",
                                   created_at=CLOCK.now_utc())

    def test_create_empty_name_raises_validation(self, conn):
        with pytest.raises(ValidationError):
            subject_service.create(conn, name="   ", colour="#000000",
                                   created_at=CLOCK.now_utc())

    def test_create_long_name_raises_validation(self, conn):
        with pytest.raises(ValidationError):
            subject_service.create(conn, name="X" * 61, colour="#000000",
                                   created_at=CLOCK.now_utc())

    def test_create_bad_colour_raises_validation(self, conn):
        with pytest.raises(ValidationError):
            subject_service.create(conn, name="Art", colour="blue",
                                   created_at=CLOCK.now_utc())

    def test_sort_order_increments(self, conn):
        a = subject_service.create(conn, name="AAA", colour="#000000",
                                   created_at=CLOCK.now_utc())
        b = subject_service.create(conn, name="BBB", colour="#000000",
                                   created_at=CLOCK.now_utc())
        assert b.sort_order > a.sort_order


class TestRename:
    def test_rename_works(self, conn):
        s = subject_service.create(conn, name="Old", colour="#000000",
                                   created_at=CLOCK.now_utc())
        renamed = subject_service.rename(conn, s.id, new_name="New")
        assert renamed.name == "New"

    def test_rename_to_same_name_ok(self, conn):
        s = subject_service.create(conn, name="Same", colour="#000000",
                                   created_at=CLOCK.now_utc())
        result = subject_service.rename(conn, s.id, new_name="Same")
        assert result.name == "Same"

    def test_rename_conflict_raises(self, conn):
        subject_service.create(conn, name="Alpha", colour="#000000",
                               created_at=CLOCK.now_utc())
        s2 = subject_service.create(conn, name="Beta", colour="#000000",
                                    created_at=CLOCK.now_utc())
        with pytest.raises(ConflictError):
            subject_service.rename(conn, s2.id, new_name="Alpha")

    def test_rename_nonexistent_raises(self, conn):
        with pytest.raises(NotFoundError):
            subject_service.rename(conn, 9999, new_name="X")


class TestArchiveDelete:
    def test_archive_and_unarchive(self, conn):
        s = subject_service.create(conn, name="Temp", colour="#000000",
                                   created_at=CLOCK.now_utc())
        archived = subject_service.archive(conn, s.id)
        assert archived.archived is True
        active = subject_service.get_active(conn)
        assert all(sub.id != s.id for sub in active)

        restored = subject_service.unarchive(conn, s.id)
        assert restored.archived is False

    def test_delete_unused_subject(self, conn):
        s = subject_service.create(conn, name="DeleteMe", colour="#000000",
                                   created_at=CLOCK.now_utc())
        subject_service.delete(conn, s.id)
        all_subjects = subject_service.get_all(conn)
        assert all(sub.id != s.id for sub in all_subjects)

    def test_delete_referenced_by_task_raises(self, conn):
        s = subject_service.create(conn, name="Referenced", colour="#000000",
                                   created_at=CLOCK.now_utc())
        conn.execute(
            "INSERT INTO tasks(subject_id, title, created_at) VALUES(?,?,'2026-01-01T00:00:00Z')",
            (s.id, "Task A"),
        )
        with pytest.raises(ConflictError, match="task"):
            subject_service.delete(conn, s.id)

    def test_delete_referenced_by_session_raises(self, conn):
        s = subject_service.create(conn, name="WithSession", colour="#000000",
                                   created_at=CLOCK.now_utc())
        conn.execute(
            """INSERT INTO sessions(uuid,subject_id,local_date,duration_secs,
               session_type,notes,utc_offset_mins,created_at)
               VALUES('u1',?,?,3600,'timer','',0,'2026-01-01T00:00:00Z')""",
            (s.id, "2026-10-13"),
        )
        with pytest.raises(ConflictError, match="session"):
            subject_service.delete(conn, s.id)

    def test_delete_nonexistent_raises(self, conn):
        with pytest.raises(NotFoundError):
            subject_service.delete(conn, 9999)

    def test_archived_subject_absent_from_get_active(self, conn):
        s = subject_service.create(conn, name="HideMe", colour="#000000",
                                   created_at=CLOCK.now_utc())
        subject_service.archive(conn, s.id)
        active = subject_service.get_active(conn)
        assert all(sub.id != s.id for sub in active)
        all_subjects = subject_service.get_all(conn, include_archived=True)
        assert any(sub.id == s.id for sub in all_subjects)


class TestReorder:
    def test_reorder_changes_sort_order(self, conn):
        a = subject_service.create(conn, name="A", colour="#000000",
                                   created_at=CLOCK.now_utc())
        b = subject_service.create(conn, name="B", colour="#000000",
                                   created_at=CLOCK.now_utc())
        # Swap order: B first, then A.
        subject_service.reorder(conn, [b.id, a.id])
        from study_tracker.db import subjects_repo
        ra = subjects_repo.get_by_id(conn, a.id)
        rb = subjects_repo.get_by_id(conn, b.id)
        assert rb.sort_order < ra.sort_order  # type: ignore[union-attr]
