#!/usr/bin/env bash
# Create a virtual environment, install dependencies, and run the test suite.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"

# Create virtual environment if it doesn't exist
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r "$REPO_ROOT/requirements.txt"
pip install -r "$REPO_ROOT/tests/requirements.txt"

# Ensure repository modules are discoverable
export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"

cd "$REPO_ROOT"
pytest -q "$@"
