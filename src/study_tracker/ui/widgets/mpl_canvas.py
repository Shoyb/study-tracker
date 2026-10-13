"""A reusable Qt widget that owns one Matplotlib figure."""

from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class MplCanvas(FigureCanvasQTAgg):
    """Canvas that reuses its figure across redraws to avoid memory growth."""

    def __init__(self, parent=None, *, height: float = 3.0) -> None:
        self.figure = Figure(figsize=(6, height), layout="constrained")
        super().__init__(self.figure)
        self.setParent(parent)
        self.setMinimumHeight(round(height * 100))
        self._hover_connections: list[int] = []

    def redraw(self, draw_function, *args, **kwargs):
        """Clear the existing figure and invoke a backend-neutral chart function."""
        self.figure.clear()
        for connection in self._hover_connections:
            self.mpl_disconnect(connection)
        self._hover_connections.clear()
        result = draw_function(self.figure, *args, **kwargs)
        self.draw_idle()
        return result

    def enable_bar_hover(self, axes, bars, labels: list[str], on_click=None) -> None:
        """Show a small tooltip over chart bars and optionally handle clicks."""
        annotation = axes.annotate(
            "",
            xy=(0, 0),
            xytext=(10, 10),
            textcoords="offset points",
            bbox={"boxstyle": "round", "fc": "white", "ec": "#90A4AE"},
        )
        annotation.set_visible(False)

        def bar_at(event):
            if event.inaxes != axes:
                return None
            for index, bar in enumerate(bars):
                if bar.contains(event)[0]:
                    return index, bar
            return None

        def on_motion(event) -> None:
            found = bar_at(event)
            if found is None:
                if annotation.get_visible():
                    annotation.set_visible(False)
                    self.draw_idle()
                return
            index, bar = found
            annotation.xy = (bar.get_x() + bar.get_width() / 2, bar.get_height())
            annotation.set_text(labels[index])
            annotation.set_visible(True)
            self.draw_idle()

        def on_press(event) -> None:
            found = bar_at(event)
            if found is not None and on_click is not None:
                on_click(found[0])

        self._hover_connections.extend(
            [
                self.mpl_connect("motion_notify_event", on_motion),
                self.mpl_connect("button_press_event", on_press),
            ]
        )
