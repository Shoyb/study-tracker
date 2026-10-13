"""Exam editor with result parts and a live score preview."""

from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from study_tracker.db import exams_repo, subjects_repo
from study_tracker.db.exams_repo import Exam, ExamPart
from study_tracker.domain.exam_scoring import (
    MCQPart,
    format_milli_marks,
    format_percentage,
    score_exam,
)


def _to_milli(text: str) -> int:
    try:
        value = Decimal(text.strip()) * 1000
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Enter marks as a number with up to three decimal places.") from exc
    if value != value.to_integral_value():
        raise ValueError("Marks can have at most three decimal places.")
    return int(value)


def _from_milli(value: int | None) -> str:
    return format_milli_marks(value or 0)


class ExamPartDialog(QDialog):
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        kind: str,
        part: ExamPart | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._part = part
        self.setWindowTitle("Edit exam part" if part else "Add exam part")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._label = QLineEdit(part.label if part else "")
        self._subject = QComboBox()
        self._subject.addItem("No subject", None)
        for subject in subjects_repo.get_all(conn, include_archived=True):
            self._subject.addItem(subject.name, subject.id)
        if part and part.subject_id is not None:
            self._subject.setCurrentIndex(self._subject.findData(part.subject_id))
        form.addRow("Label:", self._label)
        form.addRow("Subject:", self._subject)
        layout.addLayout(form)

        self._mcq_box = QWidget()
        mcq_form = QFormLayout(self._mcq_box)
        self._total = self._counter(100 if part is None else part.total_questions or 1)
        self._correct = self._counter(part.correct if part and part.correct is not None else 0)
        self._incorrect = self._counter(
            part.incorrect if part and part.incorrect is not None else 0
        )
        self._skipped = self._counter(
            part.skipped if part and part.skipped is not None else (100 if part is None else 0)
        )
        self._total.valueChanged.connect(lambda: self._counts_changed("total"))
        self._correct.valueChanged.connect(lambda: self._counts_changed("correct"))
        self._incorrect.valueChanged.connect(lambda: self._counts_changed("incorrect"))
        self._skipped.valueChanged.connect(lambda: self._counts_changed("skipped"))
        mcq_form.addRow("Total questions:", self._total)
        mcq_form.addRow("Correct:", self._correct)
        mcq_form.addRow("Incorrect:", self._incorrect)
        mcq_form.addRow("Skipped:", self._skipped)

        self._presets = QComboBox()
        self._preset_values: dict[int, tuple[int, int, int]] = {}
        for preset in exams_repo.lookup_values(conn, "scoring_presets"):
            preset_id = int(preset["id"])
            self._presets.addItem(str(preset["name"]), preset_id)
            self._preset_values[preset_id] = (
                int(preset["marks_per_correct_milli"]),
                int(preset["penalty_per_incorrect_milli"]),
                int(preset["marks_per_skipped_milli"]),
            )
        mcq_form.addRow("Marking preset:", self._presets)
        self._marks_correct = QLineEdit("1")
        self._penalty = QLineEdit("0.25")
        self._marks_skipped = QLineEdit("0")
        self._presets.currentIndexChanged.connect(self._apply_preset)
        mcq_form.addRow("Marks per correct:", self._marks_correct)
        mcq_form.addRow("Penalty per incorrect:", self._penalty)
        mcq_form.addRow("Marks per skipped:", self._marks_skipped)
        save_preset = QPushButton("Save scheme as preset")
        save_preset.clicked.connect(self._save_preset)
        mcq_form.addRow("", save_preset)
        layout.addWidget(self._mcq_box)

        self._written_box = QWidget()
        written_form = QFormLayout(self._written_box)
        self._written_full = QLineEdit()
        self._written_obtained = QLineEdit()
        written_form.addRow("Full marks:", self._written_full)
        written_form.addRow("Marks obtained:", self._written_obtained)
        layout.addWidget(self._written_box)
        self._preview = QLabel()
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)
        for field in (self._marks_correct, self._penalty, self._marks_skipped,
                      self._written_full, self._written_obtained):
            field.textChanged.connect(self._update_preview)
        self._correct.valueChanged.connect(self._update_preview)
        self._incorrect.valueChanged.connect(self._update_preview)
        self._skipped.valueChanged.connect(self._update_preview)
        self._total.valueChanged.connect(self._update_preview)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_part)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._kind = kind
        if part is not None:
            self._kind = part.kind
            if part.kind == "mcq":
                self._marks_correct.setText(_from_milli(part.marks_per_correct_milli))
                self._penalty.setText(_from_milli(part.penalty_per_incorrect_milli))
                self._marks_skipped.setText(_from_milli(part.marks_per_skipped_milli))
            else:
                self._written_full.setText(_from_milli(part.written_full_milli))
                self._written_obtained.setText(_from_milli(part.written_obtained_milli))
        elif self._presets.count():
            self._apply_preset()
        self._update_kind_visibility()
        self._update_preview()

    @staticmethod
    def _counter(value: int) -> QSpinBox:
        counter = QSpinBox()
        counter.setRange(0, 100000)
        counter.setValue(value)
        return counter

    def _counts_changed(self, changed: str) -> None:
        if changed == "skipped":
            self._total.setValue(
                self._correct.value() + self._incorrect.value() + self._skipped.value()
            )
        else:
            remaining = self._total.value() - self._correct.value() - self._incorrect.value()
            if remaining >= 0:
                self._skipped.setValue(remaining)
        self._update_preview()

    def _apply_preset(self) -> None:
        values = self._preset_values.get(self._presets.currentData())
        if values is None:
            return
        self._marks_correct.setText(_from_milli(values[0]))
        self._penalty.setText(_from_milli(values[1]))
        self._marks_skipped.setText(_from_milli(values[2]))

    def _save_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save marking preset", "Preset name:")
        if not accepted or not name.strip():
            return
        try:
            values = (
                _to_milli(self._marks_correct.text()),
                _to_milli(self._penalty.text()),
                _to_milli(self._marks_skipped.text()),
            )
            preset_id = exams_repo.add_scoring_preset(
                self._conn,
                name=name.strip(),
                marks_per_correct_milli=values[0],
                penalty_per_incorrect_milli=values[1],
                marks_per_skipped_milli=values[2],
            )
        except (ValueError, sqlite3.IntegrityError) as exc:
            QMessageBox.warning(self, "Cannot save preset", str(exc))
            return
        self._preset_values[preset_id] = values
        self._presets.addItem(name.strip(), preset_id)
        self._presets.setCurrentIndex(self._presets.count() - 1)

    def _update_kind_visibility(self) -> None:
        is_mcq = self._kind == "mcq"
        self._mcq_box.setVisible(is_mcq)
        self._written_box.setVisible(not is_mcq)
        self._preview.setVisible(is_mcq)

    def _part_value(self) -> ExamPart:
        if self._kind == "mcq":
            return ExamPart(
                kind="mcq",
                label=self._label.text().strip(),
                subject_id=self._subject.currentData(),
                total_questions=self._total.value(),
                correct=self._correct.value(),
                incorrect=self._incorrect.value(),
                skipped=self._skipped.value(),
                marks_per_correct_milli=_to_milli(self._marks_correct.text()),
                penalty_per_incorrect_milli=_to_milli(self._penalty.text()),
                marks_per_skipped_milli=_to_milli(self._marks_skipped.text()),
            )
        return ExamPart(
            kind="written",
            label=self._label.text().strip(),
            subject_id=self._subject.currentData(),
            written_full_milli=_to_milli(self._written_full.text()),
            written_obtained_milli=_to_milli(self._written_obtained.text()),
        )

    def _update_preview(self) -> None:
        if self._kind != "mcq":
            return
        try:
            part = self._part_value()
            score = score_exam([
                MCQPart(
                    part.total_questions or 0,
                    part.correct or 0,
                    part.incorrect or 0,
                    part.skipped or 0,
                    part.marks_per_correct_milli or 0,
                    part.penalty_per_incorrect_milli or 0,
                    part.marks_per_skipped_milli or 0,
                )
            ])
            self._preview.setText(
                f"Score {format_milli_marks(score.score_milli)} / "
                f"{format_milli_marks(score.full_milli)} "
                f"({format_percentage(score.net_accuracy)}), "
                f"net {format_percentage(score.net_accuracy)}, "
                f"attempt {format_percentage(score.attempt_accuracy)}, "
                f"raw {format_percentage(score.raw_accuracy)}, "
                f"lost {format_milli_marks(score.marks_lost_milli)} to negatives, "
                f"{format_milli_marks(score.marks_unanswered_milli)} marks unanswered."
            )
        except (ValueError, InvalidOperation):
            self._preview.setText("Complete valid counts and marking values for a score preview.")

    def _accept_part(self) -> None:
        try:
            self._part_value()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid result part", str(exc))
            return
        self.accept()

    @property
    def part(self) -> ExamPart:
        return self._part_value()


class ExamDialog(QDialog):
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock,
        exam: Exam | None = None,
        default_status: str = "completed",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._clock = clock
        self._exam = exam
        self._parts = list(exam.parts) if exam else []
        self.setWindowTitle("Edit exam" if exam else "Add exam")
        self.setMinimumSize(640, 600)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._title = QLineEdit(exam.title if exam else "")
        self._date = QDateEdit(QDate.fromString(
            exam.exam_date if exam else clock.local_date(), "yyyy-MM-dd"
        ))
        self._date.setCalendarPopup(True)
        self._status = QComboBox()
        self._status.addItem("Completed", "completed")
        self._status.addItem("Planned", "planned")
        self._status.setCurrentIndex(
            self._status.findData(exam.status if exam else default_status)
        )
        self._category = QComboBox()
        self._category.addItem("No category", None)
        for row in exams_repo.lookup_values(conn, "exam_categories"):
            self._category.addItem(str(row["name"]), int(row["id"]))
        self._level = QComboBox()
        self._level.addItem("Unspecified", None)
        for row in exams_repo.lookup_values(conn, "exam_levels"):
            self._level.addItem(str(row["name"]), int(row["id"]))
        self._allowed = QSpinBox()
        self._allowed.setRange(0, 10000)
        self._allowed.setSuffix(" min")
        self._taken = QSpinBox()
        self._taken.setRange(0, 10000)
        self._taken.setSuffix(" min")
        if exam:
            self._allowed.setValue((exam.allowed_seconds or 0) // 60)
            self._taken.setValue((exam.taken_seconds or 0) // 60)
            self._category.setCurrentIndex(self._category.findData(exam.category_id))
            self._level.setCurrentIndex(self._level.findData(exam.level_id))
        self._notes = QPlainTextEdit(exam.notes if exam else "")
        self._notes.setMaximumHeight(80)
        self._count_as_study = QCheckBox("Count time taken as study time")
        self._count_as_study.setChecked(exam.session_id is not None if exam else True)
        form.addRow("Title:", self._title)
        form.addRow("Study day:", self._date)
        form.addRow("Status:", self._status)
        form.addRow("Category:", self._category)
        form.addRow("Level:", self._level)
        form.addRow("Time allowed:", self._allowed)
        form.addRow("Time taken:", self._taken)
        form.addRow("Notes:", self._notes)
        form.addRow("", self._count_as_study)
        layout.addLayout(form)
        layout.addWidget(QLabel("Result parts"))
        self._part_list = QListWidget()
        layout.addWidget(self._part_list)
        controls = QHBoxLayout()
        for label, kind in (("Add MCQ part", "mcq"), ("Add written part", "written")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, part_kind=kind: self._add_part(part_kind))
            controls.addWidget(button)
        edit_button = QPushButton("Edit part")
        edit_button.clicked.connect(self._edit_part)
        remove_button = QPushButton("Remove part")
        remove_button.clicked.connect(self._remove_part)
        controls.addWidget(edit_button)
        controls.addWidget(remove_button)
        layout.addLayout(controls)
        self._status.currentIndexChanged.connect(self._update_status_fields)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_exam)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if not exam and default_status == "completed":
            self._parts.append(ExamPart(
                kind="mcq", total_questions=1, correct=0, incorrect=0, skipped=1,
                marks_per_correct_milli=1000, penalty_per_incorrect_milli=250,
                marks_per_skipped_milli=0,
            ))
        self._refresh_parts()
        self._update_status_fields()

    def _refresh_parts(self) -> None:
        self._part_list.clear()
        for part in self._parts:
            if part.kind == "mcq":
                summary = f"MCQ: {part.correct}/{part.total_questions} correct, "
                summary += f"{part.incorrect} wrong, {part.skipped} skipped"
            else:
                summary = (
                    f"Written: {format_milli_marks(part.written_obtained_milli or 0)} / "
                    f"{format_milli_marks(part.written_full_milli or 0)}"
                )
            label = f"{part.label}: " if part.label else ""
            self._part_list.addItem(QListWidgetItem(label + summary))

    def _add_part(self, kind: str) -> None:
        dialog = ExamPartDialog(self._conn, kind=kind, parent=self)
        if dialog.exec() == ExamPartDialog.DialogCode.Accepted:
            self._parts.append(dialog.part)
            self._refresh_parts()

    def _edit_part(self) -> None:
        index = self._part_list.currentRow()
        if index < 0:
            return
        part = self._parts[index]
        dialog = ExamPartDialog(self._conn, kind=part.kind, part=part, parent=self)
        if dialog.exec() == ExamPartDialog.DialogCode.Accepted:
            self._parts[index] = dialog.part
            self._refresh_parts()
            self._part_list.setCurrentRow(index)

    def _remove_part(self) -> None:
        index = self._part_list.currentRow()
        if index >= 0:
            self._parts.pop(index)
            self._refresh_parts()

    def _update_status_fields(self) -> None:
        completed = self._status.currentData() == "completed"
        for widget in (self._taken, self._count_as_study, self._part_list):
            widget.setEnabled(completed)

    def _accept_exam(self) -> None:
        if not self.title:
            QMessageBox.warning(self, "Invalid exam", "Enter an exam title.")
            return
        if self.status == "completed" and not self._parts:
            QMessageBox.warning(self, "Invalid exam", "Add at least one result part.")
            return
        if self.status == "planned" and self._parts:
            QMessageBox.warning(
                self, "Planned exam", "Remove result parts before planning an exam."
            )
            return
        self.accept()

    @property
    def title(self) -> str:
        return self._title.text().strip()

    @property
    def exam_date(self) -> str:
        return self._date.date().toString("yyyy-MM-dd")

    @property
    def status(self) -> str:
        return str(self._status.currentData())

    @property
    def category_id(self) -> int | None:
        return self._category.currentData()

    @property
    def level_id(self) -> int | None:
        return self._level.currentData()

    @property
    def allowed_seconds(self) -> int | None:
        value = self._allowed.value() * 60
        return value or None

    @property
    def taken_seconds(self) -> int | None:
        value = self._taken.value() * 60
        return value or None

    @property
    def notes(self) -> str:
        return self._notes.toPlainText().strip()

    @property
    def parts(self) -> tuple[ExamPart, ...]:
        return tuple(self._parts)

    @property
    def count_as_study(self) -> bool:
        return self._count_as_study.isChecked()
