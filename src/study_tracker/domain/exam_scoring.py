"""Exam scoring and headline accuracy calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class MCQPart:
    total_questions: int
    correct: int
    incorrect: int
    skipped: int
    marks_per_correct_milli: int
    penalty_per_incorrect_milli: int
    marks_per_skipped_milli: int = 0


@dataclass(frozen=True)
class WrittenPart:
    full_marks_milli: int
    obtained_milli: int


type ExamPart = MCQPart | WrittenPart


@dataclass(frozen=True)
class PartScore:
    score_milli: int
    full_milli: int
    correct: int = 0
    incorrect: int = 0
    skipped: int = 0
    marks_lost_milli: int = 0
    marks_unanswered_milli: int = 0


@dataclass(frozen=True)
class ExamScore:
    score_milli: int
    full_milli: int
    net_accuracy: Decimal | None
    attempt_accuracy: Decimal | None
    raw_accuracy: Decimal | None
    marks_lost_milli: int
    marks_unanswered_milli: int
    time_per_question_seconds: Decimal | None


def score_part(part: ExamPart) -> PartScore:
    if isinstance(part, MCQPart):
        counts = (part.total_questions, part.correct, part.incorrect, part.skipped)
        if any(value < 0 for value in counts) or part.total_questions <= 0:
            raise ValueError("MCQ counts must be nonnegative and total questions must be positive.")
        if part.correct + part.incorrect + part.skipped != part.total_questions:
            raise ValueError("Correct, incorrect and skipped counts must sum to total questions.")
        if part.marks_per_correct_milli <= 0 or part.penalty_per_incorrect_milli < 0:
            raise ValueError("Mark values must be nonnegative and correct marks must be positive.")
        score = (
            part.correct * part.marks_per_correct_milli
            - part.incorrect * part.penalty_per_incorrect_milli
            + part.skipped * part.marks_per_skipped_milli
        )
        return PartScore(
            score_milli=score,
            full_milli=part.total_questions * part.marks_per_correct_milli,
            correct=part.correct,
            incorrect=part.incorrect,
            skipped=part.skipped,
            marks_lost_milli=part.incorrect * part.penalty_per_incorrect_milli,
            marks_unanswered_milli=part.skipped * part.marks_per_correct_milli,
        )
    if part.full_marks_milli <= 0 or not 0 <= part.obtained_milli <= part.full_marks_milli:
        raise ValueError("Written marks must be between zero and full marks.")
    return PartScore(score_milli=part.obtained_milli, full_milli=part.full_marks_milli)


def score_exam(parts: list[ExamPart], *, taken_seconds: int | None = None) -> ExamScore:
    if not parts:
        raise ValueError("An exam must contain at least one part.")
    if taken_seconds is not None and taken_seconds < 0:
        raise ValueError("Time taken cannot be negative.")
    results = [score_part(part) for part in parts]
    score = sum(result.score_milli for result in results)
    full = sum(result.full_milli for result in results)
    correct = sum(result.correct for result in results)
    incorrect = sum(result.incorrect for result in results)
    questions = sum(result.correct + result.incorrect + result.skipped for result in results)
    attempted = correct + incorrect
    all_mcq = all(isinstance(part, MCQPart) for part in parts)
    return ExamScore(
        score_milli=score,
        full_milli=full,
        net_accuracy=Decimal(score) / full if full else None,
        attempt_accuracy=Decimal(correct) / attempted if attempted else None,
        raw_accuracy=Decimal(correct) / questions if questions else None,
        marks_lost_milli=sum(result.marks_lost_milli for result in results),
        marks_unanswered_milli=sum(result.marks_unanswered_milli for result in results),
        time_per_question_seconds=(
            Decimal(taken_seconds) / questions
            if all_mcq and questions and taken_seconds is not None
            else None
        ),
    )


def format_percentage(value: Decimal | None) -> str:
    if value is None:
        return ""
    rounded = (value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{rounded:.1f}%"


def format_milli_marks(value: int) -> str:
    formatted = f"{Decimal(value) / 1000:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"

def compute_exam_summary(
    *,
    full_marks: int,
    correct: int,
    incorrect: int,
    marks_per_correct: int = 1,
    penalty_per_incorrect: int = 0,
) -> dict[str, float | int]:
    """Return a compact summary of an exam score.

    Net marks accuracy is the raw total minus penalties divided by full marks.
    Attempt accuracy is correct attempts divided by total attempted questions.
    """
    net_marks = correct * marks_per_correct - incorrect * penalty_per_incorrect
    attempt_total = correct + incorrect
    net_accuracy = net_marks / full_marks if full_marks else 0.0
    attempt_accuracy = correct / attempt_total if attempt_total else 0.0
    return {
        "net_marks": net_marks,
        "net_accuracy": net_accuracy,
        "attempt_accuracy": attempt_accuracy,
        "correct": correct,
        "incorrect": incorrect,
        "attempt_total": attempt_total,
    }
