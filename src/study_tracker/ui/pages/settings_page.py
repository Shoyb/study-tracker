"""Settings and data-ownership controls."""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from study_tracker import __version__
from study_tracker.core import paths
from study_tracker.core.errors import AppError
from study_tracker.db import settings_repo
from study_tracker.services.backup_service import backup_report, create_backup
from study_tracker.services.export_service import (
    export_daily_by_subject,
    export_daily_totals,
    export_sessions,
    export_subject_summary,
    export_tasks,
)
from study_tracker.services.import_service import (
    commit_sessions,
    commit_tasks,
    preview_sessions,
    preview_tasks,
)
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.confirm import alert, confirm, warn


class SettingsPage(QWidget):
    """Data path, backup, restore, export and import actions."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        signals: AppSignals,
        clock,
        on_restore: Callable[[Path], None] | None = None,
        database_path: Path | None = None,
        log_path: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._signals = signals
        self._clock = clock
        self._on_restore = on_restore
        self._database_path = database_path
        self._log_path = log_path
        self._build_ui()

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.addWidget(QLabel("<h2>Settings & Data</h2>"))

        form = QFormLayout()
        self._data_path = QLabel(str(self._database_path or "Connected database"))
        self._data_path.setWordWrap(True)
        form.addRow("Database:", self._data_path)
        self._theme = QComboBox()
        self._theme.addItem("Light", "light")
        self._theme.addItem("Dark", "dark")
        theme_index = self._theme.findData(settings_repo.get(self._conn, "theme") or "light")
        self._theme.setCurrentIndex(max(0, theme_index))
        self._theme.currentIndexChanged.connect(self._save_theme)
        form.addRow("Theme:", self._theme)
        self._copies = QSpinBox()
        self._copies.setRange(1, 100)
        self._copies.setValue(int(settings_repo.get(self._conn, "backup_copies") or "10"))
        self._copies.valueChanged.connect(self._save_backup_copies)
        form.addRow("Automatic copies kept:", self._copies)
        form.addRow("Version:", QLabel(__version__))
        form.addRow("Log file:", QLabel(str(self._log_path or "Application log")))
        root.addLayout(form)

        backup_row = QHBoxLayout()
        backup_row.addWidget(self._button("Back up now", self._backup))
        backup_row.addWidget(self._button("Validate backup…", self._validate_backup))
        backup_row.addWidget(self._button("Restore backup…", self._restore))
        backup_row.addStretch()
        root.addLayout(backup_row)

        root.addWidget(
            QLabel(
                "<h3>CSV export</h3><p>Exports use UTF-8 so Excel keeps "
                "non-English text intact.</p>"
            )
        )
        export_row = QHBoxLayout()
        export_row.addWidget(self._button("Export sessions", self._export_sessions))
        export_row.addWidget(self._button("Export tasks", self._export_tasks))
        export_row.addWidget(self._button("Export daily totals", self._export_daily))
        export_row.addWidget(self._button("Export subject summary", self._export_subjects))
        export_row.addStretch()
        root.addLayout(export_row)

        import_row = QHBoxLayout()
        import_row.addWidget(QLabel("<h3>CSV import</h3>"))
        import_row.addWidget(self._button("Import tasks or sessions…", self._import_csv))
        import_row.addStretch()
        root.addLayout(import_row)
        self._message = QLabel()
        self._message.setWordWrap(True)
        root.addWidget(self._message)
        root.addStretch()

    def _save_backup_copies(self, value: int) -> None:
        settings_repo.set_value(self._conn, "backup_copies", str(value))
        self._signals.settings_changed.emit()

    def _save_theme(self) -> None:
        settings_repo.set_value(self._conn, "theme", self._theme.currentData())
        self._signals.settings_changed.emit()

    def _choose_directory(self, title: str) -> Path | None:
        chosen = QFileDialog.getExistingDirectory(self, title, str(paths.data_dir()))
        return Path(chosen) if chosen else None

    def _backup(self) -> None:
        directory = self._choose_directory("Choose backup folder")
        if directory is None:
            return
        try:
            path = create_backup(self._conn, directory)
            self._message.setText(f"Backup created: {path}")
        except AppError as exc:
            warn(self, "Backup failed", str(exc))

    def _validate_backup(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose backup", str(paths.backup_dir()), "SQLite (*.db)"
        )
        if not filename:
            return
        report = backup_report(Path(filename))
        message = (
            f"{report.message}\nSchema version: {report.user_version}\n"
            f"Subjects: {report.subjects}, Tasks: {report.tasks}, Sessions: {report.sessions}"
        )
        (alert if report.ok else warn)(self, "Backup validation", message)

    def _restore(self) -> None:
        if self._on_restore is None:
            warn(self, "Restore unavailable", "Restart the application before restoring a backup.")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose backup to restore", str(paths.backup_dir()), "SQLite (*.db)"
        )
        if not filename:
            return
        report = backup_report(Path(filename))
        if not report.ok:
            warn(self, "Cannot restore", report.message)
            return
        if not confirm(
            self,
            "Restore backup",
            f"Replace the current database with this backup ({report.sessions} sessions)?",
            "A safety backup of the current database will be made first.",
        ):
            return
        try:
            self._on_restore(Path(filename))
        except AppError as exc:
            warn(self, "Restore failed", str(exc))

    def _range(self) -> tuple[str, str]:
        end = date.fromisoformat(self._clock.local_date())
        return (end - timedelta(days=29)).isoformat(), end.isoformat()

    def _export_path(self, filename: str) -> Path | None:
        directory = self._choose_directory("Choose export folder")
        return directory / filename if directory else None

    def _run_export(self, filename: str, exporter) -> None:
        path = self._export_path(filename)
        if path is None:
            return
        try:
            exporter(path)
            self._message.setText(f"Exported: {path}")
        except FileExistsError:
            warn(self, "Export exists", f"Choose another folder or remove {path.name} first.")
        except OSError as exc:
            warn(self, "Export failed", str(exc))

    def _export_sessions(self) -> None:
        start, end = self._range()
        self._run_export(
            "sessions.csv",
            lambda path: export_sessions(self._conn, path, date_from=start, date_to=end),
        )

    def _export_tasks(self) -> None:
        self._run_export("tasks.csv", lambda path: export_tasks(self._conn, path))

    def _export_daily(self) -> None:
        start, end = self._range()
        self._run_export(
            "daily_totals.csv",
            lambda path: export_daily_totals(self._conn, path, date_from=start, date_to=end),
        )

    def _export_subjects(self) -> None:
        start, end = self._range()
        path = self._export_path("subject_summary.csv")
        if path is None:
            return
        try:
            export_subject_summary(self._conn, path, date_from=start, date_to=end)
            export_daily_by_subject(
                self._conn, path.with_name("daily_by_subject.csv"), date_from=start, date_to=end
            )
            self._message.setText(f"Exported: {path.parent}")
        except (FileExistsError, OSError) as exc:
            warn(self, "Export failed", str(exc))

    def _import_csv(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import Study Tracker CSV", "", "CSV (*.csv)"
        )
        if not filename:
            return
        path = Path(filename)
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                headers = set(next(csv.reader(stream)))
            sessions = "session_uuid" in headers
            preview = (
                preview_sessions(self._conn, path) if sessions else preview_tasks(self._conn, path)
            )
            summary = (
                f"{preview.total} rows: {preview.new} new, {preview.duplicates} duplicates, "
                f"{len(preview.errors)} rejected."
            )
            if preview.exact_file_seen:
                alert(self, "Import", "This exact file was already imported; no rows were changed.")
                return
            if preview.errors:
                warn(self, "Import preview", summary + "\n\n" + "\n".join(preview.errors[:5]))
            if preview.new and confirm(self, "Import CSV", summary + "\nImport valid rows?"):
                if sessions:
                    count = commit_sessions(self._conn, path, preview, self._clock.now_utc())
                    self._signals.sessions_changed.emit()
                else:
                    count = commit_tasks(self._conn, path, preview, self._clock.now_utc())
                    self._signals.tasks_changed.emit()
                self._message.setText(f"Imported {count} row(s) from {path.name}.")
        except (AppError, OSError, ValueError, StopIteration) as exc:
            warn(self, "Import failed", str(exc))
