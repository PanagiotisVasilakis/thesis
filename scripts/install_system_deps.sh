#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y \
    libhdf5-dev \
    libffi-dev \
    libcairo2 \
    libpango-1.0-0 \
    libjpeg-dev

