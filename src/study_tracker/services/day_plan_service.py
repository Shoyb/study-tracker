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
