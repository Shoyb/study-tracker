from __future__ import annotations

from study_tracker.domain.baseline import alert_level, required_minutes_for_day
from study_tracker.domain.exam_scoring import compute_exam_summary
from study_tracker.domain.exam_stats import aggregate_by_group
from study_tracker.domain.pomodoro import PomodoroState, advance_phase
from study_tracker.domain.records import is_record, record_values


def test_pomodoro_advances_focus_to_break_and_back():
    state = PomodoroState(phase="focus", remaining_seconds=1200, completed_cycles=0)
    next_state = advance_phase(state, preset_minutes=25)
    assert next_state.phase == "short_break"
    assert next_state.remaining_seconds == 300
    assert next_state.completed_cycles == 1


def test_pomodoro_uses_long_break_after_four_focus_cycles():
    state = PomodoroState(phase="focus", remaining_seconds=1500)
    for _ in range(3):
        state = advance_phase(state)
        state = advance_phase(state)
    long_break = advance_phase(state)
    assert long_break.phase == "long_break"
    assert long_break.remaining_seconds == 900
    assert long_break.completed_cycles == 4


def test_baseline_alert_levels():
    assert required_minutes_for_day(180, overhead_percent=20) == 216
    assert alert_level(120, margins=(120, 60, 20)) == "headsup"
    assert alert_level(10, margins=(120, 60, 20)) == "urgent"
    assert alert_level(-5, margins=(120, 60, 20)) == "critical"


def test_exam_summary_uses_net_accuracy():
    summary = compute_exam_summary(
        full_marks=120,
        correct=18,
        incorrect=2,
        marks_per_correct=5,
        penalty_per_incorrect=1,
    )
    assert summary["net_marks"] == 88
    assert summary["net_accuracy"] == 0.7333333333333333
    assert summary["attempt_accuracy"] == 0.9


def test_exam_group_aggregation():
    exams = [
        {"id": 1, "group_ids": [1, 2], "score": 80},
        {"id": 2, "group_ids": [1], "score": 20},
        {"id": 3, "group_ids": [2], "score": 40},
    ]
    result = aggregate_by_group(exams)
    assert result[1] == 50.0
    assert result[2] == 60.0


def test_record_detection_only_tracks_new_highs():
    assert is_record(82, [72, 76, 80, 79]) is True
    assert is_record(75, [72, 76, 80, 79]) is False
    assert record_values([70, 72, 71, 80]) == [70, 72, 72, 80]
