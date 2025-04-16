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
python app.py
