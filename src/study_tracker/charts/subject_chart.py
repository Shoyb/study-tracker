"""Subject distribution bar chart."""

from __future__ import annotations

from study_tracker.charts.style import prepare_axes


def draw_subject_distribution(figure, subjects: list[tuple[str, int, str]]) -> None:
    """Draw subjects sorted by time with their configured colours."""
    axes = figure.subplots()
    prepare_axes(axes, "Time by subject")
    ordered = sorted(subjects, key=lambda item: item[1])
    if not ordered:
        axes.text(0.5, 0.5, "No study time recorded in this period", ha="center", va="center")
        axes.set_yticks([])
        return
    names, seconds, colors = zip(*ordered, strict=True)
    axes.barh(names, [value / 3600 for value in seconds], color=colors)
