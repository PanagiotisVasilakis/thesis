"""Logging helpers used by all services."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional, Union


def configure_logging(
    level: Union[int, str, None] = None,
    fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    log_file: Optional[str] = None,
) -> None:
    """Configure application-wide logging.

    Parameters
    ----------
    level:
        Numeric or string log level. When ``None`` the ``LOG_LEVEL`` environment
        variable is consulted and defaults to ``INFO``.
    fmt:
        Format string passed to :class:`~logging.Formatter`.
    log_file:
        Optional path to a log file. A :class:`RotatingFileHandler` is attached
        when provided. If ``None``, the ``LOG_FILE`` environment variable is
        used if set.

    The root logger is only configured on the first call so repeated invocations
    have no side effects.
    """

    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO")

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    log_file = log_file or os.getenv("LOG_FILE")

    root = logging.getLogger()
    if root.handlers:
        return

    formatter = logging.Formatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    handlers = [stream_handler]
    if log_file:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5_000_000, backupCount=3
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root.setLevel(level)
    for h in handlers:
        root.addHandler(h)
