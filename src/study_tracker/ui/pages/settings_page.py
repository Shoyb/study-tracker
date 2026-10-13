"""Settings and data-ownership controls."""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from study_tracker import __version__
from study_tracker.core import paths
from study_tracker.core.errors import AppError
from study_tracker.db import exams_repo, settings_repo
from study_tracker.services import day_plan_service, subject_daily_goal_service, subject_service
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
from study_tracker.services.pomodoro_service import PomodoroService
from study_tracker.services.settings_service import change_study_day_cutoff
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
        self._signals.subjects_changed.connect(self._reload_subject_daily_goal_subjects)

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def _section_heading(self, text: str) -> QLabel:
        heading = QLabel(text)
        heading.setStyleSheet("font-size: 12pt; font-weight: 600; padding-top: 12px;")
        return heading

    def _build_ui(self) -> None:
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        self._scroll_area = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        scroll.setWidget(content)
        page_layout.addWidget(scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(24, 24, 24, 24)
        root.addWidget(QLabel("<h2>Settings & Data</h2>"))

        form = QFormLayout()
        form.addRow(self._section_heading("General"))
        self._data_path = QLabel(str(self._database_path or "Connected database"))
        self._data_path.setWordWrap(True)
        form.addRow("Database:", self._data_path)
        cutoff_row = QHBoxLayout()
        cutoff_minutes = int(settings_repo.get(self._conn, "day_cutoff_minutes") or "180")
        self._cutoff_time = QTimeEdit(QTime(cutoff_minutes // 60, cutoff_minutes % 60))
        self._cutoff_time.setDisplayFormat("HH:mm")
        cutoff_row.addWidget(self._cutoff_time)
        cutoff_row.addWidget(self._button("Apply cutoff", self._change_cutoff))
        cutoff_row.addStretch()
        form.addRow("Study day ends at:", cutoff_row)
        form.addRow(self._section_heading("Study goals and alerts"))
        self._baseline_alerts = QCheckBox("Enable baseline study-goal alerts")
        self._baseline_alerts.setChecked(
            settings_repo.get(self._conn, "baseline_alerts_enabled") != "0"
        )
        wake_minutes = int(settings_repo.get(self._conn, "wake_minutes") or "420")
        self._wake_time = QTimeEdit(QTime(wake_minutes // 60, wake_minutes % 60))
        self._wake_time.setDisplayFormat("HH:mm")
        self._overhead = QSpinBox()
        self._overhead.setRange(0, 100)
        self._overhead.setSuffix(" %")
        self._overhead.setValue(
            int(settings_repo.get(self._conn, "break_overhead_percent") or "20")
        )
        margin_values = self._read_alert_margins()
        self._alert_margins = []
        margins_row = QHBoxLayout()
        for label, value in zip(("Heads-up", "Warning", "Urgent"), margin_values):
            margins_row.addWidget(QLabel(label))
            margin = QSpinBox()
            margin.setRange(0, 1440)
            margin.setSuffix(" min")
            margin.setValue(value)
            self._alert_margins.append(margin)
            margins_row.addWidget(margin)
        self._alert_sound = QCheckBox("Play a sound for baseline alerts")
        self._alert_sound.setChecked(settings_repo.get(self._conn, "alert_sound") == "1")
        self._tray_minimize = QCheckBox("Keep running in the system tray after closing")
        self._tray_minimize.setChecked(settings_repo.get(self._conn, "tray_minimize") != "0")
        self._tray_minimize.setToolTip("Requires Windows system tray support.")
        form.addRow("Baseline alerts:", self._baseline_alerts)
        form.addRow("Wake time:", self._wake_time)
        form.addRow("Break overhead:", self._overhead)
        form.addRow("Alert margins:", margins_row)
        form.addRow("", self._alert_sound)
        form.addRow("", self._tray_minimize)
        self._goal_weekday = QComboBox()
        for weekday, label in enumerate(
            ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        ):
            self._goal_weekday.addItem(label, weekday)
        self._goal_hours = QDoubleSpinBox()
        self._goal_hours.setRange(0, 24)
        self._goal_hours.setSingleStep(0.5)
        self._goal_hours.setDecimals(1)
        self._goal_hours.setSuffix(" h")
        self._goal_exam_count = QSpinBox()
        self._goal_exam_count.setRange(0, 1000)
        self._goal_exam_count.setSuffix(" exams")
        self._goal_weekday.currentIndexChanged.connect(self._load_weekday_goal)
        goal_row = QHBoxLayout()
        goal_row.addWidget(self._goal_hours)
        goal_row.addWidget(self._button("Save weekday goal", self._save_weekday_goal))
        goal_row.addStretch()
        form.addRow("Weekday:", self._goal_weekday)
        form.addRow("Minimum study:", goal_row)
        exam_goal_row = QHBoxLayout()
        exam_goal_row.addWidget(self._goal_exam_count)
        exam_goal_row.addStretch()
        form.addRow("Minimum exams:", exam_goal_row)
        form.addRow("", QLabel("Set either minimum to 0 to disable that target."))
        self._load_weekday_goal()
        form.addRow("", self._button("Apply alert settings", self._save_alert_settings))
        form.addRow(self._section_heading("Per-subject daily targets"))
        self._subject_goal_subject = QComboBox()
        self._subject_goal_subject.currentIndexChanged.connect(self._load_subject_daily_goal)
        self._subject_goal_minutes = QSpinBox()
        self._subject_goal_minutes.setRange(0, 1440)
        self._subject_goal_minutes.setSuffix(" min")
        subject_goal_row = QHBoxLayout()
        subject_goal_row.addWidget(self._subject_goal_subject)
        subject_goal_row.addWidget(self._subject_goal_minutes)
        self._subject_goal_save = self._button("Save target", self._save_subject_daily_goal)
        subject_goal_row.addWidget(self._subject_goal_save)
        subject_goal_row.addStretch()
        form.addRow("Subject target:", subject_goal_row)
        self._reload_subject_daily_goal_subjects()
        form.addRow(self._section_heading("Appearance"))
        self._theme = QComboBox()
        self._theme.addItem("Light", "light")
        self._theme.addItem("Dark", "dark")
        theme_index = self._theme.findData(settings_repo.get(self._conn, "theme") or "dark")
        self._theme.setCurrentIndex(max(0, theme_index))
        self._theme.currentIndexChanged.connect(self._save_theme)
        form.addRow("Theme:", self._theme)
        form.addRow(self._section_heading("Exam setup"))
        self._exam_categories = QComboBox()
        self._exam_levels = QComboBox()
        self._exam_lookup_name = QLineEdit()
        self._reload_exam_lookups()
        form.addRow("Exam category:", self._exam_categories)
        form.addRow("Exam level:", self._exam_levels)
        lookup_buttons = QHBoxLayout()
        lookup_buttons.addWidget(self._exam_lookup_name)
        lookup_buttons.addWidget(self._button("Add category", self._add_exam_category))
        lookup_buttons.addWidget(self._button("Archive category", self._archive_exam_category))
        lookup_buttons.addWidget(self._button("Add level", self._add_exam_level))
        lookup_buttons.addWidget(self._button("Archive level", self._archive_exam_level))
        form.addRow("Exam lists:", lookup_buttons)
        self._scoring_presets = QComboBox()
        self._scoring_presets.currentIndexChanged.connect(self._load_scoring_preset)
        self._scoring_preset_name = QLineEdit()
        self._scoring_correct = QLineEdit("1")
        self._scoring_penalty = QLineEdit("0.25")
        self._scoring_skipped = QLineEdit("0")
        form.addRow("Scoring preset:", self._scoring_presets)
        form.addRow("Preset name:", self._scoring_preset_name)
        form.addRow("Marks per correct:", self._scoring_correct)
        form.addRow("Penalty per incorrect:", self._scoring_penalty)
        form.addRow("Marks per skipped:", self._scoring_skipped)
        scoring_buttons = QHBoxLayout()
        scoring_buttons.addWidget(self._button("New preset", self._new_scoring_preset))
        scoring_buttons.addWidget(self._button("Save preset", self._save_scoring_preset))
        scoring_buttons.addWidget(self._button("Archive preset", self._archive_scoring_preset))
        scoring_buttons.addStretch()
        form.addRow("", scoring_buttons)
        self._reload_scoring_presets()
        form.addRow(self._section_heading("Pomodoro presets"))
        self._pomodoro_service = PomodoroService(self._conn)
        self._pomodoro_presets = QComboBox()
        self._pomodoro_presets.currentIndexChanged.connect(self._load_pomodoro_preset)
        self._pomodoro_name = QLineEdit()
        self._pomodoro_focus = QSpinBox()
        self._pomodoro_focus.setRange(1, 180)
        self._pomodoro_focus.setSuffix(" min")
        self._pomodoro_short = QSpinBox()
        self._pomodoro_short.setRange(0, 60)
        self._pomodoro_short.setSuffix(" min")
        self._pomodoro_long = QSpinBox()
        self._pomodoro_long.setRange(0, 120)
        self._pomodoro_long.setSuffix(" min")
        self._pomodoro_cycles = QSpinBox()
        self._pomodoro_cycles.setRange(1, 12)
        self._pomodoro_auto_break = QCheckBox("Start break automatically")
        self._pomodoro_auto_focus = QCheckBox("Start focus automatically")
        self._pomodoro_sound = QCheckBox("Play a sound at phase changes")
        self._pomodoro_sound.setChecked(settings_repo.get(self._conn, "pomodoro_sound") == "1")
        self._pomodoro_sound.toggled.connect(self._save_pomodoro_sound)
        form.addRow("Pomodoro preset:", self._pomodoro_presets)
        form.addRow("Preset name:", self._pomodoro_name)
        form.addRow("Focus:", self._pomodoro_focus)
        form.addRow("Short break:", self._pomodoro_short)
        form.addRow("Long break:", self._pomodoro_long)
        form.addRow("Focus periods before long break:", self._pomodoro_cycles)
        form.addRow("", self._pomodoro_auto_break)
        form.addRow("", self._pomodoro_auto_focus)
        form.addRow("", self._pomodoro_sound)
        pomodoro_buttons = QHBoxLayout()
        pomodoro_buttons.addWidget(self._button("New preset", self._new_pomodoro_preset))
        pomodoro_buttons.addWidget(self._button("Save preset", self._save_pomodoro_preset))
        pomodoro_buttons.addStretch()
        form.addRow("", pomodoro_buttons)
        self._reload_pomodoro_presets()
        form.addRow(self._section_heading("Backup retention"))
        self._copies = QSpinBox()
        self._copies.setRange(1, 100)
        self._copies.setValue(int(settings_repo.get(self._conn, "backup_copies") or "10"))
        self._copies.valueChanged.connect(self._save_backup_copies)
        form.addRow("Automatic copies kept:", self._copies)
        form.addRow(self._section_heading("Application details"))
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

    def _read_alert_margins(self) -> tuple[int, int, int]:
        value = settings_repo.get(self._conn, "alert_margins_minutes") or "120,60,20"
        try:
            margins = tuple(int(part.strip()) for part in value.split(","))
        except ValueError:
            margins = ()
        if len(margins) != 3 or not margins[0] >= margins[1] >= margins[2] >= 0:
            return 120, 60, 20
        return margins

    def _load_weekday_goal(self) -> None:
        weekday = self._goal_weekday.currentData()
        if weekday is None:
            return
        row = self._conn.execute(
            "SELECT study_goal_secs, exam_goal_type, exam_goal_value "
            "FROM weekday_defaults WHERE weekday = ?",
            (weekday,),
        ).fetchone()
        self._goal_hours.setValue(
            float(row["study_goal_secs"] / 3600) if row else 0
        )
        exam_count = (
            int(row["exam_goal_value"])
            if row and row["exam_goal_type"] == "count"
            else 0
        )
        self._goal_exam_count.setValue(exam_count)

    def _save_weekday_goal(self) -> None:
        try:
            day_plan_service.set_weekday_study_goal_seconds(
                self._conn,
                int(self._goal_weekday.currentData()),
                round(self._goal_hours.value() * 3600),
            )
            exam_count = self._goal_exam_count.value()
            day_plan_service.set_weekday_exam_goal(
                self._conn,
                int(self._goal_weekday.currentData()),
                goal_type="count" if exam_count else "none",
                value=exam_count,
            )
        except AppError as exc:
            warn(self, "Invalid study target", str(exc))
            return
        self._signals.settings_changed.emit()

    def _reload_subject_daily_goal_subjects(self) -> None:
        previous_id = self._subject_goal_subject.currentData()
        self._subject_goal_subject.blockSignals(True)
        self._subject_goal_subject.clear()
        for subject in subject_service.get_all(self._conn, include_archived=False):
            self._subject_goal_subject.addItem(subject.name, subject.id)
        index = self._subject_goal_subject.findData(previous_id)
        if index < 0 and self._subject_goal_subject.count():
            index = 0
        self._subject_goal_subject.setCurrentIndex(index)
        self._subject_goal_subject.blockSignals(False)
        self._load_subject_daily_goal()

    def _load_subject_daily_goal(self) -> None:
        subject_id = self._subject_goal_subject.currentData()
        enabled = subject_id is not None
        self._subject_goal_minutes.setEnabled(enabled)
        self._subject_goal_save.setEnabled(enabled)
        if enabled:
            seconds = subject_daily_goal_service.get_daily_goal_seconds(self._conn, subject_id)
            self._subject_goal_minutes.setValue(seconds // 60)
        else:
            self._subject_goal_minutes.setValue(0)

    def _save_subject_daily_goal(self) -> None:
        subject_id = self._subject_goal_subject.currentData()
        if subject_id is None:
            return
        try:
            subject_daily_goal_service.set_daily_goal_seconds(
                self._conn, subject_id, self._subject_goal_minutes.value() * 60
            )
        except AppError as exc:
            warn(self, "Invalid subject target", str(exc))
            return
        self._signals.settings_changed.emit()
        self._message.setText(f"Saved daily target for {self._subject_goal_subject.currentText()}.")

    def _save_alert_settings(self) -> None:
        margins = tuple(spin.value() for spin in self._alert_margins)
        if not margins[0] >= margins[1] >= margins[2]:
            warn(self, "Invalid alert margins", "Margins must descend from heads-up to urgent.")
            return
        wake_time = self._wake_time.time()
        settings_repo.set_many(
            self._conn,
            {
                "baseline_alerts_enabled": str(int(self._baseline_alerts.isChecked())),
                "wake_minutes": str(wake_time.hour() * 60 + wake_time.minute()),
                "break_overhead_percent": str(self._overhead.value()),
                "alert_margins_minutes": ",".join(str(value) for value in margins),
                "alert_sound": str(int(self._alert_sound.isChecked())),
                "tray_minimize": str(int(self._tray_minimize.isChecked())),
            },
        )
        self._signals.settings_changed.emit()
        alert(self, "Alert settings saved", "Baseline alert preferences were updated.")

    def _save_theme(self) -> None:
        settings_repo.set_value(self._conn, "theme", self._theme.currentData())
        self._signals.settings_changed.emit()

    def _reload_exam_lookups(self) -> None:
        self._exam_categories.clear()
        self._exam_levels.clear()
        for row in exams_repo.lookup_values(self._conn, "exam_categories"):
            self._exam_categories.addItem(str(row["name"]), int(row["id"]))
        for row in exams_repo.lookup_values(self._conn, "exam_levels"):
            self._exam_levels.addItem(str(row["name"]), int(row["id"]))

    def _add_exam_lookup(self, table: str, combo: QComboBox) -> None:
        name = self._exam_lookup_name.text().strip()
        if not name:
            return
        try:
            item_id = exams_repo.add_lookup(self._conn, table, name)
            combo.addItem(name, item_id)
            combo.setCurrentIndex(combo.count() - 1)
            self._exam_lookup_name.clear()
            self._signals.settings_changed.emit()
        except sqlite3.IntegrityError as exc:
            warn(self, "Duplicate exam list item", str(exc))

    def _add_exam_category(self) -> None:
        self._add_exam_lookup("exam_categories", self._exam_categories)

    def _add_exam_level(self) -> None:
        self._add_exam_lookup("exam_levels", self._exam_levels)

    def _archive_exam_lookup(self, table: str, combo: QComboBox) -> None:
        item_id = combo.currentData()
        if item_id is None:
            return
        if not confirm(self, "Archive exam list item", f"Archive '{combo.currentText()}'?"):
            return
        exams_repo.archive_lookup(self._conn, table, item_id)
        self._reload_exam_lookups()
        self._signals.settings_changed.emit()

    def _archive_exam_category(self) -> None:
        self._archive_exam_lookup("exam_categories", self._exam_categories)

    def _archive_exam_level(self) -> None:
        self._archive_exam_lookup("exam_levels", self._exam_levels)

    def _reload_scoring_presets(self, select_id: int | None = None) -> None:
        self._scoring_presets.blockSignals(True)
        self._scoring_presets.clear()
        self._scoring_presets.addItem("New preset", None)
        for row in exams_repo.lookup_values(self._conn, "scoring_presets"):
            self._scoring_presets.addItem(str(row["name"]), int(row["id"]))
        index = self._scoring_presets.findData(select_id)
        self._scoring_presets.setCurrentIndex(index if index >= 0 else 0)
        self._scoring_presets.blockSignals(False)
        self._load_scoring_preset()

    def _load_scoring_preset(self) -> None:
        preset_id = self._scoring_presets.currentData()
        preset = next(
            (
                row
                for row in exams_repo.lookup_values(self._conn, "scoring_presets")
                if row["id"] == preset_id
            ),
            None,
        )
        if preset is None:
            self._scoring_preset_name.clear()
            self._scoring_correct.setText("1")
            self._scoring_penalty.setText("0.25")
            self._scoring_skipped.setText("0")
            return
        self._scoring_preset_name.setText(str(preset["name"]))
        self._scoring_correct.setText(_milli_to_text(int(preset["marks_per_correct_milli"])))
        self._scoring_penalty.setText(_milli_to_text(int(preset["penalty_per_incorrect_milli"])))
        self._scoring_skipped.setText(_milli_to_text(int(preset["marks_per_skipped_milli"])))

    def _new_scoring_preset(self) -> None:
        self._scoring_presets.setCurrentIndex(0)
        self._scoring_preset_name.setFocus()

    def _save_scoring_preset(self) -> None:
        try:
            name = self._scoring_preset_name.text().strip()
            values = (
                _text_to_milli(self._scoring_correct.text()),
                _text_to_milli(self._scoring_penalty.text()),
                _text_to_milli(self._scoring_skipped.text()),
            )
            if not name:
                raise ValueError("Enter a name for this preset.")
            preset_id = self._scoring_presets.currentData()
            if preset_id is None:
                preset_id = exams_repo.add_scoring_preset(
                    self._conn,
                    name=name,
                    marks_per_correct_milli=values[0],
                    penalty_per_incorrect_milli=values[1],
                    marks_per_skipped_milli=values[2],
                )
            else:
                exams_repo.update_scoring_preset(
                    self._conn,
                    preset_id,
                    name=name,
                    marks_per_correct_milli=values[0],
                    penalty_per_incorrect_milli=values[1],
                    marks_per_skipped_milli=values[2],
                )
            self._reload_scoring_presets(preset_id)
            self._signals.settings_changed.emit()
        except (ValueError, InvalidOperation, sqlite3.IntegrityError) as exc:
            warn(self, "Cannot save scoring preset", str(exc))

    def _archive_scoring_preset(self) -> None:
        preset_id = self._scoring_presets.currentData()
        if preset_id is None:
            return
        if not confirm(
            self,
            "Archive scoring preset",
            f"Archive '{self._scoring_presets.currentText()}'? "
            "Existing exam results will not change.",
        ):
            return
        exams_repo.archive_lookup(self._conn, "scoring_presets", preset_id)
        self._reload_scoring_presets()

    def _reload_pomodoro_presets(self, select_id: int | None = None) -> None:
        self._pomodoro_presets.blockSignals(True)
        self._pomodoro_presets.clear()
        self._pomodoro_presets.addItem("New preset", None)
        for preset in self._pomodoro_service.presets():
            self._pomodoro_presets.addItem(preset.name, preset.id)
        index = self._pomodoro_presets.findData(select_id)
        self._pomodoro_presets.setCurrentIndex(index if index >= 0 else 0)
        self._pomodoro_presets.blockSignals(False)
        self._load_pomodoro_preset()

    def _load_pomodoro_preset(self) -> None:
        preset_id = self._pomodoro_presets.currentData()
        preset = next(
            (preset for preset in self._pomodoro_service.presets() if preset.id == preset_id), None
        )
        if preset is None:
            self._pomodoro_name.clear()
            self._pomodoro_focus.setValue(25)
            self._pomodoro_short.setValue(5)
            self._pomodoro_long.setValue(15)
            self._pomodoro_cycles.setValue(4)
            self._pomodoro_auto_break.setChecked(True)
            self._pomodoro_auto_focus.setChecked(False)
            return
        self._pomodoro_name.setText(preset.name)
        self._pomodoro_focus.setValue(preset.focus_seconds // 60)
        self._pomodoro_short.setValue(preset.short_break_seconds // 60)
        self._pomodoro_long.setValue(preset.long_break_seconds // 60)
        self._pomodoro_cycles.setValue(preset.cycles_before_long_break)
        self._pomodoro_auto_break.setChecked(preset.auto_start_break)
        self._pomodoro_auto_focus.setChecked(preset.auto_start_focus)

    def _new_pomodoro_preset(self) -> None:
        self._pomodoro_presets.setCurrentIndex(0)
        self._pomodoro_name.setFocus()

    def _save_pomodoro_sound(self, enabled: bool) -> None:
        settings_repo.set_value(self._conn, "pomodoro_sound", "1" if enabled else "0")

    def _save_pomodoro_preset(self) -> None:
        values = {
            "name": self._pomodoro_name.text(),
            "focus_seconds": self._pomodoro_focus.value() * 60,
            "short_break_seconds": self._pomodoro_short.value() * 60,
            "long_break_seconds": self._pomodoro_long.value() * 60,
            "cycles_before_long_break": self._pomodoro_cycles.value(),
            "auto_start_break": self._pomodoro_auto_break.isChecked(),
            "auto_start_focus": self._pomodoro_auto_focus.isChecked(),
        }
        try:
            preset_id = self._pomodoro_presets.currentData()
            if preset_id is None:
                preset = self._pomodoro_service.create_preset(**values)
                preset_id = preset.id
            else:
                self._pomodoro_service.update_preset(preset_id, **values)
            self._reload_pomodoro_presets(preset_id)
            self._signals.settings_changed.emit()
        except AppError as exc:
            warn(self, "Cannot save Pomodoro preset", str(exc))

    def _change_cutoff(self) -> None:
        new_cutoff = self._cutoff_time.time().hour() * 60 + self._cutoff_time.time().minute()
        current = int(settings_repo.get(self._conn, "day_cutoff_minutes") or "180")
        if new_cutoff == current:
            return
        count = self._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE start_utc IS NOT NULL"
        ).fetchone()[0]
        if not confirm(
            self,
            "Change study-day cutoff",
            f"Recalculate the study day for {count} timed session(s)?",
            "A safety backup will be created first. Duration-only entries keep their dates.",
        ):
            self._cutoff_time.setTime(QTime(current // 60, current % 60))
            return
        try:
            changed, backup_path = change_study_day_cutoff(
                self._conn, new_cutoff, paths.backup_dir()
            )
        except AppError as exc:
            warn(self, "Could not change cutoff", str(exc))
            self._cutoff_time.setTime(QTime(current // 60, current % 60))
            return
        self._clock.set_cutoff_minutes(new_cutoff)
        self._signals.sessions_changed.emit()
        self._signals.day_changed.emit()
        self._signals.settings_changed.emit()
        self._message.setText(f"Updated {changed} timed session(s). Safety backup: {backup_path}")

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


def _text_to_milli(text: str) -> int:
    try:
        value = Decimal(text.strip()) * 1000
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Enter marks with at most three decimal places.") from exc
    if value != value.to_integral_value():
        raise ValueError("Enter marks with at most three decimal places.")
    return int(value)


def _milli_to_text(value: int) -> str:
    return f"{Decimal(value) / 1000:.3f}".rstrip("0").rstrip(".")
