"""Environment variable utilities."""

import os
import logging


def get_neighbor_count_from_env(logger: logging.Logger | None = None) -> int | None:
    """Return the integer value of ``NEIGHBOR_COUNT`` or ``None``.

    Parameters
    ----------
    logger:
        Optional logger for warning messages when parsing fails.

    Returns
    -------
    int | None
        Parsed integer value, or ``None`` if the variable is unset or invalid.
    """
    env_val = os.getenv("NEIGHBOR_COUNT")
    if env_val is not None:
        try:
            return int(env_val)
        except ValueError:
            if logger is not None:
                logger.warning("Invalid NEIGHBOR_COUNT value '%s'; ignoring", env_val)
    return None
