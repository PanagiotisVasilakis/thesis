"""Pytest configuration for rf_model_tests.

Ensures correct import paths are set up for rf_models imports.

NOTE: This directory is named rf_model_tests (not rf_models) to avoid
shadowing the rf_models package from nef-emulator during pytest imports.
"""
import sys
from pathlib import Path

# Setup import paths
_tests_dir = Path(__file__).parent.parent.absolute()
_project_root = _tests_dir.parent
_nef_emulator_dir = _project_root / "5g-network-optimization" / "services" / "nef-emulator"
_nef_backend_dir = _nef_emulator_dir / "backend"

for _path in [str(_project_root), str(_nef_emulator_dir), str(_nef_backend_dir)]:
    if _path not in sys.path:
        sys.path.insert(0, _path)
