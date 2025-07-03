#!/bin/bash

# Create necessary directories
mkdir -p output
mkdir -p app/data/collected_data
mkdir -p app/models

# Ensure dependencies are installed
PYTHON_BIN=python3.10
$PYTHON_BIN -m pip install -r ../../../requirements.txt
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
