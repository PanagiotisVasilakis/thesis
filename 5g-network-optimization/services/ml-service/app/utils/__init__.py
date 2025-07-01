"""Utility helpers for the ML service."""

import os


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
        Absolute path to the resolved output directory. The function does not
        create the directory; callers are expected to ensure it exists when
        necessary.
    """

    if os.path.isabs(directory):
        return os.path.abspath(directory)

    return os.path.abspath(os.path.join(os.getcwd(), directory))

