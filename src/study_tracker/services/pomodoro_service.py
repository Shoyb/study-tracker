"""Pomodoro preset validation and shared-timer orchestration."""

from __future__ import annotations

import sqlite3

from study_tracker.core.errors import NotFoundError, ValidationError
from study_tracker.db import pomodoro_repo
from study_tracker.services.timer_service import TimerService


class PomodoroService:
    def __init__(self, conn: sqlite3.Connection, timer: TimerService | None = None) -> None:
        self._conn = conn
        self._timer = timer

    def presets(self) -> list[pomodoro_repo.PomodoroPreset]:
        return pomodoro_repo.get_presets(self._conn)

    def create_preset(
        self,
        *,
        name: str,
        focus_seconds: int,
        short_break_seconds: int,
        long_break_seconds: int,
        cycles_before_long_break: int,
        auto_start_break: bool = True,
        auto_start_focus: bool = False,
    ) -> pomodoro_repo.PomodoroPreset:
        self._validate_preset(
            name, focus_seconds, short_break_seconds, long_break_seconds, cycles_before_long_break
        )
        return pomodoro_repo.create_preset(
            self._conn,
            name=name,
            focus_seconds=focus_seconds,
            short_break_seconds=short_break_seconds,
            long_break_seconds=long_break_seconds,
            cycles_before_long_break=cycles_before_long_break,
            auto_start_break=auto_start_break,
            auto_start_focus=auto_start_focus,
        )

    def start(self, preset_id: int, *, subject_id: int, task_id: int | None, notes: str) -> None:
        if self._timer is None:
            raise RuntimeError("A timer service is required to start Pomodoro.")
        preset = pomodoro_repo.get_preset_by_id(self._conn, preset_id)
        if preset is None:
            raise NotFoundError(f"Pomodoro preset {preset_id} not found.")
        self._timer.start_pomodoro(subject_id, task_id, notes, preset)

    def update_preset(
        self,
        preset_id: int,
        *,
        name: str,
        focus_seconds: int,
        short_break_seconds: int,
        long_break_seconds: int,
        cycles_before_long_break: int,
        auto_start_break: bool,
        auto_start_focus: bool,
    ) -> None:
        self._validate_preset(
            name, focus_seconds, short_break_seconds, long_break_seconds, cycles_before_long_break
        )
        if pomodoro_repo.get_preset_by_id(self._conn, preset_id) is None:
            raise NotFoundError(f"Pomodoro preset {preset_id} not found.")
        pomodoro_repo.update_preset(
            self._conn,
            preset_id,
            name=name,
            focus_seconds=focus_seconds,
            short_break_seconds=short_break_seconds,
            long_break_seconds=long_break_seconds,
            cycles_before_long_break=cycles_before_long_break,
            auto_start_break=auto_start_break,
            auto_start_focus=auto_start_focus,
        )

    @staticmethod
    def _validate_preset(
        name: str,
        focus_seconds: int,
        short_break_seconds: int,
        long_break_seconds: int,
        cycles_before_long_break: int,
    ) -> None:
        if not name.strip() or len(name.strip()) > 40:
            raise ValidationError("Preset name must be between 1 and 40 characters.")
        if not 60 <= focus_seconds <= 10800:
            raise ValidationError("Focus length must be between 1 minute and 3 hours.")
        if not 0 <= short_break_seconds <= 3600:
            raise ValidationError("Short break must be between 0 and 60 minutes.")
        if not 0 <= long_break_seconds <= 7200:
            raise ValidationError("Long break must be between 0 and 120 minutes.")
        if not 1 <= cycles_before_long_break <= 12:
            raise ValidationError("Long break cycle must be between 1 and 12 focus periods.")
