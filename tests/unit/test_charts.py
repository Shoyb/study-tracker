"""Backend-neutral drawing tests for the Matplotlib chart functions."""

from __future__ import annotations

from matplotlib.figure import Figure

from study_tracker.charts.daily_bar import draw_daily_bars
from study_tracker.charts.subject_chart import draw_subject_distribution
from study_tracker.charts.task_charts import draw_estimate_vs_actual
from study_tracker.charts.weekly_trend import draw_week_overlay, draw_weekly_trend


def test_daily_chart_has_one_bar_for_every_day_including_zeros():
    figure = Figure()
    axes, bars = draw_daily_bars(
        figure,
        {"2026-10-10": 3600, "2026-10-11": 0, "2026-10-12": 1800},
        today="2026-10-12",
    )
    assert len(bars) == 3
    assert [bar.get_height() for bar in bars] == [1, 0, 0.5]
    assert axes.get_title() == "Daily study time"


def test_subject_chart_sorts_longest_subject_to_top():
    figure = Figure()
    draw_subject_distribution(figure, [("Physics", 3600, "#111111"), ("Math", 7200, "#222222")])
    labels = [label.get_text() for label in figure.axes[0].get_yticklabels()]
    assert labels == ["Physics", "Math"]


def test_estimate_chart_reports_tasks_without_estimates():
    figure = Figure()
    assert draw_estimate_vs_actual(figure, [("Known", 3600, 1800), ("Unknown", 0, 600)]) == 1


def test_weekly_charts_draw_without_data_or_backend():
    totals = {"2026-10-12": 3600, "2026-10-13": 1800}
    figure = Figure()
    draw_weekly_trend(figure, totals)
    assert len(figure.axes[0].lines) == 2
    figure = Figure()
    draw_week_overlay(figure, totals)
    assert len(figure.axes[0].lines) == 1
