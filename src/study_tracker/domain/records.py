"""Personal record detection."""

from __future__ import annotations


def record_values(values: list[int]) -> list[int]:
    """Return the running record at each point in time."""
    running: list[int] = []
    best = None
    for value in values:
        if best is None or value > best:
            best = value
        running.append(best)
    return running


def is_record(candidate: int, previous_values: list[int]) -> bool:
    """Return True when the candidate is a new personal best."""
    return candidate > max(previous_values, default=float("-inf"))
