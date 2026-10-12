"""Integration tests for DB constraints (foreign keys, checks, unique)."""

from __future__ import annotations

import pathlib
import sqlite3

import pytest

from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations


@pytest.fixture()
def conn(tmp_path: pathlib.Path):
    db_path = tmp_path / "test.db"
    c = get_connection(db_path)
    run_migrations(c, db_path)
    yield c
    c.close()


def _subject_id(conn) -> int:
    return conn.execute("SELECT id FROM subjects LIMIT 1").fetchone()[0]


class TestForeignKeys:
    def test_insert_task_bad_subject_raises(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks(subject_id, title, created_at) VALUES(9999,'X','2026-01-01T00:00:00Z')"  # noqa: E501
            )

    def test_delete_subject_with_tasks_raises(self, conn):
        sid = _subject_id(conn)
        conn.execute(
            "INSERT INTO tasks(subject_id,title,created_at) VALUES(?,?,'2026-01-01T00:00:00Z')",
            (sid, "Task A"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM subjects WHERE id=?", (sid,))

    def test_delete_subject_without_tasks_succeeds(self, conn):
        conn.execute(
            "INSERT INTO subjects(name, colour, sort_order, created_at) VALUES('Temp','#000',99,'2026-01-01T00:00:00Z')"  # noqa: E501
        )
        new_id = conn.execute("SELECT id FROM subjects WHERE name='Temp'").fetchone()[0]
        conn.execute("DELETE FROM subjects WHERE id=?", (new_id,))


class TestCheckConstraints:
    def test_negative_duration_raises(self, conn):
        sid = _subject_id(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO sessions(uuid,subject_id,local_date,duration_secs,
                   session_type,notes,utc_offset_mins,created_at)
                   VALUES('u1',?,?,?,'timer','',0,'2026-01-01T00:00:00Z')""",
                (sid, "2026-01-01", -1),
            )

    def test_end_before_start_raises(self, conn):
        sid = _subject_id(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO sessions(uuid,subject_id,local_date,start_utc,end_utc,
                   duration_secs,session_type,notes,utc_offset_mins,created_at)
                   VALUES('u2',?,'2026-01-01',
                   '2026-01-01T10:00:00Z','2026-01-01T09:00:00Z',
                   3600,'timer','',0,'2026-01-01T00:00:00Z')""",
                (sid,),
            )

    def test_done_task_without_completed_at_raises(self, conn):
        sid = _subject_id(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO tasks(subject_id,title,status,created_at)
                   VALUES(?,'T','done','2026-01-01T00:00:00Z')""",
                (sid,),
            )

    def test_done_task_with_completed_at_ok(self, conn):
        sid = _subject_id(conn)
        conn.execute(
            """INSERT INTO tasks(subject_id,title,status,completed_at,created_at)
               VALUES(?,'T','done','2026-01-01T10:00:00Z','2026-01-01T00:00:00Z')""",
            (sid,),
        )

    def test_duplicate_subject_name_raises(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO subjects(name,colour,sort_order,created_at) VALUES('Physics','#000',99,'2026-01-01T00:00:00Z')"  # noqa: E501
            )

    def test_case_insensitive_duplicate_raises(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO subjects(name,colour,sort_order,created_at) VALUES('PHYSICS','#000',99,'2026-01-01T00:00:00Z')"  # noqa: E501
            )

    def test_duplicate_session_source_id_raises(self, conn):
        sid = _subject_id(conn)
        conn.execute(
            """INSERT INTO sessions(uuid,subject_id,local_date,duration_secs,
               session_type,notes,utc_offset_mins,source,source_id,created_at)
               VALUES('u3',?,'2026-01-01',3600,'manual_duration','',0,'csv','row1','2026-01-01T00:00:00Z')""",
            (sid,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO sessions(uuid,subject_id,local_date,duration_secs,
                   session_type,notes,utc_offset_mins,source,source_id,created_at)
                   VALUES('u4',?,'2026-01-01',3600,'manual_duration','',0,'csv','row1','2026-01-01T00:00:00Z')""",
                (sid,),
            )

    def test_foreign_keys_are_enforced(self, conn):
        """Verify that PRAGMA foreign_keys=ON is actually active on this connection."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sessions(uuid,subject_id,local_date,duration_secs,session_type,notes,utc_offset_mins,created_at) VALUES('u5',9999,'2026-01-01',60,'timer','',0,'2026-01-01T00:00:00Z')"  # noqa: E501
            )
