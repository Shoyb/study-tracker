"""Read-only personal records derived from study and exam history."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from study_tracker.db import sessions_repo, settings_repo
from study_tracker.domain import stats
from study_tracker.services.exam_service import get_exams, score


@dataclass(frozen=True)
class PersonalRecord:
    key: str
    title: str
    value: int | Decimal
    period: str
    detail: str = ""


def get_personal_records(conn: sqlite3.Connection) -> list[PersonalRecord]:
    sessions = sessions_repo.get_all(conn)
    records: list[PersonalRecord] = []
    if sessions:
        cutoff = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")
        first = min(date.fromisoformat(item.local_date) for item in sessions)
        last = max(date.fromisoformat(item.local_date) for item in sessions) + timedelta(days=1)
        daily = stats.daily_totals(sessions, first.isoformat(), last.isoformat(), cutoff)
        _append_highest(
            records,
            "study_day",
            "Most study in one day",
            ((day, value) for day, value in daily.items() if value > 0),
        )
        week_start = settings_repo.get(conn, "week_start") or "monday"
        _append_highest(
            records,
            "study_week",
            "Most study in one week",
            stats.weekly_totals(daily, week_start).items(),
        )
        monthly: dict[str, int] = {}
        for day, value in daily.items():
            month = day[:7]
            monthly[month] = monthly.get(month, 0) + value
        _append_highest(
            records,
            "study_month",
            "Most study in one month",
            monthly.items(),
        )

        threshold_hours = float(settings_repo.get(conn, "streak_threshold_hrs") or "0.5")
        threshold_seconds = round(threshold_hours * 3600)
        streak_length, streak_period = _longest_streak_period(daily, threshold_seconds)
        if streak_length:
            records.append(
                PersonalRecord(
                    "longest_streak",
                    "Longest study streak",
                    streak_length,
                    streak_period,
                )
            )

        pomodoros: dict[str, int] = {}
        for session in sessions:
            if session.pomodoro_completed:
                pomodoros[session.local_date] = pomodoros.get(session.local_date, 0) + 1
        _append_highest(
            records,
            "pomodoros_day",
            "Most completed Pomodoros in one day",
            pomodoros.items(),
        )

    best_exam = None
    best_accuracy: Decimal | None = None
    for exam in sorted(
        get_exams(conn, status="completed"), key=lambda item: (item.exam_date, item.id)
    ):
        result = score(exam)
        if (
            result is not None
            and result.net_accuracy is not None
            and (best_accuracy is None or result.net_accuracy > best_accuracy)
        ):
            best_exam = exam
            best_accuracy = result.net_accuracy
    if best_exam is not None and best_accuracy is not None:
        records.append(
            PersonalRecord(
                "exam_accuracy",
                "Highest exam net accuracy",
                best_accuracy,
                best_exam.exam_date,
                best_exam.title,
            )
        )
    return records


def _append_highest(
    records: list[PersonalRecord],
    key: str,
    title: str,
    values,
) -> None:
    best_period = None
    best_value = 0
    for period, value in sorted(values):
        if value > best_value:
            best_period = period
            best_value = value
    if best_period is not None:
        records.append(PersonalRecord(key, title, best_value, best_period))


def _longest_streak_period(daily: dict[str, int], threshold_seconds: int) -> tuple[int, str]:
    best_length = 0
    current_length = 0
    current_start = ""
    best_period = ""
    previous_day: date | None = None
    for day_text, seconds in sorted(daily.items()):
        current_day = date.fromisoformat(day_text)
        if seconds >= threshold_seconds:
            if previous_day is None or current_day != previous_day + timedelta(days=1):
                current_length = 0
                current_start = day_text
            current_length += 1
            if current_length > best_length:
                best_length = current_length
                best_period = f"{current_start} to {day_text}"
        else:
            current_length = 0
        previous_day = current_day
    return best_length, best_period
