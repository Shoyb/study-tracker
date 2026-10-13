"""Exam validation, scoring, linked study time, and undoable persistence."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date

from study_tracker.core.errors import NotFoundError, ValidationError
from study_tracker.db import exams_repo, sessions_repo, subjects_repo
from study_tracker.db.exams_repo import Exam, ExamPart
from study_tracker.domain.exam_scoring import (
    ExamScore,
    MCQPart,
    WrittenPart,
    score_exam,
    score_part,
)
from study_tracker.services.undo.adapters import snapshot
from study_tracker.services.undo.journal import JournalService


def create_exam(
    conn: sqlite3.Connection,
    *,
    title: str,
    exam_date: str,
    status: str = "completed",
    category_id: int | None = None,
    level_id: int | None = None,
    allowed_seconds: int | None = None,
    taken_seconds: int | None = None,
    notes: str = "",
    parts: tuple[ExamPart, ...] = (),
    count_as_study: bool = True,
    now_utc: str,
) -> Exam:
    title, exam_date, notes = _validate_exam(
        conn,
        title=title,
        exam_date=exam_date,
        status=status,
        allowed_seconds=allowed_seconds,
        taken_seconds=taken_seconds,
        category_id=category_id,
        level_id=level_id,
        parts=parts,
        notes=notes,
    )
    with JournalService(conn).action("Create exam", now_utc) as record:
        session_id = None
        if count_as_study and status == "completed" and taken_seconds:
            session_id = _insert_exam_session(
                conn, exam_date, taken_seconds, title, parts, now_utc
            )
            record("session", session_id, "create", None, snapshot(conn, "session", session_id))
        exam_id = exams_repo.insert_exam(
            conn,
            title=title,
            status=status,
            exam_date=exam_date,
            category_id=category_id,
            level_id=level_id,
            allowed_seconds=allowed_seconds,
            taken_seconds=taken_seconds if status == "completed" else None,
            session_id=session_id,
            notes=notes,
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
        )
        exams_repo.replace_parts(conn, exam_id, parts)
        record("exam", exam_id, "create", None, snapshot(conn, "exam", exam_id))
    exam = exams_repo.get_by_id(conn, exam_id)
    assert exam is not None
    return exam


def update_exam(
    conn: sqlite3.Connection,
    exam_id: int,
    *,
    title: str,
    exam_date: str,
    status: str,
    category_id: int | None,
    level_id: int | None,
    allowed_seconds: int | None,
    taken_seconds: int | None,
    notes: str,
    parts: tuple[ExamPart, ...],
    count_as_study: bool,
    now_utc: str,
) -> Exam:
    existing = exams_repo.get_by_id(conn, exam_id)
    if existing is None:
        raise NotFoundError(f"Exam {exam_id} not found.")
    title, exam_date, notes = _validate_exam(
        conn,
        title=title,
        exam_date=exam_date,
        status=status,
        allowed_seconds=allowed_seconds,
        taken_seconds=taken_seconds,
        category_id=category_id,
        level_id=level_id,
        parts=parts,
        notes=notes,
    )
    before_exam = snapshot(conn, "exam", exam_id)
    with JournalService(conn).action("Edit exam", now_utc) as record:
        session_id = existing.session_id
        session_to_delete: int | None = None
        wants_session = count_as_study and status == "completed" and bool(taken_seconds)
        if wants_session and session_id is None:
            session_id = _insert_exam_session(
                conn, exam_date, taken_seconds or 0, title, parts, now_utc
            )
            record("session", session_id, "create", None, snapshot(conn, "session", session_id))
        elif wants_session and session_id is not None:
            session = sessions_repo.get_by_id(conn, session_id)
            if session is not None:
                before_session = snapshot(conn, "session", session_id)
                subjects = _session_subject(parts)
                sessions_repo.update(
                    conn,
                    session_id,
                    subject_id=subjects,
                    task_id=None,
                    local_date=exam_date,
                    start_utc=None,
                    end_utc=None,
                    duration_secs=taken_seconds or 1,
                    session_type="manual_duration",
                    notes=f"Exam practice: {title}",
                    utc_offset_mins=0,
                )
                record(
                    "session",
                    session_id,
                    "update",
                    before_session,
                    snapshot(conn, "session", session_id),
                )
        else:
            if session_id is not None:
                session_to_delete = session_id
            session_id = None

        exams_repo.update_exam(
            conn,
            exam_id,
            title=title,
            status=status,
            exam_date=exam_date,
            category_id=category_id,
            level_id=level_id,
            allowed_seconds=allowed_seconds,
            taken_seconds=taken_seconds if status == "completed" else None,
            session_id=session_id,
            notes=notes,
            updated_at_utc=now_utc,
        )
        exams_repo.replace_parts(conn, exam_id, parts)
        record("exam", exam_id, "update", before_exam, snapshot(conn, "exam", exam_id))
        if session_to_delete is not None:
            session = sessions_repo.get_by_id(conn, session_to_delete)
            if session is not None:
                before_session = snapshot(conn, "session", session_to_delete)
                sessions_repo.delete(conn, session_to_delete)
                record("session", session_to_delete, "delete", before_session, None)
    updated = exams_repo.get_by_id(conn, exam_id)
    assert updated is not None
    return updated


def delete_exam(
    conn: sqlite3.Connection, exam_id: int, *, delete_linked_session: bool, now_utc: str
) -> None:
    exam = exams_repo.get_by_id(conn, exam_id)
    if exam is None:
        raise NotFoundError(f"Exam {exam_id} not found.")
    before_exam = snapshot(conn, "exam", exam_id)
    with JournalService(conn).action("Delete exam", now_utc) as record:
        exams_repo.delete_exam(conn, exam_id)
        record("exam", exam_id, "delete", before_exam, None)
        if delete_linked_session and exam.session_id is not None:
            session = sessions_repo.get_by_id(conn, exam.session_id)
            if session is not None:
                before_session = snapshot(conn, "session", session.id)
                sessions_repo.delete(conn, session.id)
                record("session", session.id, "delete", before_session, None)


def get_exam(conn: sqlite3.Connection, exam_id: int) -> Exam | None:
    return exams_repo.get_by_id(conn, exam_id)


def get_exams(conn: sqlite3.Connection, **filters) -> list[Exam]:
    return exams_repo.get_all(conn, **filters)


def score(exam: Exam) -> ExamScore | None:
    if exam.status != "completed" or not exam.parts:
        return None
    return score_exam([_domain_part(part) for part in exam.parts], taken_seconds=exam.taken_seconds)


def duplicate_exam(conn: sqlite3.Connection, exam_id: int, *, new_date: str, now_utc: str) -> Exam:
    exam = exams_repo.get_by_id(conn, exam_id)
    if exam is None:
        raise NotFoundError(f"Exam {exam_id} not found.")
    return create_exam(
        conn,
        title=exam.title,
        exam_date=new_date,
        status="planned",
        category_id=exam.category_id,
        level_id=exam.level_id,
        allowed_seconds=exam.allowed_seconds,
        notes=exam.notes,
        now_utc=now_utc,
    )


def _validate_exam(
    conn: sqlite3.Connection,
    *,
    title: str,
    exam_date: str,
    status: str,
    allowed_seconds: int | None,
    taken_seconds: int | None,
    category_id: int | None,
    level_id: int | None,
    parts: tuple[ExamPart, ...],
    notes: str,
) -> tuple[str, str, str]:
    title = title.strip()
    if not title or len(title) > 200:
        raise ValidationError("Exam title must be between 1 and 200 characters.")
    try:
        date.fromisoformat(exam_date)
    except ValueError as exc:
        raise ValidationError("Exam date must be a valid YYYY-MM-DD date.") from exc
    if status not in {"planned", "completed"}:
        raise ValidationError("Exam status must be planned or completed.")
    if allowed_seconds is not None and allowed_seconds <= 0:
        raise ValidationError("Allowed time must be positive.")
    if taken_seconds is not None and taken_seconds <= 0:
        raise ValidationError("Time taken must be positive.")
    if status == "planned" and (taken_seconds is not None or parts):
        raise ValidationError("Planned exams cannot contain results or time taken.")
    if status == "completed" and not parts:
        raise ValidationError("A completed exam must contain at least one result part.")
    for part in parts:
        score_part(_domain_part(part))
        if part.subject_id is not None and subjects_repo.get_by_id(conn, part.subject_id) is None:
            raise NotFoundError(f"Subject {part.subject_id} not found.")
    if category_id is not None and not _lookup_exists(conn, "exam_categories", category_id):
        raise NotFoundError(f"Exam category {category_id} not found.")
    if level_id is not None and not _lookup_exists(conn, "exam_levels", level_id):
        raise NotFoundError(f"Exam level {level_id} not found.")
    return title, exam_date, notes.strip()


def _lookup_exists(conn: sqlite3.Connection, table: str, item_id: int) -> bool:
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (item_id,)).fetchone() is not None


def _domain_part(part: ExamPart) -> MCQPart | WrittenPart:
    if part.kind == "mcq":
        if None in (
            part.total_questions,
            part.correct,
            part.incorrect,
            part.skipped,
            part.marks_per_correct_milli,
            part.penalty_per_incorrect_milli,
            part.marks_per_skipped_milli,
        ):
            raise ValidationError("MCQ result fields are required.")
        return MCQPart(
            total_questions=part.total_questions,
            correct=part.correct,
            incorrect=part.incorrect,
            skipped=part.skipped,
            marks_per_correct_milli=part.marks_per_correct_milli,
            penalty_per_incorrect_milli=part.penalty_per_incorrect_milli,
            marks_per_skipped_milli=part.marks_per_skipped_milli,
        )
    if part.kind == "written":
        if part.written_full_milli is None or part.written_obtained_milli is None:
            raise ValidationError("Written full and obtained marks are required.")
        return WrittenPart(part.written_full_milli, part.written_obtained_milli)
    raise ValidationError("Part kind must be MCQ or written.")


def _session_subject(parts: tuple[ExamPart, ...]) -> int:
    subjects = {part.subject_id for part in parts if part.subject_id is not None}
    return next(iter(subjects)) if len(subjects) == 1 else 1


def _insert_exam_session(
    conn: sqlite3.Connection,
    exam_date: str,
    duration_secs: int,
    title: str,
    parts: tuple[ExamPart, ...],
    now_utc: str,
) -> int:
    return sessions_repo.insert(
        conn,
        uuid=str(uuid.uuid4()),
        subject_id=_session_subject(parts),
        task_id=None,
        local_date=exam_date,
        start_utc=None,
        end_utc=None,
        duration_secs=duration_secs,
        session_type="manual_duration",
        notes=f"Exam practice: {title}",
        utc_offset_mins=0,
        created_at=now_utc,
    )
