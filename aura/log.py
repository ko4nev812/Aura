"""Logging setup: opt-in rotating file logs, 7-day retention (see ТЗ §8)."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

MAX_LOG_FILES = 7
LOG_FILENAME = "aura.log"


def setup_logging(level: str = "INFO", log_dir: Path | None = None, file_logging: bool = False) -> logging.Logger:
    """Configure root loggers for the app.

    Console logging is always on. File logging is opt-in and keeps at most
    ``MAX_LOG_FILES`` daily rotated files (7 days retention).
    """
    root = logging.getLogger("aura")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if file_logging and log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_dir / LOG_FILENAME,
            when="midnight",
            backupCount=MAX_LOG_FILES,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"aura.{name}")
