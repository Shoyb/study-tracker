"""Pure pomodoro state handling."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PomodoroState:
    phase: str
    remaining_seconds: int
    completed_cycles: int = 0


def advance_phase(
    state: PomodoroState,
    *,
    preset_minutes: int = 25,
    short_break_minutes: int = 5,
    long_break_minutes: int = 15,
    cycles_before_long_break: int = 4,
    focus_seconds: int | None = None,
    short_break_seconds: int | None = None,
    long_break_seconds: int | None = None,
) -> PomodoroState:
    """Return the next phase in the copied Pomodoro preset cycle."""
    if state.phase == "focus":
        completed = state.completed_cycles + 1
        long_break = completed % max(1, cycles_before_long_break) == 0
        return PomodoroState(
            phase="long_break" if long_break else "short_break",
            remaining_seconds=(
                long_break_seconds
                if long_break and long_break_seconds is not None
                else short_break_seconds
                if not long_break and short_break_seconds is not None
                else (long_break_minutes if long_break else short_break_minutes) * 60
            ),
            completed_cycles=completed,
        )
    return PomodoroState(
        phase="focus",
        remaining_seconds=focus_seconds if focus_seconds is not None else preset_minutes * 60,
        completed_cycles=state.completed_cycles,
    )
