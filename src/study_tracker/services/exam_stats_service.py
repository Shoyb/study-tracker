"""Category and level aggregation for exam analytics."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from study_tracker.db import exams_repo
from study_tracker.services.exam_service import get_exams, score


@dataclass(frozen=True)
class ExamAggregate:
    category: str
    level: str
    exam_count: int
    score_milli: int
    full_milli: int
    net_accuracy: Decimal | None
    attempt_accuracy: Decimal | None
    raw_accuracy: Decimal | None
    time_taken_seconds: int


def category_statistics(
    conn: sqlite3.Connection,
    *,
    category_id: int | None = None,
    level_id: int | None = None,
) -> list[ExamAggregate]:
    categories = {
        int(row["id"]): str(row["name"])
        for row in exams_repo.lookup_values(conn, "exam_categories", include_archived=True)
    }
    levels = {
        int(row["id"]): str(row["name"])
        for row in exams_repo.lookup_values(conn, "exam_levels", include_archived=True)
    }
    grouped: dict[tuple[str, str], list] = {}
    for exam in get_exams(
        conn,
        status="completed",
        category_id=category_id,
        level_id=level_id,
    ):
        key = (
            categories.get(exam.category_id, "No category"),
            levels.get(exam.level_id, "Unspecified"),
        )
        grouped.setdefault(key, []).append(exam)

    result = []
    for (category, level), exams in sorted(grouped.items()):
        score_total = full_total = correct = attempted = questions = time_taken = 0
        for exam in exams:
            summary = score(exam)
            if summary is None:
                continue
            score_total += summary.score_milli
            full_total += summary.full_milli
            time_taken += exam.taken_seconds or 0
            for part in exam.parts:
                if part.kind == "mcq":
                    part_correct = part.correct or 0
                    part_incorrect = part.incorrect or 0
                    part_skipped = part.skipped or 0
                    correct += part_correct
                    attempted += part_correct + part_incorrect
                    questions += part_correct + part_incorrect + part_skipped
        result.append(
            ExamAggregate(
                category=category,
                level=level,
                exam_count=len(exams),
                score_milli=score_total,
                full_milli=full_total,
                net_accuracy=Decimal(score_total) / full_total if full_total else None,
                attempt_accuracy=Decimal(correct) / attempted if attempted else None,
                raw_accuracy=Decimal(correct) / questions if questions else None,
                time_taken_seconds=time_taken,
            )
        )
    return result
