"""App-wide logging setup.

Every destructive action (scan result, delete, package cache clear) must be
logged here — this is the audit trail the Cleaner tab points users to when
they ask "what did you actually do?" and it's what Undo reads back from.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".local" / "share" / "linux-guardian" / "logs"
LOG_FILE = LOG_DIR / "linux-guardian.log"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("linux_guardian")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"linux_guardian.{name}")
