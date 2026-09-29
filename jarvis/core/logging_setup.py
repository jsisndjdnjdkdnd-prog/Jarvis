from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
NOISY_LOGGERS: tuple[str, ...] = ("httpx", "httpcore", "openai", "urllib3", "PIL", "comtypes", "asyncio")


def configure_logging(level: str, log_file: Path | None) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter(LOG_FORMAT)
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
