"""Repository for exams, result parts, and their editable lookup lists."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class ExamPart:
    kind: str
    label: str = ""
    subject_id: int | None = None
    total_questions: int | None = None
    correct: int | None = None
    incorrect: int | None = None
    skipped: int | None = None
    marks_per_correct_milli: int | None = None
    penalty_per_incorrect_milli: int | None = None
    marks_per_skipped_milli: int | None = None
    written_full_milli: int | None = None
    written_obtained_milli: int | None = None
    id: int | None = None
    position: int = 0


@dataclass(frozen=True)
class Exam:
    id: int
    uuid: str
    title: str
    status: str
    exam_date: str
    category_id: int | None
    level_id: int | None
    allowed_seconds: int | None
    taken_seconds: int | None
    session_id: int | None
    notes: str
    created_at_utc: str
    updated_at_utc: str
    parts: tuple[ExamPart, ...]


def _row_to_part(row: sqlite3.Row) -> ExamPart:
    return ExamPart(
        id=row["id"],
        position=row["position"],
        kind=row["kind"],
        subject_id=row["subject_id"],
        label=row["label"],
        total_questions=row["total_questions"],
        correct=row["correct"],
        incorrect=row["incorrect"],
        skipped=row["skipped"],
        marks_per_correct_milli=row["marks_per_correct_milli"],
        penalty_per_incorrect_milli=row["penalty_per_incorrect_milli"],
        marks_per_skipped_milli=row["marks_per_skipped_milli"],
        written_full_milli=row["written_full_milli"],
        written_obtained_milli=row["written_obtained_milli"],
    )


def _row_to_exam(conn: sqlite3.Connection, row: sqlite3.Row) -> Exam:
    parts = conn.execute(
        "SELECT * FROM exam_parts WHERE exam_id = ? ORDER BY position, id", (row["id"],)
    ).fetchall()
    return Exam(
        id=row["id"],
        uuid=row["uuid"],
        title=row["title"],
        status=row["status"],
        exam_date=row["exam_date"],
        category_id=row["category_id"],
        level_id=row["level_id"],
        allowed_seconds=row["allowed_seconds"],
        taken_seconds=row["taken_seconds"],
        session_id=row["session_id"],
        notes=row["notes"],
        created_at_utc=row["created_at_utc"],
        updated_at_utc=row["updated_at_utc"],
        parts=tuple(_row_to_part(part) for part in parts),
    )


def insert_exam(
    conn: sqlite3.Connection,
    *,
    title: str,
    status: str,
    exam_date: str,
    category_id: int | None,
    level_id: int | None,
    allowed_seconds: int | None,
    taken_seconds: int | None,
    session_id: int | None,
    notes: str,
    created_at_utc: str,
    updated_at_utc: str,
    exam_uuid: str | None = None,
) -> int:
    cursor = conn.execute(
        """INSERT INTO exams (
            uuid, title, status, exam_date, category_id, level_id, allowed_seconds,
            taken_seconds, session_id, notes, created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            exam_uuid or str(uuid.uuid4()),
            title,
            status,
            exam_date,
            category_id,
            level_id,
            allowed_seconds,
            taken_seconds,
            session_id,
            notes,
            created_at_utc,
            updated_at_utc,
        ),
    )
    return cursor.lastrowid


def update_exam(
    conn: sqlite3.Connection,
    exam_id: int,
    *,
    title: str,
    status: str,
    exam_date: str,
    category_id: int | None,
    level_id: int | None,
    allowed_seconds: int | None,
    taken_seconds: int | None,
    session_id: int | None,
    notes: str,
    updated_at_utc: str,
) -> None:
    conn.execute(
        """UPDATE exams SET title=?, status=?, exam_date=?, category_id=?, level_id=?,
           allowed_seconds=?, taken_seconds=?, session_id=?, notes=?, updated_at_utc=?
           WHERE id=?""",
        (
            title,
            status,
            exam_date,
            category_id,
            level_id,
            allowed_seconds,
            taken_seconds,
            session_id,
            notes,
            updated_at_utc,
            exam_id,
        ),
    )


def replace_parts(conn: sqlite3.Connection, exam_id: int, parts: tuple[ExamPart, ...]) -> None:
    conn.execute("DELETE FROM exam_parts WHERE exam_id = ?", (exam_id,))
    for position, part in enumerate(parts):
        conn.execute(
            """INSERT INTO exam_parts (
                exam_id, position, kind, subject_id, label, total_questions, correct,
                incorrect, skipped, marks_per_correct_milli, penalty_per_incorrect_milli,
                marks_per_skipped_milli, written_full_milli, written_obtained_milli
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                exam_id,
                position,
                part.kind,
                part.subject_id,
                part.label,
                part.total_questions,
                part.correct,
                part.incorrect,
                part.skipped,
                part.marks_per_correct_milli,
                part.penalty_per_incorrect_milli,
                part.marks_per_skipped_milli,
                part.written_full_milli,
                part.written_obtained_milli,
            ),
        )


def get_by_id(conn: sqlite3.Connection, exam_id: int) -> Exam | None:
    row = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    return _row_to_exam(conn, row) if row else None


def get_all(
    conn: sqlite3.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    category_id: int | None = None,
    level_id: int | None = None,
    subject_id: int | None = None,
    query: str | None = None,
) -> list[Exam]:
    sql = "SELECT DISTINCT exams.* FROM exams"
    params: list[object] = []
    if subject_id is not None:
        sql += " JOIN exam_parts ON exam_parts.exam_id = exams.id"
    sql += " WHERE 1 = 1"
    for column, value, operator in (
        ("exam_date", date_from, ">="),
        ("exam_date", date_to, "<="),
        ("status", status, "="),
        ("category_id", category_id, "="),
        ("level_id", level_id, "="),
        ("exam_parts.subject_id", subject_id, "="),
    ):
        if value is not None:
            sql += f" AND {column} {operator} ?"
            params.append(value)
    if query and query.strip():
        sql += " AND exams.title LIKE ?"
        params.append(f"%{query.strip()}%")
    sql += " ORDER BY exam_date DESC, id DESC"
    return [_row_to_exam(conn, row) for row in conn.execute(sql, params).fetchall()]


def delete_exam(conn: sqlite3.Connection, exam_id: int) -> None:
    conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,))


def lookup_values(
    conn: sqlite3.Connection, table: str, *, include_archived: bool = False
) -> list[dict[str, object]]:
    if table not in {"exam_levels", "exam_categories", "scoring_presets"}:
        raise ValueError("Unsupported exam lookup table.")
    where = "" if include_archived else "WHERE is_archived = 0 "
    rows = conn.execute(
        f"SELECT * FROM {table} {where}ORDER BY sort_order, id"
    ).fetchall()
    return [dict(row) for row in rows]


def add_lookup(conn: sqlite3.Connection, table: str, name: str) -> int:
    if table not in {"exam_levels", "exam_categories"}:
        raise ValueError("Unsupported exam lookup table.")
    cursor = conn.execute(
        f"INSERT INTO {table} (name, sort_order) "
        f"VALUES (?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM {table}))",
        (name.strip(),),
    )
    return cursor.lastrowid


def archive_lookup(conn: sqlite3.Connection, table: str, item_id: int) -> None:
    if table not in {"exam_levels", "exam_categories", "scoring_presets"}:
        raise ValueError("Unsupported exam lookup table.")
    conn.execute(f"UPDATE {table} SET is_archived = 1 WHERE id = ?", (item_id,))


def add_scoring_preset(
    conn: sqlite3.Connection,
    *,
    name: str,
    marks_per_correct_milli: int,
    penalty_per_incorrect_milli: int,
    marks_per_skipped_milli: int,
) -> int:
    cursor = conn.execute(
        """INSERT INTO scoring_presets (
            name, marks_per_correct_milli, penalty_per_incorrect_milli,
            marks_per_skipped_milli, sort_order
        ) VALUES (?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM scoring_presets))""",
        (name, marks_per_correct_milli, penalty_per_incorrect_milli, marks_per_skipped_milli),
    )
    return cursor.lastrowid


def update_scoring_preset(
    conn: sqlite3.Connection,
    preset_id: int,
    *,
    name: str,
    marks_per_correct_milli: int,
    penalty_per_incorrect_milli: int,
    marks_per_skipped_milli: int,
) -> None:
    conn.execute(
        """UPDATE scoring_presets SET name=?, marks_per_correct_milli=?,
           penalty_per_incorrect_milli=?, marks_per_skipped_milli=? WHERE id=?""",
        (
            name.strip(),
            marks_per_correct_milli,
            penalty_per_incorrect_milli,
            marks_per_skipped_milli,
            preset_id,
        ),
    )
