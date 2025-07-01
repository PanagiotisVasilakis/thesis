#!/usr/bin/env bash
# Install Python dependencies for local development and CI
set -euo pipefail

python -m pip install -r requirements.txt

# Install the ML service as an editable package so that tests can
# import `ml_service.*` modules without adjusting PYTHONPATH.
python -m pip install -e 5g-network-optimization/services/ml-service
