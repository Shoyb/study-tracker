"""Application-wide Qt signals.

A single ``AppSignals`` instance is created in ``app.py`` and passed down to
every service and page that needs it.  Pages subscribe to whichever signals
are relevant and refresh themselves when they fire.

Using a single object instead of many separate signals makes wiring simple:
each page receives the whole ``AppSignals`` and calls ``.connect()`` on the
ones it cares about.
"""

from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    """All application-level change notifications."""

    # A session was added, edited or deleted.
    sessions_changed = Signal()

    # A task was added, edited, completed, archived or deleted.
    tasks_changed = Signal()

    # A subject was added, renamed, recoloured, reordered, archived or deleted.
    subjects_changed = Signal()

    # Calendar items or scheduled dates changed.
    calendar_changed = Signal()

    # Exam results, plans, or lookup lists changed.
    exam_changed = Signal()

    # Settings were changed (week start, theme, streak threshold, etc.).
    settings_changed = Signal()

    # The calendar date has rolled over midnight.
    day_changed = Signal()

    # The running timer tick (emitted every tick while a timer is running).
    timer_tick = Signal()

    # Emitted when timer starts, pauses, resumes, stops, or is recovered/discarded.
    timer_state_changed = Signal()

    # Pomodoro phase changes for in-app and tray notifications.
    pomodoro_phase_changed = Signal(str)
