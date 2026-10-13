"""Baseline-hours progress and one-time alert scheduling."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from study_tracker.db import day_plans_repo, sessions_repo, settings_repo
from study_tracker.domain.allocation import allocate_by_day
from study_tracker.domain.baseline import alert_level, required_minutes_for_day
from study_tracker.domain.day import day_bounds, study_date
from study_tracker.services.day_plan_service import get_study_goal_seconds


@dataclass(frozen=True)
class BaselineAlert:
    study_day: str
    level: str
    studied_seconds: int
    target_seconds: int
    slack_minutes: int
    message: str


class AlertService:
    def __init__(self, conn: sqlite3.Connection, clock) -> None:
        self._conn = conn
        self._clock = clock

    def evaluate(self) -> BaselineAlert | None:
        if settings_repo.get(self._conn, "baseline_alerts_enabled") == "0":
            return None

        cutoff = int(settings_repo.get(self._conn, "day_cutoff_minutes") or "180")
        local_now = self._clock.local_datetime()
        study_day = study_date(local_now, cutoff)
        goal_seconds = get_study_goal_seconds(self._conn, study_day)
        plan = day_plans_repo.get_day_plan(self._conn, study_day)
        if goal_seconds <= 0 or (plan is not None and plan["is_rest_day"]):
            return None

        start_date = (date.fromisoformat(study_day) - timedelta(days=1)).isoformat()
        sessions = sessions_repo.get_all(self._conn, date_from=start_date, date_to=study_day)
        studied_seconds = sum(
            allocate_by_day(session, cutoff).get(study_day, 0) for session in sessions
        )
        wake_minutes = int(settings_repo.get(self._conn, "wake_minutes") or "420")
        wake = datetime.combine(date.fromisoformat(study_day), time.min) + timedelta(
            minutes=wake_minutes
        )
        _, day_end = day_bounds(study_day, cutoff)
        available_start = max(local_now, wake)
        available_seconds = max(0, int((day_end - available_start).total_seconds()))
        remaining_seconds = max(0, goal_seconds - studied_seconds)
        overhead = int(settings_repo.get(self._conn, "break_overhead_percent") or "20")
        needed_minutes = required_minutes_for_day(
            (remaining_seconds + 59) // 60, overhead_percent=overhead
        )
        slack_minutes = available_seconds // 60 - needed_minutes
        level = alert_level(slack_minutes, margins=self._alert_margins())
        if level == "ok":
            return None

        now_utc = self._clock.now_utc()
        if not day_plans_repo.record_alert(
            self._conn,
            local_date=study_day,
            alert_key=level,
            fired_at_utc=now_utc,
        ):
            return None
        message = (
            "Today's study goal is no longer reachable at the current pace."
            if level == "critical"
            else f"Study goal slack is {slack_minutes} minutes."
        )
        return BaselineAlert(
            study_day=study_day,
            level=level,
            studied_seconds=studied_seconds,
            target_seconds=goal_seconds,
            slack_minutes=slack_minutes,
            message=message,
        )

    def _alert_margins(self) -> tuple[int, int, int]:
        value = settings_repo.get(self._conn, "alert_margins_minutes") or "120,60,20"
        try:
            margins = tuple(int(part.strip()) for part in value.split(","))
        except ValueError:
            margins = ()
        if len(margins) != 3 or not margins[0] >= margins[1] >= margins[2] >= 0:
            return 120, 60, 20
        return margins
