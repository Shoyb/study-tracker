"""Resolve the application's data folder and derived paths.

Priority:
1. ``STUDY_TRACKER_HOME`` environment variable (used for tests and portable mode).
2. ``%LOCALAPPDATA%\\StudyTracker`` on Windows.
3. ``~/.local/share/StudyTracker`` on other systems (fallback).

All paths returned are absolute and resolved, so the app's behaviour is
identical regardless of the current working directory.
"""

import os
import pathlib
import sys


def _default_data_dir() -> pathlib.Path:
    """Return the platform default data directory (not yet created)."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return pathlib.Path(local_app_data) / "StudyTracker"
    return pathlib.Path.home() / ".local" / "share" / "StudyTracker"


def data_dir() -> pathlib.Path:
    """Return the resolved, absolute data directory.

    If the directory does not exist it is created (with parents).
    """
    override = os.environ.get("STUDY_TRACKER_HOME")
    base = pathlib.Path(override).resolve() if override else _default_data_dir().resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> pathlib.Path:
    """Absolute path to the SQLite database file."""
    return data_dir() / "study_tracker.db"


def log_path() -> pathlib.Path:
    """Absolute path to the application log file."""
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "study_tracker.log"


def backup_dir() -> pathlib.Path:
    """Directory where automatic and manual backups are stored."""
    d = data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock_path() -> pathlib.Path:
    """Path to the single-instance lock file."""
    return data_dir() / "study_tracker.lock"


def theme_dir() -> pathlib.Path:
    """Directory containing QSS stylesheet files (inside the package)."""
    return pathlib.Path(__file__).parent.parent / "ui" / "theme"
