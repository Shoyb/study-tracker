"""Baseline hour calculations and alert states."""

from __future__ import annotations


def required_minutes_for_day(target_minutes: int, *, overhead_percent: int = 20) -> int:
    """Return the total minutes needed, including the configured break overhead."""
    return int(target_minutes * (1 + overhead_percent / 100))


def alert_level(slack_minutes: int, *, margins: tuple[int, int, int] = (120, 60, 20)) -> str:
    """Return the current alert state for a missing-hours slack value."""
    heads_up, warning, urgent = margins
    if slack_minutes < 0:
        return "critical"
    if slack_minutes <= urgent:
        return "urgent"
    if slack_minutes <= warning:
        return "warning"
    if slack_minutes <= heads_up:
        return "headsup"
    return "ok"
