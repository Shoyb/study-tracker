"""Domain validation rules.

Pure functions – no Qt, no SQL, no side-effects.
"""

from __future__ import annotations

from study_tracker.core.errors import ValidationError

# ── Subject rules ─────────────────────────────────────────────────────────────

SUBJECT_NAME_MAX = 60
SUBJECT_COLOUR_REGEX = r"^#[0-9A-Fa-f]{6}$"

# The seed subject name that cannot be modified.
_PROTECTED_NAMES: frozenset[str] = frozenset()  # extended per project needs


def validate_subject_name(name: str) -> str:
    """Strip and validate a subject name.  Returns the cleaned name."""
    name = name.strip()
    if not name:
        raise ValidationError("Subject name cannot be empty.")
    if len(name) > SUBJECT_NAME_MAX:
        raise ValidationError(
            f"Subject name is too long ({len(name)} chars, max {SUBJECT_NAME_MAX})."
        )
    return name


def validate_subject_colour(colour: str) -> str:
    """Validate a CSS hex colour string like ``#1976D2``."""
    import re

    colour = colour.strip()
    if not re.fullmatch(SUBJECT_COLOUR_REGEX, colour):
        raise ValidationError(
            f"Invalid colour '{colour}'. Expected a hex string like #1976D2."
        )
    return colour


# ── Task rules ────────────────────────────────────────────────────────────────

TASK_TITLE_MAX = 200
VALID_STATUSES = ("todo", "in_progress", "done")
VALID_PRIORITIES = ("low", "medium", "high")


def validate_task_title(title: str) -> str:
    title = title.strip()
    if not title:
        raise ValidationError("Task title cannot be empty.")
    if len(title) > TASK_TITLE_MAX:
        raise ValidationError(
            f"Task title is too long ({len(title)} chars, max {TASK_TITLE_MAX})."
        )
    return title


def validate_task_status(status: str) -> str:
    if status not in VALID_STATUSES:
        raise ValidationError(
            f"Invalid status '{status}'. Must be one of: {', '.join(VALID_STATUSES)}."
        )
    return status


def validate_task_priority(priority: str) -> str:
    if priority not in VALID_PRIORITIES:
        raise ValidationError(
            f"Invalid priority '{priority}'. Must be one of: {', '.join(VALID_PRIORITIES)}."
        )
    return priority


# ── Session rules ─────────────────────────────────────────────────────────────

VALID_SESSION_TYPES = ("timer", "manual_timed", "manual_duration", "device")
MAX_SESSION_SECS = 86400  # 24 hours


def validate_duration_secs(secs: int) -> int:
    if secs <= 0:
        raise ValidationError("Session duration must be greater than zero.")
    if secs > MAX_SESSION_SECS:
        raise ValidationError("Session duration cannot exceed 24 hours (86,400 seconds).")
    return secs


def validate_session_times(
    start_utc: str,
    end_utc: str,
    now_utc: str | None = None,
) -> None:
    if end_utc <= start_utc:
        raise ValidationError("Session end time must be after start time.")
    if now_utc and start_utc > now_utc:
        raise ValidationError("Session start time cannot be in the future.")


def validate_session_type(session_type: str) -> str:
    if session_type not in VALID_SESSION_TYPES:
        raise ValidationError(f"Invalid session type: {session_type!r}.")
    return session_type
