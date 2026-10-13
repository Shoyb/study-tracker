"""Resolve per-day exam goals from a date override or weekday default."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from study_tracker.core.errors import ValidationError
from study_tracker.db import day_plans_repo
from study_tracker.db.exams_repo import get_all as get_exams

_GOAL_TYPES = {"none", "count", "minutes", "questions"}


@dataclass(frozen=True)
class ExamGoal:
    goal_type: str
    value: int
    is_rest_day: bool = False


@dataclass(frozen=True)
class ExamGoalProgress:
    goal: ExamGoal
    completed: int


def get_study_goal_seconds(conn: sqlite3.Connection, study_day: str) -> int:
    day = date.fromisoformat(study_day)
    plan = day_plans_repo.get_day_plan(conn, study_day)
    if plan is not None and plan["study_goal_secs"] is not None:
        return int(plan["study_goal_secs"])
    default = day_plans_repo.get_weekday_default(conn, day.weekday())
    return int(default["study_goal_secs"]) if default is not None else 0


def set_study_goal_seconds(
    conn: sqlite3.Connection, study_day: str, seconds: int, *, now_utc: str
) -> None:
    if not 0 <= seconds <= 86400:
        raise ValidationError("Study goal must be between 0 and 24 hours.")
    date.fromisoformat(study_day)
    existing = day_plans_repo.get_day_plan(conn, study_day)
    day_plans_repo.upsert_day_plan(
        conn,
        local_date=study_day,
        study_goal_secs=seconds,
        exam_goal_type=existing["exam_goal_type"] if existing else None,
        exam_goal_value=existing["exam_goal_value"] if existing else None,
        is_rest_day=bool(existing["is_rest_day"]) if existing else False,
        notes=existing["notes"] if existing else "",
        updated_at_utc=now_utc,
    )


def is_rest_day(conn: sqlite3.Connection, study_day: str) -> bool:
    plan = day_plans_repo.get_day_plan(conn, study_day)
    return bool(plan["is_rest_day"]) if plan is not None else False


def save_day_plan(
    conn: sqlite3.Connection,
    study_day: str,
    *,
    study_goal_secs: int,
    exam_goal_type: str,
    exam_goal_value: int,
    is_rest_day: bool,
    now_utc: str,
) -> None:
    date.fromisoformat(study_day)
    if not 0 <= study_goal_secs <= 86400:
        raise ValidationError("Study goal must be between 0 and 24 hours.")
    _validate_goal(exam_goal_type, exam_goal_value)
    if is_rest_day:
        study_goal_secs = 0
        exam_goal_type = "none"
        exam_goal_value = 0
    existing = day_plans_repo.get_day_plan(conn, study_day)
    day_plans_repo.upsert_day_plan(
        conn,
        local_date=study_day,
        study_goal_secs=study_goal_secs,
        exam_goal_type=exam_goal_type,
        exam_goal_value=exam_goal_value,
        is_rest_day=is_rest_day,
        notes=existing["notes"] if existing else "",
        updated_at_utc=now_utc,
    )


def set_weekday_study_goal_seconds(
    conn: sqlite3.Connection, weekday: int, seconds: int
) -> None:
    if not 0 <= weekday <= 6:
        raise ValidationError("Weekday must be between 0 (Monday) and 6 (Sunday).")
    if not 0 <= seconds <= 86400:
        raise ValidationError("Study goal must be between 0 and 24 hours.")
    current = day_plans_repo.get_weekday_default(conn, weekday)
    day_plans_repo.upsert_weekday_default(
        conn,
        weekday=weekday,
        study_goal_secs=seconds,
        exam_goal_type=current["exam_goal_type"] if current else "count",
        exam_goal_value=current["exam_goal_value"] if current else 1,
    )


def get_exam_goal(conn: sqlite3.Connection, study_day: str) -> ExamGoal:
    day = date.fromisoformat(study_day)
    plan = day_plans_repo.get_day_plan(conn, study_day)
    if plan is not None:
        if plan["is_rest_day"]:
            return ExamGoal("none", 0, True)
        goal_type = plan["exam_goal_type"]
        value = plan["exam_goal_value"]
        if goal_type is not None and value is not None:
            return ExamGoal(goal_type, value)
    default = day_plans_repo.get_weekday_default(conn, day.weekday())
    if default is None:
        return ExamGoal("count", 1)
    return ExamGoal(default["exam_goal_type"], default["exam_goal_value"])


def set_exam_goal(
    conn: sqlite3.Connection,
    study_day: str,
    *,
    goal_type: str,
    value: int,
    now_utc: str,
    is_rest_day: bool = False,
) -> None:
    _validate_goal(goal_type, value)
    existing = day_plans_repo.get_day_plan(conn, study_day)
    day_plans_repo.upsert_day_plan(
        conn,
        local_date=study_day,
        study_goal_secs=existing["study_goal_secs"] if existing else None,
        exam_goal_type=goal_type,
        exam_goal_value=value,
        is_rest_day=is_rest_day,
        notes=existing["notes"] if existing else "",
        updated_at_utc=now_utc,
    )


def set_weekday_exam_goal(
    conn: sqlite3.Connection,
    weekday: int,
    *,
    goal_type: str,
    value: int,
) -> None:
    if not 0 <= weekday <= 6:
        raise ValidationError("Weekday must be between 0 (Monday) and 6 (Sunday).")
    _validate_goal(goal_type, value)
    current = day_plans_repo.get_weekday_default(conn, weekday)
    day_plans_repo.upsert_weekday_default(
        conn,
        weekday=weekday,
        study_goal_secs=current["study_goal_secs"] if current else 0,
        exam_goal_type=goal_type,
        exam_goal_value=value,
    )


def exam_goal_progress(conn: sqlite3.Connection, study_day: str) -> ExamGoalProgress:
    goal = get_exam_goal(conn, study_day)
    exams = get_exams(conn, date_from=study_day, date_to=study_day, status="completed")
    if goal.goal_type == "count":
        completed = len(exams)
    elif goal.goal_type == "minutes":
        completed = sum(exam.taken_seconds or 0 for exam in exams) // 60
    elif goal.goal_type == "questions":
        completed = sum(
            (part.correct or 0) + (part.incorrect or 0)
            for exam in exams
            for part in exam.parts
            if part.kind == "mcq"
        )
    else:
        completed = 0
    return ExamGoalProgress(goal, completed)


def _validate_goal(goal_type: str, value: int) -> None:
    if goal_type not in _GOAL_TYPES:
        raise ValidationError("Exam goal type must be none, count, minutes, or questions.")
    if value < 0:
        raise ValidationError("Exam goal cannot be negative.")
    if goal_type == "none" and value != 0:
        raise ValidationError("A disabled exam goal must have a value of zero.")
