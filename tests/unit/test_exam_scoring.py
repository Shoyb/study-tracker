"""Integer scoring rules for exam parts and summaries."""

from __future__ import annotations

from decimal import Decimal

import pytest

from study_tracker.domain.exam_scoring import (
    MCQPart,
    WrittenPart,
    format_milli_marks,
    format_percentage,
    score_exam,
    score_part,
)


def test_worked_mcq_example_matches_all_reported_metrics():
    summary = score_exam(
        [MCQPart(100, 72, 20, 8, 1000, 250)],
        taken_seconds=6000,
    )
    assert summary.score_milli == 67000
    assert summary.full_milli == 100000
    assert format_percentage(summary.net_accuracy) == "67.0%"
    assert format_percentage(summary.attempt_accuracy) == "78.3%"
    assert format_percentage(summary.raw_accuracy) == "72.0%"
    assert summary.marks_lost_milli == 5000
    assert summary.marks_unanswered_milli == 8000
    assert summary.time_per_question_seconds == Decimal("60")


def test_negative_scores_and_zero_attempts_are_defined():
    negative = score_exam([MCQPart(10, 1, 9, 0, 1000, 2000)])
    assert negative.score_milli == -17000
    assert format_percentage(negative.net_accuracy) == "-170.0%"

    blank = score_exam([MCQPart(10, 0, 0, 10, 1000, 250)])
    assert blank.attempt_accuracy is None
    assert format_percentage(blank.attempt_accuracy) == ""
    assert blank.raw_accuracy == Decimal("0")


def test_skipped_marks_and_written_part_aggregate_exactly():
    result = score_exam(
        [
            MCQPart(4, 2, 1, 1, 1000, 250, 500),
            WrittenPart(full_marks_milli=5000, obtained_milli=4250),
        ]
    )
    assert result.score_milli == 6500
    assert result.full_milli == 9000
    assert result.marks_lost_milli == 250
    assert result.marks_unanswered_milli == 1000
    assert result.time_per_question_seconds is None
    assert format_milli_marks(result.score_milli) == "6.5"


def test_invalid_mcq_counts_and_written_marks_are_rejected():
    with pytest.raises(ValueError, match="sum"):
        score_part(MCQPart(10, 4, 2, 3, 1000, 250))
    with pytest.raises(ValueError, match="between"):
        score_part(WrittenPart(full_marks_milli=1000, obtained_milli=1100))


def test_display_percentages_round_half_up():
    assert format_percentage(Decimal("0.725")) == "72.5%"
    assert format_percentage(None) == ""
