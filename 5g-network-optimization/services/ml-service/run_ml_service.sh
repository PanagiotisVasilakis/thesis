#!/bin/bash

set -euo pipefail

usage() {
    echo "Usage: $0 [--skip-if-present]" >&2
    exit 1
}

SKIP_IF_PRESENT=false
for arg in "$@"; do
    case "$arg" in
        --skip-if-present)
            SKIP_IF_PRESENT=true
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $arg" >&2
            usage
            ;;
    esac
done

# Create necessary directories
mkdir -p output
mkdir -p app/data/collected_data
mkdir -p app/models

# Ensure dependencies are installed
PYTHON_BIN=python3.10

check_installed() {
    python -m pip show ml_service >/dev/null 2>&1 && \
        python -m pip check >/dev/null 2>&1
}

if [ "$SKIP_IF_PRESENT" = true ] && [ -n "${VIRTUAL_ENV:-}" ] && check_installed; then
    echo "Using existing virtual environment and dependencies" >&2
else
    echo "Installing dependencies..." >&2
    $PYTHON_BIN -m pip install -r ../../../requirements.txt
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "Error: dependency installation failed with exit code $rc" >&2
        exit $rc
    fi
fi
# Ensure the repository root is on PYTHONPATH so ``services`` can be imported
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}/..:${PYTHONPATH}"

# Run the model test
echo "Testing ML model..."
${PYTHON_BIN} tests/test_model.py

# Start the Flask service
echo "Starting ML service..."
export A3_HYSTERESIS_DB=${A3_HYSTERESIS_DB:-2.0}
export A3_TTT_S=${A3_TTT_S:-0.0}
${PYTHON_BIN} app.py
