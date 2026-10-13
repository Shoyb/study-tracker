"""In-app, tray, and optional sound notifications."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSystemTrayIcon


class NotificationBanner(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("NotificationBanner")
        self._label = QLabel()
        self._label.setWordWrap(True)
        close_button = QPushButton("Dismiss")
        close_button.clicked.connect(self.hide)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.addWidget(self._label, 1)
        layout.addWidget(close_button)
        self.hide()

    def notify(
        self,
        title: str,
        message: str,
        level: str,
        *,
        tray: QSystemTrayIcon | None = None,
        sound: bool = False,
    ) -> None:
        colors = {
            "headsup": ("#EAF4FB", "#1F5675"),
            "warning": ("#FFF4D6", "#775500"),
            "urgent": ("#FCE8D5", "#8A3B00"),
            "critical": ("#FDE5E5", "#8B1E1E"),
        }
        background, foreground = colors.get(level, colors["headsup"])
        self.setStyleSheet(
            "#NotificationBanner {"
            f"background: {background}; color: {foreground}; "
            "border-bottom: 1px solid #9AA6AF; }"
        )
        self._label.setText(f"<b>{title}</b> {message}")
        self.show()
        if tray is not None and tray.isVisible():
            tray.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Warning
                if level in {"urgent", "critical"}
                else QSystemTrayIcon.MessageIcon.Information,
                10000,
            )
        if sound:
            try:
                import winsound

                winsound.MessageBeep()
            except (ImportError, RuntimeError):
                pass
