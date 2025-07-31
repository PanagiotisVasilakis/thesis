"""Utility helpers for the ML service."""

import os

__all__ = [
    "get_output_dir",
]


def get_output_dir(directory: str = "output") -> str:
    """Return the absolute path to the output directory.

    Parameters
    ----------
    directory:
        Directory name or relative path where visualization outputs should be
        stored. By default ``"output"`` within the current working directory.

    Returns
    -------
    str
        Absolute path to the resolved output directory. Nested paths are
        supported and the directory is created if it does not already exist.
    """

    abs_dir = os.path.abspath(directory if os.path.isabs(directory) else os.path.join(os.getcwd(), directory))
    os.makedirs(abs_dir, exist_ok=True)
    return abs_dir
