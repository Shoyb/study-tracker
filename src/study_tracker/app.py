"""Top-level QApplication and startup sequence.

Responsibilities:
1. Enforce single-instance using a lock file.
2. Configure logging.
3. Load the stylesheet.
4. Open (or create) the database.
5. Show the main window.
"""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from study_tracker.core import paths
from study_tracker.core.logging_setup import configure_logging
from study_tracker.ui.main_window import MainWindow
from study_tracker.ui.signals import AppSignals

log = logging.getLogger(__name__)

_LOCK_FD: int | None = None  # keeps the lock file descriptor alive


def _acquire_lock() -> bool:
    """Try to acquire the single-instance lock.  Returns ``True`` on success."""
    global _LOCK_FD  # noqa: PLW0603
    lock = paths.lock_path()
    try:
        if sys.platform == "win32":
            import msvcrt

            _LOCK_FD = os.open(str(lock), os.O_CREAT | os.O_RDWR)
            try:
                msvcrt.locking(_LOCK_FD, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                os.close(_LOCK_FD)
                _LOCK_FD = None
                return False
        else:
            import fcntl

            _LOCK_FD = os.open(str(lock), os.O_CREAT | os.O_RDWR)
            try:
                fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                os.close(_LOCK_FD)
                _LOCK_FD = None
                return False
    except Exception as exc:
        log.warning("Could not create lock file: %s", exc)
        return True  # Fail open rather than refusing to start.


def _load_stylesheet(app: QApplication) -> None:
    """Load the light theme QSS from the package."""
    qss_path = paths.theme_dir() / "light.qss"
    if qss_path.exists():
        with open(qss_path, encoding="utf-8") as fh:
            app.setStyleSheet(fh.read())
        log.debug("Stylesheet loaded from %s.", qss_path)
    else:
        log.warning("Stylesheet not found at %s.", qss_path)


class Application(QApplication):
    """Subclass of QApplication that owns the startup sequence."""

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.setApplicationName("Study Tracker")
        self.setApplicationVersion("0.1.0")
        self.setOrganizationName("StudyTracker")

        # 1. Logging (before anything else so errors are recorded).
        configure_logging(paths.log_path())
        log.info(
            "Study Tracker starting. Data dir: %s", paths.data_dir()
        )

        # 2. Single-instance check.
        if not _acquire_lock():
            # Show a message box even before the main window exists.
            QMessageBox.warning(
                None,  # type: ignore[arg-type]
                "Already running",
                "Study Tracker is already open.\n"
                "Check the system tray or the taskbar.",
            )
            sys.exit(0)

        # 3. Stylesheet.
        _load_stylesheet(self)

        # 4. Signals hub.
        self._signals = AppSignals(self)

        # 5. Main window.
        self._window = MainWindow(self._signals)
        self._window.show()

        log.info("Startup complete.")
