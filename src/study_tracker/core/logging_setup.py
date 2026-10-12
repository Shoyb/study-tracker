"""Logging setup – call ``configure_logging()`` once at startup."""

import logging
import logging.handlers
from pathlib import Path


def configure_logging(log_file: Path, level: int = logging.DEBUG) -> None:
    """Configure root logger with a rotating file handler and a console handler.

    Args:
        log_file: Absolute path to the log file.  Parent directories must exist.
        level: Minimum log level.  Defaults to ``DEBUG``.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove any handlers that might exist (e.g. from pytest's caplog).
    for h in root.handlers[:]:
        root.removeHandler(h)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Rotating file: keep 5 × 1 MB files.
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler at WARNING level so normal use is quiet.
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)
