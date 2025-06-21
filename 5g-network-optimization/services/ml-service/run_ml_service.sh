#!/bin/bash

# Create necessary directories
mkdir -p output
mkdir -p app/data/collected_data
mkdir -p app/models

# Ensure dependencies are installed
python3.10 -m pip install -r requirements.txt

# Run the model test
echo "Testing ML model..."
python tests/test_model.py

# Start the Flask service
echo "Starting ML service..."
export SIMPLE_MODE=${SIMPLE_MODE:-false}
export A3_HYSTERESIS_DB=${A3_HYSTERESIS_DB:-2.0}
export A3_TTT_S=${A3_TTT_S:-0.0}
python app.py
