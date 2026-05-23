"""Pytest configuration and shared fixtures for thesis tests.

This module provides portable path resolution for all test files,
eliminating hardcoded absolute paths.
"""
import sys
from pathlib import Path

# Resolve project paths dynamically
TESTS_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = TESTS_DIR.parent
NEF_EMULATOR_DIR = PROJECT_ROOT / "5g-network-optimization" / "services" / "nef-emulator"
NEF_BACKEND_DIR = NEF_EMULATOR_DIR / "backend"
NEF_APP_ROOT = NEF_BACKEND_DIR / "app"
ML_SERVICE_DIR = PROJECT_ROOT / "5g-network-optimization" / "services" / "ml-service"

# Add paths to sys.path for imports
def setup_import_paths():
    """Add all necessary paths to sys.path for test imports.
    
    This function is called automatically by pytest via conftest.py,
    but can also be called manually in test files if needed.
    """
    desired_order = [
        str(NEF_APP_ROOT),
        str(NEF_BACKEND_DIR),
        str(NEF_EMULATOR_DIR),
        str(PROJECT_ROOT),
        str(ML_SERVICE_DIR),
    ]

    for path in reversed(desired_order):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


# Auto-setup on import
setup_import_paths()


def pytest_configure(config):
    """Pytest hook called after command line options have been parsed."""
    # Ensure paths are set up before any tests run
    setup_import_paths()


# Export path constants for tests that need explicit paths
__all__ = [
    'TESTS_DIR',
    'PROJECT_ROOT',
    'NEF_EMULATOR_DIR',
    'NEF_BACKEND_DIR',
    'NEF_APP_ROOT',
    'ML_SERVICE_DIR',
    'setup_import_paths',
]
