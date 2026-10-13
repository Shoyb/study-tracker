"""Shared, backend-neutral Matplotlib styling."""

from __future__ import annotations


def prepare_axes(axes, title: str, ylabel: str = "Hours") -> None:
    """Apply the light, compact chart treatment used throughout the app."""
    axes.clear()
    fig = axes.figure
    fig.patch.set_facecolor("#1F2A32")
    axes.set_facecolor("#1F2A32")
    axes.set_title(title, fontweight="bold")
    axes.set_ylabel(ylabel)
    axes.title.set_color("#F0F7FF")
    axes.yaxis.label.set_color("#E6EDF3")
    axes.xaxis.label.set_color("#E6EDF3")
    axes.tick_params(colors="#D9E4EE")
    axes.spines[["top", "right"]].set_visible(False)
    for spine in axes.spines.values():
        spine.set_color("#7F90A0")
    axes.grid(axis="y", color="#3E4F5F", linewidth=0.8)
    axes.set_axisbelow(True)
