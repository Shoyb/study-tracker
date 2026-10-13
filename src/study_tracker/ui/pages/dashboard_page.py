"""The at-a-glance study Dashboard."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from study_tracker.charts.daily_bar import draw_daily_bars
from study_tracker.core.formatting import format_duration
from study_tracker.services.stats_service import dashboard_stats
from study_tracker.ui.signals import AppSignals
from study_tracker.ui.widgets.mpl_canvas import MplCanvas


class DashboardPage(QWidget):
    """Summary tiles calculated by the shared statistics service."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        signals: AppSignals,
        clock,
        on_day_selected: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._clock = clock
        self._on_day_selected = on_day_selected
        self._range = QComboBox()
        self._tiles: dict[str, QLabel] = {}
        self._build_ui()
        signals.sessions_changed.connect(self.refresh)
        signals.tasks_changed.connect(self.refresh)
        signals.settings_changed.connect(self.refresh)
        signals.day_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        header = QHBoxLayout()
        header.addWidget(QLabel("<h2>Dashboard</h2>"))
        header.addStretch()
        header.addWidget(QLabel("Summary range:"))
        ranges = (
            ("Last 7 days", 7),
            ("Last 14 days", 14),
            ("Last 30 days", 30),
            ("Last 90 days", 90),
        )
        for label, days in ranges:
            self._range.addItem(label, days)
        self._range.setCurrentIndex(2)
        self._range.currentIndexChanged.connect(self.refresh)
        header.addWidget(self._range)
        root.addLayout(header)

        grid = QGridLayout()
        labels = (
            ("today", "Today"), ("week", "This week"), ("month", "This month"),
            ("average", "Daily average"), ("sessions", "Sessions in range"),
            ("streak", "Current streak"), ("tasks", "Tasks completed"), ("rate", "Completion rate"),
        )
        for index, (key, title) in enumerate(labels):
            tile = QLabel()
            tile.setMinimumHeight(92)
            tile.setStyleSheet(
                "background: #1F2A32; border: 1px solid #3A4F5F; border-radius: 10px; "
                "padding: 12px; font-size: 11pt; color: #E6EDF3;"
            )
            tile.setTextFormat(Qt.TextFormat.RichText)
            self._tiles[key] = tile
            grid.addWidget(tile, index // 4, index % 4)
            tile.setText(f"<span style='color:#52606D'>{title}</span><br><b>—</b>")
        root.addLayout(grid)
        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #D9E4EE; padding-top: 12px;")
        root.addWidget(self._detail)
        self._daily_chart = MplCanvas(height=2.8)
        self._daily_chart.setStyleSheet(
            "background: #1F2A32; border: 1px solid #3A4F5F; border-radius: 10px;"
        )
        root.addWidget(self._daily_chart)
        root.addStretch()

    def refresh(self) -> None:
        if not self._conn:
            return
        data = dashboard_stats(
            self._conn, today=self._clock.local_date(), range_days=int(self._range.currentData())
        )
        values = {
            "today": format_duration(data.today_secs),
            "week": format_duration(data.week_secs),
            "month": format_duration(data.month_secs),
            "average": format_duration(round(data.daily_average_secs)),
            "sessions": str(data.session_count),
            "streak": f"{data.current_streak} day{'s' if data.current_streak != 1 else ''}",
            "tasks": f"{data.completed_tasks} completed",
            "rate": "—" if data.completion_rate is None else f"{data.completion_rate:.0f}%",
        }
        titles = {
            "today": "Today",
            "week": "This week",
            "month": "This month",
            "average": "Daily average",
            "sessions": "Sessions in range",
            "streak": "Current streak",
            "tasks": "Tasks completed",
            "rate": "Completion rate",
        }
        for key, value in values.items():
            text = f"<span style='color:#D9E4EE'>{titles[key]}</span><br><b>{value}</b>"
            self._tiles[key].setText(text)
        self._detail.setText(
            f"{data.open_tasks} task{'s' if data.open_tasks != 1 else ''} open in this period. "
            "See Analytics for subject and task comparisons."
        )
        axes, bars = self._daily_chart.redraw(
            draw_daily_bars, data.daily, self._clock.local_date()
        )
        dates = sorted(data.daily)
        labels = [
            f"{day}: {format_duration(data.daily[day])}, "
            f"{data.daily_session_counts[day]} session(s)"
            for day in dates
        ]
        self._daily_chart.enable_bar_hover(
            axes,
            bars,
            labels,
            on_click=lambda index: self._on_day_selected and self._on_day_selected(dates[index]),
        )
