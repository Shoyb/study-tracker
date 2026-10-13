"""Weekly consistency charts."""

from __future__ import annotations

from datetime import date

from study_tracker.charts.style import prepare_axes


def draw_weekly_trend(figure, totals: dict[str, int]) -> None:
    """Draw daily time and a seven-day trailing average."""
    axes = figure.subplots()
    prepare_axes(axes, "Weekly trend")
    days = sorted(totals)
    values = [totals[day] / 3600 for day in days]
    average = [
        sum(values[max(0, index - 6) : index + 1]) / min(index + 1, 7)
        for index in range(len(values))
    ]
    axes.plot(values, marker="o", markersize=3, color="#90CAF9", label="Daily")
    axes.plot(average, linewidth=2.4, color="#1976D2", label="7-day average")
    if days:
        ticks = list(range(0, len(days), 7))
        axes.set_xticks(ticks, [date.fromisoformat(days[i]).strftime("%d %b") for i in ticks])
    axes.legend(frameon=False)


def draw_week_overlay(figure, totals: dict[str, int], week_start: str = "monday") -> None:
    """Draw recent weeks overlaid by weekday for consistency comparison."""
    axes = figure.subplots()
    prepare_axes(axes, "Week overlay")
    starts = {"monday": 0, "saturday": 5}
    start_weekday = starts.get(week_start, 0)
    weeks: dict[str, list[float]] = {}
    for day, seconds in sorted(totals.items()):
        current = date.fromisoformat(day)
        start = current.fromordinal(current.toordinal() - (current.weekday() - start_weekday) % 7)
        weekday = (current.weekday() - start_weekday) % 7
        weeks.setdefault(start.isoformat(), [0.0] * 7)[weekday] = seconds / 3600
    for index, (week, values) in enumerate(sorted(weeks.items())[-4:]):
        axes.plot(
            range(7),
            values,
            alpha=0.45 + index * 0.18,
            linewidth=2 if index == len(weeks) - 1 else 1,
            label=week,
        )
    axes.set_xticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    if weeks:
        axes.legend(frameon=False, fontsize="small")
