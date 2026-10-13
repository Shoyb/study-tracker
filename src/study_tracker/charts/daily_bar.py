"""Daily study-time bar chart."""

from __future__ import annotations

from datetime import date

from study_tracker.charts.style import prepare_axes


def draw_daily_bars(figure, totals: dict[str, int], today: str | None = None):
    """Draw exactly one bar slot per supplied date, including zero days."""
    axes = figure.subplots()
    prepare_axes(axes, "Daily study time")
    dates = list(sorted(totals))
    hours = [totals[day] / 3600 for day in dates]
    colors = ["#1976D2" if day == today else "#90CAF9" for day in dates]
    bars = axes.bar(range(len(dates)), hours, color=colors, width=0.72)
    if not dates:
        axes.text(0.5, 0.5, "No study time recorded in this period", ha="center", va="center")
        axes.set_xticks([])
        return axes, bars
    every = 1 if len(dates) <= 14 else 3 if len(dates) <= 45 else 7
    ticks = list(range(0, len(dates), every))
    axes.set_xticks(ticks, [date.fromisoformat(dates[i]).strftime("%d %b") for i in ticks])
    axes.tick_params(axis="x", rotation=35)
    axes.set_xlim(-0.6, len(dates) - 0.4)
    return axes, bars
