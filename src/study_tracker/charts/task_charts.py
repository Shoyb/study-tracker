"""Task analytics charts."""

from __future__ import annotations

from study_tracker.charts.style import prepare_axes


def draw_task_time(figure, tasks: list[tuple[str, int, str]]) -> None:
    """Draw the ten tasks with the most allocated study time."""
    axes = figure.subplots()
    prepare_axes(axes, "Time per task")
    ordered = sorted(tasks, key=lambda item: item[1], reverse=True)[:10]
    if not ordered:
        axes.text(0.5, 0.5, "No task-linked study time in this period", ha="center", va="center")
        axes.set_yticks([])
        return
    names, seconds, colors = zip(*reversed(ordered), strict=True)
    axes.barh(names, [value / 3600 for value in seconds], color=colors)


def draw_estimate_vs_actual(figure, tasks: list[tuple[str, int, int]]) -> int:
    """Draw estimate and actual hours; return count without estimates."""
    axes = figure.subplots()
    prepare_axes(axes, "Estimated versus actual")
    estimated = [task for task in tasks if task[1] > 0]
    if not estimated:
        axes.text(0.5, 0.5, "No estimated tasks in this period", ha="center", va="center")
        axes.set_yticks([])
        return len(tasks)
    names, estimates, actuals = zip(*estimated[:10], strict=True)
    positions = range(len(names))
    axes.barh(
        positions, [value / 3600 for value in estimates], color="#CFD8DC", label="Estimate"
    )
    actual_colors = [
        "#F9A825" if actual > estimate else "#1976D2"
        for estimate, actual in zip(estimates, actuals, strict=True)
    ]
    axes.barh(
        positions,
        [value / 3600 for value in actuals],
        color=actual_colors,
        alpha=0.85,
        label="Actual",
    )
    axes.set_yticks(list(positions), names)
    axes.legend(frameon=False)
    return len(tasks) - len(estimated)


def draw_completions(figure, weekly: dict[str, int]) -> None:
    """Draw task completions by week."""
    axes = figure.subplots()
    prepare_axes(axes, "Task completions", "Tasks")
    labels = sorted(weekly)
    axes.bar(range(len(labels)), [weekly[label] for label in labels], color="#1976D2")
    axes.set_xticks(range(len(labels)), labels, rotation=35)
