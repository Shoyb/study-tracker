from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from study_tracker.db import sessions_repo, settings_repo
from study_tracker.db.connection import get_connection
from study_tracker.db.exams_repo import ExamPart
from study_tracker.db.migrate import run_migrations
from study_tracker.services import exam_service
from study_tracker.services.records_service import get_personal_records


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "records.db"
    connection = get_connection(db_path)
    run_migrations(connection, db_path)
    yield connection
    connection.close()


def _add_duration_session(
    conn, study_day: str, seconds: int, *, pomodoro_completed: bool | None = None
) -> None:
    sessions_repo.insert(
        conn,
        uuid=str(uuid.uuid4()),
        subject_id=1,
        task_id=None,
        local_date=study_day,
        start_utc=None,
        end_utc=None,
        duration_secs=seconds,
        session_type="manual_duration",
        notes="",
        utc_offset_mins=0,
        created_at=f"{study_day}T12:00:00Z",
        pomodoro_completed=pomodoro_completed,
    )


def test_personal_records_derive_highs_and_keep_earliest_tied_holder(conn):
    settings_repo.set_value(conn, "streak_threshold_hrs", "1")
    _add_duration_session(conn, "2026-10-12", 3600, pomodoro_completed=True)
    _add_duration_session(conn, "2026-10-12", 3600)
    _add_duration_session(conn, "2026-10-13", 3600)
    _add_duration_session(conn, "2026-10-14", 7200)
    exam_service.create_exam(
        conn,
        title="Physics best",
        exam_date="2026-10-14",
        status="completed",
        taken_seconds=3600,
        parts=(ExamPart(kind="written", written_full_milli=100000, written_obtained_milli=90000),),
        count_as_study=False,
        now_utc="2026-10-14T12:00:00Z",
    )

    records = {record.key: record for record in get_personal_records(conn)}

    assert records["study_day"].value == 7200
    assert records["study_day"].period == "2026-10-12"
    assert records["study_week"].value == 18000
    assert records["study_month"].value == 18000
    assert records["longest_streak"].value == 3
    assert records["pomodoros_day"].value == 1
    assert records["exam_accuracy"].value == Decimal("0.9")
    assert records["exam_accuracy"].detail == "Physics best"
