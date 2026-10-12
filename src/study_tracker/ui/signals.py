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

    # Settings were changed (week start, theme, streak threshold, etc.).
    settings_changed = Signal()

    # The calendar date has rolled over midnight.
    day_changed = Signal()

    # The running timer tick (emitted every second while a timer is running).
    timer_tick = Signal()
