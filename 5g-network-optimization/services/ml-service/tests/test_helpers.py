"""Utilities for ml-service tests."""

from importlib.util import module_from_spec, spec_from_file_location
from types import ModuleType
from pathlib import Path


def load_module(path: Path, name: str) -> ModuleType:
    """Load a Python module from ``path`` with the given ``name``.

    Parameters
    ----------
    path: Path
        Filesystem path to the module to load.
    name: str
        Module name under which it will be loaded.

    Returns
    -------
    ModuleType
        The loaded module object.
    """
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
