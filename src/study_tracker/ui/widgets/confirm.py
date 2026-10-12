"""Reusable confirmation dialog helper."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def confirm(
    parent: QWidget,
    title: str,
    message: str,
    detail: str = "",
) -> bool:
    """Show a Yes/No confirmation dialog.  Returns ``True`` if the user clicks Yes."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    if detail:
        box.setInformativeText(detail)
    box.setIcon(QMessageBox.Icon.Question)
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def alert(parent: QWidget, title: str, message: str) -> None:
    """Show a simple information alert."""
    QMessageBox.information(parent, title, message)


def warn(parent: QWidget, title: str, message: str) -> None:
    """Show a warning dialog."""
    QMessageBox.warning(parent, title, message)
