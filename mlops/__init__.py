"""MLOps toolkit for the thesis project."""

from importlib import import_module as _import_module

# Ensure nested packages are discoverable when third-party ``mlops`` packages
# are installed in the environment. Pytest on some CI runners resolves the
# namespace differently, so we eagerly import the data pipeline utilities.
_import_module("mlops.data_pipeline")

__all__ = ["data_pipeline"]
