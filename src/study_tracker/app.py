"""Top-level QApplication and startup sequence.

Responsibilities:
1. Enforce single-instance using a lock file.
2. Configure logging.
3. Load the stylesheet.
4. Open (or create) the database (migrate + quick_check + auto-backup).
5. Show the main window.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from study_tracker.core import paths
from study_tracker.core.clock import Clock
from study_tracker.core.errors import DatabaseError
from study_tracker.core.logging_setup import configure_logging
from study_tracker.db.connection import get_connection, quick_check
from study_tracker.db.migrate import log_row_counts, run_migrations
from study_tracker.services.backup_service import (
    create_backup,
    list_backups,
    prune_backups,
    restore_backup,
)
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


def _load_stylesheet(app: QApplication, theme: str = "light") -> None:
    """Load a bundled stylesheet without depending on the working directory."""
    selected = theme if theme in {"light", "dark"} else "light"
    qss_path = paths.theme_dir() / f"{selected}.qss"
    if qss_path.exists():
        with open(qss_path, encoding="utf-8") as fh:
            app.setStyleSheet(fh.read())
        log.debug("%s stylesheet loaded from %s.", selected, qss_path)
    else:
        log.warning("Stylesheet not found at %s.", qss_path)


def _open_database() -> sqlite3.Connection:
    """Open, migrate and integrity-check the database.

    If the database file is missing but backups exist, logs a warning and
    returns a fresh database (the UI will offer a restore dialog in a later
    milestone).
    """
    db_path = paths.db_path()
    backup_dir = paths.backup_dir()

    if not db_path.exists() and list_backups(backup_dir):
        log.warning(
            "Database not found at %s but %d backup(s) exist in %s. "
            "Starting fresh – use Settings > Restore to recover data.",
            db_path,
            len(list_backups(backup_dir)),
            backup_dir,
        )

    conn = get_connection(db_path)
    run_migrations(conn, db_path)

    from study_tracker.db import settings_repo
    from study_tracker.services.undo.journal import JournalService

    JournalService(conn).purge(
        Clock().now_utc(),
        keep_entries=int(settings_repo.get(conn, "undo_keep_entries") or "500"),
        keep_days=int(settings_repo.get(conn, "undo_keep_days") or "30"),
    )

    if not quick_check(conn):
        raise DatabaseError(
            f"Database integrity check failed: {db_path}\n"
            "Try restoring from a backup via Settings > Data."
        )

    log_row_counts(conn)
    log.info("Database opened: %s", db_path)
    return conn


def _auto_backup(conn: sqlite3.Connection) -> None:
    """Create a daily automatic backup and prune old ones."""
    settings_val = None
    try:
        from study_tracker.db import settings_repo
        settings_val = settings_repo.get(conn, "auto_backup")
    except Exception:
        pass

    if settings_val == "0":
        return

    try:
        keep_str = None
        try:
            from study_tracker.db import settings_repo

            keep_str = settings_repo.get(conn, "backup_copies")
        except Exception:
            pass
        keep = int(keep_str or "10")

        backup_dir = paths.backup_dir()
        create_backup(conn, backup_dir)
        prune_backups(backup_dir, keep=keep)
    except Exception as exc:
        log.warning("Auto-backup failed (non-fatal): %s", exc)


class Application(QApplication):
    """Subclass of QApplication that owns the startup sequence."""

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.setApplicationName("Study Tracker")
        self.setApplicationVersion("0.1.0")
        self.setOrganizationName("StudyTracker")

        # 1. Logging (before anything else so errors are recorded).
        configure_logging(paths.log_path())
        log.info("Study Tracker starting. Data dir: %s", paths.data_dir())

        # 2. Single-instance check.
        if not _acquire_lock():
            QMessageBox.warning(
                None,  # type: ignore[arg-type]
                "Already running",
                "Study Tracker is already open.\nCheck the system tray or the taskbar.",
            )
            sys.exit(0)

        # 3. Database.
        try:
            self._conn = _open_database()
            _auto_backup(self._conn)
        except DatabaseError as exc:
            QMessageBox.critical(
                None,  # type: ignore[arg-type]
                "Database error",
                str(exc),
            )
            sys.exit(1)

        # 4. Theme, signals hub, and clock.
        from study_tracker.db import settings_repo

        self.setWindowIcon(QIcon(str(paths.icon_path())))
        _load_stylesheet(self, settings_repo.get(self._conn, "theme") or "dark")
        self._signals = AppSignals(self)
        self._signals.settings_changed.connect(self._apply_saved_theme)
        self._clock = Clock(
            cutoff_minutes=int(settings_repo.get(self._conn, "day_cutoff_minutes") or "180")
        )
        self._apply_saved_theme()

        # 5. Main window.
        self._window = MainWindow(
            self._signals,
            conn=self._conn,
            clock=self._clock,
            on_restore=self._restore_database,
            database_path=paths.db_path(),
            log_path=paths.log_path(),
        )
        self._window.show()

        log.info("Startup complete.")

    def _apply_saved_theme(self) -> None:
        from study_tracker.db import settings_repo

        _load_stylesheet(self, settings_repo.get(self._conn, "theme") or "dark")

    def _restore_database(self, backup_path) -> None:
        """Safety-back up, replace, reopen, and rebuild pages using the new database."""
        from study_tracker.db import settings_repo

        create_backup(self._conn, paths.backup_dir())
        self._conn.close()
        try:
            restore_backup(backup_path, paths.db_path())
            self._conn = _open_database()
        except Exception:
            self._conn = _open_database()
            raise
        self._window.close()
        self._signals = AppSignals(self)
        self._signals.settings_changed.connect(self._apply_saved_theme)
        self._clock = Clock(
            cutoff_minutes=int(settings_repo.get(self._conn, "day_cutoff_minutes") or "180")
        )
        self._apply_saved_theme()
        self._window = MainWindow(
            self._signals,
            conn=self._conn,
            clock=self._clock,
            on_restore=self._restore_database,
            database_path=paths.db_path(),
            log_path=paths.log_path(),
        )
        self._window.show()
