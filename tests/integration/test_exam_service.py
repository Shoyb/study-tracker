"""Exam lifecycle, linked study time, daily goals, and undo behavior."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from study_tracker.core.errors import ValidationError
from study_tracker.db import exams_repo, sessions_repo
from study_tracker.db.connection import get_connection
from study_tracker.db.exams_repo import ExamPart
from study_tracker.db.migrate import run_migrations
from study_tracker.domain.exam_scoring import format_percentage
from study_tracker.services import day_plan_service, exam_service, session_service
from study_tracker.services.exam_stats_service import category_statistics
from study_tracker.services.undo.journal import JournalService


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "exams.db"
    connection = get_connection(db_path)
    run_migrations(connection, db_path)
    yield connection
    connection.close()


def _mcq(*, subject_id: int = 1, penalty: int = 250) -> ExamPart:
    return ExamPart(
        kind="mcq",
        label="Physics",
        subject_id=subject_id,
        total_questions=100,
        correct=72,
        incorrect=20,
        skipped=8,
        marks_per_correct_milli=1000,
        penalty_per_incorrect_milli=penalty,
        marks_per_skipped_milli=0,
    )


def test_completed_exam_scores_and_undo_restores_parts_and_linked_session(conn):
    category_id = conn.execute("SELECT id FROM exam_categories WHERE name = 'Weekly'").fetchone()[0]
    exam = exam_service.create_exam(
        conn,
        title="Physics weekly",
        exam_date="2026-10-13",
        category_id=category_id,
        allowed_seconds=7200,
        taken_seconds=3600,
        notes="Kinematics",
        parts=(_mcq(),),
        now_utc="2026-10-13T12:00:00Z",
    )
    score = exam_service.score(exam)
    assert score is not None
    assert score.score_milli == 67000
    assert format_percentage(score.net_accuracy) == "67.0%"
    assert exam.session_id is not None
    assert sessions_repo.get_by_id(conn, exam.session_id).duration_secs == 3600

    journal = JournalService(conn)
    assert journal.undo("2026-10-13T12:01:00Z") == "Create exam"
    assert exams_repo.get_by_id(conn, exam.id) is None
    assert sessions_repo.get_by_id(conn, exam.session_id) is None
    assert journal.redo("2026-10-13T12:02:00Z") == "Create exam"
    restored = exams_repo.get_by_id(conn, exam.id)
    assert restored is not None
    assert restored.uuid == exam.uuid
    assert restored.parts[0].id == exam.parts[0].id
    assert restored.session_id == exam.session_id


def test_editing_exam_updates_linked_session_and_undo_restores_old_result(conn):
    exam = exam_service.create_exam(
        conn,
        title="Chemistry daily",
        exam_date="2026-10-13",
        taken_seconds=1800,
        parts=(_mcq(),),
        now_utc="2026-10-13T12:00:00Z",
    )
    changed = exam_service.update_exam(
        conn,
        exam.id,
        title=exam.title,
        exam_date="2026-10-14",
        status="completed",
        category_id=None,
        level_id=None,
        allowed_seconds=None,
        taken_seconds=2400,
        notes=exam.notes,
        parts=(_mcq(penalty=500),),
        count_as_study=True,
        now_utc="2026-10-13T12:01:00Z",
    )
    assert changed.parts[0].penalty_per_incorrect_milli == 500
    assert sessions_repo.get_by_id(conn, exam.session_id).duration_secs == 2400

    assert JournalService(conn).undo("2026-10-13T12:02:00Z") == "Edit exam"
    restored = exams_repo.get_by_id(conn, exam.id)
    assert restored is not None
    assert restored.exam_date == "2026-10-13"
    assert restored.parts[0].penalty_per_incorrect_milli == 250
    assert sessions_repo.get_by_id(conn, exam.session_id).duration_secs == 1800


def test_planned_exams_do_not_advance_exam_goal_progress(conn):
    exam_service.create_exam(
        conn,
        title="Upcoming",
        exam_date="2026-10-13",
        status="planned",
        allowed_seconds=3600,
        now_utc="2026-10-13T12:00:00Z",
    )
    progress = day_plan_service.exam_goal_progress(conn, "2026-10-13")
    assert progress.goal.goal_type == "count"
    assert progress.goal.value == 1
    assert progress.completed == 0


def test_blank_future_exam_can_later_be_completed_with_marks(conn):
    planned = exam_service.create_exam(
        conn,
        title="Final model test",
        exam_date="2026-10-20",
        status="planned",
        category_id=conn.execute(
            "SELECT id FROM exam_categories WHERE name = 'Final model test'"
        ).fetchone()[0],
        now_utc="2026-10-13T12:00:00Z",
    )
    assert planned.parts == ()
    completed = exam_service.update_exam(
        conn,
        planned.id,
        title=planned.title,
        exam_date=planned.exam_date,
        status="completed",
        category_id=planned.category_id,
        level_id=None,
        allowed_seconds=7200,
        taken_seconds=3600,
        notes="",
        parts=(_mcq(),),
        count_as_study=False,
        now_utc="2026-10-20T12:00:00Z",
    )
    assert completed.status == "completed"
    assert completed.parts[0].correct == 72
    assert exam_service.score(completed).score_milli == 67000


def test_exam_requires_parts_when_completed_and_rejects_invalid_counts(conn):
    with pytest.raises(ValidationError, match="at least one"):
        exam_service.create_exam(
            conn,
            title="No result",
            exam_date="2026-10-13",
            status="completed",
            now_utc="2026-10-13T12:00:00Z",
        )
    with pytest.raises(ValueError, match="sum"):
        exam_service.create_exam(
            conn,
            title="Bad counts",
            exam_date="2026-10-13",
            parts=(
                _mcq(),
                ExamPart(
                    kind="mcq",
                    total_questions=1,
                    correct=0,
                    incorrect=0,
                    skipped=0,
                    marks_per_correct_milli=1000,
                    penalty_per_incorrect_milli=0,
                    marks_per_skipped_milli=0,
                ),
            ),
            now_utc="2026-10-13T12:00:00Z",
        )


def test_date_exam_goal_override_wins_without_rewriting_weekday_default(conn):
    day_plan_service.set_exam_goal(
        conn,
        "2026-10-13",
        goal_type="questions",
        value=50,
        now_utc="2026-10-13T12:00:00Z",
    )
    assert day_plan_service.get_exam_goal(conn, "2026-10-13").goal_type == "questions"
    assert day_plan_service.get_exam_goal(conn, "2026-10-20").goal_type == "count"


def test_study_goal_date_override_wins_without_changing_weekday_default(conn):
    day_plan_service.set_weekday_study_goal_seconds(conn, 1, 7200)
    day_plan_service.set_study_goal_seconds(
        conn, "2026-10-13", 3600, now_utc="2026-10-13T12:00:00Z"
    )

    assert day_plan_service.get_study_goal_seconds(conn, "2026-10-13") == 3600
    assert day_plan_service.get_study_goal_seconds(conn, "2026-10-20") == 7200


def test_deleting_linked_session_clears_exam_link_and_undo_restores_it(conn):
    exam = exam_service.create_exam(
        conn,
        title="Manual practice",
        exam_date="2026-10-13",
        taken_seconds=1800,
        parts=(_mcq(),),
        now_utc="2026-10-13T12:00:00Z",
    )
    session_service.delete(conn, exam.session_id, now_utc="2026-10-13T12:01:00Z")
    assert exams_repo.get_by_id(conn, exam.id).session_id is None

    assert JournalService(conn).undo("2026-10-13T12:02:00Z") == "Delete 1 session"
    restored = exams_repo.get_by_id(conn, exam.id)
    assert restored.session_id == exam.session_id
    assert sessions_repo.get_by_id(conn, exam.session_id) is not None


def test_category_statistics_filter_level_and_ignore_planned_exams(conn):
    categories = {
        row["name"]: row["id"] for row in exams_repo.lookup_values(conn, "exam_categories")
    }
    levels = {row["name"]: row["id"] for row in exams_repo.lookup_values(conn, "exam_levels")}
    for title, category, level in (
        ("Daily engineering", "Daily", "Engineering"),
        ("Daily varsity", "Daily", "Varsity"),
        ("Weekly engineering", "Weekly", "Engineering"),
    ):
        exam_service.create_exam(
            conn,
            title=title,
            exam_date="2026-10-13",
            category_id=categories[category],
            level_id=levels[level],
            parts=(_mcq(),),
            count_as_study=False,
            now_utc="2026-10-13T12:00:00Z",
        )
    exam_service.create_exam(
        conn,
        title="Upcoming daily",
        exam_date="2026-10-14",
        category_id=categories["Daily"],
        level_id=levels["Engineering"],
        status="planned",
        now_utc="2026-10-13T12:01:00Z",
    )

    all_rows = category_statistics(conn)
    assert [(row.category, row.level, row.exam_count) for row in all_rows] == [
        ("Daily", "Engineering", 1),
        ("Daily", "Varsity", 1),
        ("Weekly", "Engineering", 1),
    ]
    engineering_daily = category_statistics(
        conn, category_id=categories["Daily"], level_id=levels["Engineering"]
    )
    assert len(engineering_daily) == 1
    assert engineering_daily[0].exam_count == 1


def test_category_statistics_aggregate_marks_and_time_across_exam_dates(conn):
    categories = {
        row["name"]: row["id"] for row in exams_repo.lookup_values(conn, "exam_categories")
    }
    levels = {row["name"]: row["id"] for row in exams_repo.lookup_values(conn, "exam_levels")}
    mcq_engineering = ExamPart(
        kind="mcq",
        total_questions=10,
        correct=8,
        incorrect=1,
        skipped=1,
        marks_per_correct_milli=1000,
        penalty_per_incorrect_milli=250,
        marks_per_skipped_milli=0,
    )
    written_engineering = ExamPart(
        kind="written",
        written_full_milli=50000,
        written_obtained_milli=40000,
    )
    mcq_varsity = ExamPart(
        kind="mcq",
        total_questions=10,
        correct=6,
        incorrect=1,
        skipped=3,
        marks_per_correct_milli=1000,
        penalty_per_incorrect_milli=250,
        marks_per_skipped_milli=0,
    )

    for title, exam_date, category, level, seconds, part, status in (
        ("Daily MCQ", "2026-10-01", "Daily", "Engineering", 3600, mcq_engineering, "completed"),
        (
            "Daily written",
            "2026-10-05",
            "Daily",
            "Engineering",
            7200,
            written_engineering,
            "completed",
        ),
        ("Daily varsity", "2026-10-08", "Daily", "Varsity", 2700, mcq_varsity, "completed"),
        (
            "Weekly engineering",
            "2026-10-10",
            "Weekly",
            "Engineering",
            1800,
            mcq_engineering,
            "completed",
        ),
        ("Blank upcoming", "2026-10-12", "Daily", "Engineering", None, None, "planned"),
    ):
        exam_service.create_exam(
            conn,
            title=title,
            exam_date=exam_date,
            category_id=categories[category],
            level_id=levels[level],
            status=status,
            taken_seconds=seconds,
            parts=(part,) if part is not None else (),
            count_as_study=False,
            now_utc=f"{exam_date}T12:00:00Z",
        )

    rows = category_statistics(conn)
    by_group = {(row.category, row.level): row for row in rows}
    daily_engineering = by_group[("Daily", "Engineering")]
    assert daily_engineering.exam_count == 2
    assert daily_engineering.score_milli == 47750
    assert daily_engineering.full_milli == 60000
    assert daily_engineering.net_accuracy == Decimal(47750) / 60000
    assert daily_engineering.attempt_accuracy == Decimal(8) / 9
    assert daily_engineering.raw_accuracy == Decimal(8) / 10
    assert daily_engineering.time_taken_seconds == 10800
    assert by_group[("Daily", "Varsity")].exam_count == 1
    assert by_group[("Daily", "Varsity")].time_taken_seconds == 2700
    assert by_group[("Weekly", "Engineering")].exam_count == 1
    assert by_group[("Weekly", "Engineering")].time_taken_seconds == 1800

    filtered = category_statistics(
        conn, category_id=categories["Daily"], level_id=levels["Engineering"]
    )
    assert len(filtered) == 1
    assert filtered[0].exam_count == 2
