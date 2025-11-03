# Complete Deployment and Testing Guide
## 5G Network Optimization with ML-based Handover

This comprehensive guide details every step required to deploy, run, test, and produce results from the 5G Network Optimization system. This system demonstrates how machine learning handles edge cases and scenarios with multiple antennas better than traditional A3-based handover rules.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Deployment Options](#deployment-options)
6. [Data Generation and Collection](#data-generation-and-collection)
7. [Model Training](#model-training)
8. [Testing the System](#testing-the-system)
9. [Monitoring and Metrics](#monitoring-and-metrics)
10. [Generating Thesis Results](#generating-thesis-results)
11. [Troubleshooting](#troubleshooting)

---

## System Overview

The system consists of four main components:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   5G Network Optimization System                        │
│                                                                         │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │                     │            │                              │    │
│  │   NEF Emulator      │<───────────┤    ML Service                │    │
│  │   - 3GPP APIs       │            │    - Antenna Selection       │    │
│  │   - Mobility Models │────────────┤    - QoS Management          │    │
│  │   - Handover Engine │            │    - LightGBM/LSTM Models    │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│           │                                        │                    │
│           ▼                                        ▼                    │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │   PostgreSQL/Mongo  │────────────┤    Prometheus/Grafana        │    │
│  │   - Network State   │            │    - Metrics Collection      │    │
│  │   - UE Data         │            │    - Visualization           │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Features

- **ML-Driven Handovers**: Automatically switches to ML mode when 3+ antennas are configured
- **QoS-Aware Predictions**: Considers service priority, latency, and throughput requirements
- **Fallback Mechanisms**: Falls back to 3GPP A3 rule when ML confidence is low
- **3GPP Mobility Models**: Linear, L-shaped, Random Waypoint, Manhattan Grid, and more
- **Real-time Monitoring**: Prometheus metrics and Grafana dashboards

---

## Prerequisites

### System Requirements

- **Operating System**: Linux, macOS, or Windows with WSL2
- **Docker**: Version 23.0 or higher
- **Docker Compose**: V2 (comes with Docker Desktop)
- **Python**: 3.10 or higher
- **Memory**: Minimum 8GB RAM (16GB recommended)
- **Disk Space**: Minimum 10GB free

### Required Software

#### macOS/Linux:
```bash
# Install system dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    curl \
    git \
    jq \
    libcairo2-dev \
    libjpeg-dev \
    pkg-config \
    python3-dev

# macOS (using Homebrew)
brew install cairo pkg-config jq
```

#### Optional Tools:
- **kubectl**: For Kubernetes deployment (version 1.24+)
- **minikube** or **kind**: For local Kubernetes testing
- **GNU Make**: For using Makefile targets

---

## Installation

### Step 1: Clone the Repository

```bash
cd ~/
git clone <repository-url> thesis
cd thesis
```

### Step 2: Install Python Dependencies

The project provides automated scripts for dependency installation:

```bash
# Install system dependencies
./scripts/install_system_deps.sh

# Install Python packages
./scripts/install_deps.sh

# Alternatively, install manually
pip install -r requirements.txt
```

### Step 3: Set Up Python Path

For running tests and scripts outside Docker:

```bash
export PYTHONPATH="${PWD}:${PWD}/5g-network-optimization/services:${PYTHONPATH}"
```

Add this to your `~/.bashrc` or `~/.zshrc` for persistence.

---

## Configuration

### Environment Variables

Create a `.env` file in the project root (optional, as Docker Compose provides defaults):

```bash
# Core Settings
ML_HANDOVER_ENABLED=1           # Enable ML-based handovers (0=A3 only, 1=ML, unset=auto)
ML_SERVICE_URL=http://ml-service:5050
NEF_API_URL=http://nef-emulator:80

# ML Model Configuration
MODEL_TYPE=lightgbm             # Options: lightgbm, lstm, ensemble, online
LIGHTGBM_TUNE=0                 # Set to 1 to enable hyperparameter tuning
NEIGHBOR_COUNT=3                # Number of neighbor antennas to consider

# A3 Fallback Parameters
A3_HYSTERESIS_DB=2.0            # Hysteresis in dB for A3 event
A3_TTT_S=0.0                    # Time-to-trigger in seconds

# QoS and Confidence
ML_CONFIDENCE_THRESHOLD=0.5     # Minimum confidence for ML predictions
AUTO_RETRAIN=true               # Enable drift-triggered retraining
RETRAIN_THRESHOLD=0.1           # Drift threshold for retraining

# Authentication (for ML service)
AUTH_USERNAME=admin
AUTH_PASSWORD=admin
JWT_SECRET=your-secret-key-change-me

# Logging
LOG_LEVEL=INFO                  # Options: DEBUG, INFO, WARNING, ERROR
LOG_FILE=                       # Leave empty for console-only logging

# Rate Limiting
RATE_LIMIT_PER_MINUTE=100       # API rate limit

# Resource Limits
ASYNC_MODEL_WORKERS=4           # Worker threads for async operations
ASYNC_MODEL_QUEUE_SIZE=1000     # Maximum queue size
```

### Key Configuration Notes

1. **ML_HANDOVER_ENABLED**:
   - `0`: Force A3 rule-based mode
   - `1`: Force ML mode (requires trained model)
   - Unset: Auto-switch to ML when ≥3 antennas exist

2. **MODEL_TYPE**: Choose based on your scenario:
   - `lightgbm`: Fast, good for static scenarios (default)
   - `lstm`: Better for temporal patterns
   - `ensemble`: Combines multiple models
   - `online`: Adapts in real-time

3. **LIGHTGBM_TUNE**: Enable for production deployment to optimize hyperparameters (slower startup)

---

## Deployment Options

### Option 1: Docker Compose (Recommended for Development)

This is the easiest way to run the entire stack locally.

#### 1A: Full Stack with ML

```bash
cd ~/thesis

# Build and start all services (NEF, ML, Prometheus, Grafana)
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build

# Or run in background
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build -d
```

**Services will be available at:**
- NEF Emulator: http://localhost:8080
- ML Service: http://localhost:5050
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)

#### 1B: A3-Only Mode (No ML)

```bash
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

#### 1C: Single Container Mode (ML inside NEF)

```bash
ML_LOCAL=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

### Option 2: Kubernetes Deployment

For production or multi-region deployments.

#### Step 1: Build and Push Images

```bash
cd ~/thesis

# Set your registry
REGISTRY="your-registry.io/your-username"

# Build NEF Emulator
docker build \
  -t ${REGISTRY}/nef-emulator:latest \
  -f 5g-network-optimization/services/nef-emulator/backend/Dockerfile.backend \
  5g-network-optimization/services/nef-emulator

# Build ML Service
docker build \
  -t ${REGISTRY}/ml-service:latest \
  5g-network-optimization/services/ml-service

# Push images
docker push ${REGISTRY}/nef-emulator:latest
docker push ${REGISTRY}/ml-service:latest
```

#### Step 2: Update Manifests

Edit the image references in:
- `5g-network-optimization/deployment/kubernetes/nef-emulator.yaml`
- `5g-network-optimization/deployment/kubernetes/ml-service.yaml`

```yaml
# Example:
image: your-registry.io/your-username/nef-emulator:latest
```

#### Step 3: Deploy to Kubernetes

```bash
cd ~/thesis/5g-network-optimization/deployment/kubernetes

# Deploy NEF Emulator
kubectl apply -f nef-emulator.yaml

# Deploy ML Service
kubectl apply -f ml-service.yaml

# Deploy Monitoring Stack
kubectl apply -f prometheus-grafana.yaml

# Check status
kubectl get pods
kubectl get services
```

#### Step 4: Access Services

```bash
# Port forward to access locally
kubectl port-forward svc/nef-emulator 8080:80
kubectl port-forward svc/ml-service 5050:5050
kubectl port-forward svc/prometheus 9090:9090
kubectl port-forward svc/grafana 3000:3000
```

---

## Data Generation and Collection

### Step 1: Generate Synthetic QoS Dataset

The synthetic generator creates realistic 5G service requests following 3GPP specifications.

```bash
cd ~/thesis

# Generate balanced dataset (eMBB, URLLC, mMTC, default)
python scripts/data_generation/synthetic_generator.py \
  --records 10000 \
  --profile balanced \
  --output output/qos_dataset_balanced.csv \
  --format csv \
  --seed 42

# Generate URLLC-heavy dataset (for low-latency scenarios)
python scripts/data_generation/synthetic_generator.py \
  --records 5000 \
  --profile urllc-heavy \
  --output output/qos_dataset_urllc.json \
  --format json \
  --seed 123

# Custom weights
python scripts/data_generation/synthetic_generator.py \
  --records 8000 \
  --profile balanced \
  --embb-weight 0.6 \
  --urllc-weight 0.3 \
  --mmtc-weight 0.1 \
  --output output/qos_custom.csv \
  --format csv
```

**Dataset Schema:**
- `request_id`: Unique identifier (e.g., req_000001)
- `service_type`: One of embb, urllc, mmtc, default
- `latency_ms`: Round-trip latency requirement
- `reliability_pct`: Delivery success probability (e.g., 99.995)
- `throughput_mbps`: Required throughput
- `priority`: Integer priority (1-10)

### Step 2: Initialize NEF Emulator with Network Topology

Before collecting data, populate the NEF with demo network topology:

```bash
cd ~/thesis/5g-network-optimization/services/nef-emulator

# Ensure NEF is running (from Docker Compose)
# Make sure jq is installed: brew install jq (macOS) or apt-get install jq (Linux)

# Set environment variables (adjust for your .env)
export DOMAIN=localhost
export NGINX_HTTPS=4443
export FIRST_SUPERUSER=admin@my-email.com
export FIRST_SUPERUSER_PASSWORD=pass

# Run initialization script
./backend/app/app/db/init_simple.sh
```

This creates:
- **2 Paths**: NCSRD Library and NCSRD Gate-IIT routes
- **1 gNB**: Base station (gNB1)
- **4 Cells**: Different coverage areas (Administration, Radioisotopes, IIT, Faculty)
- **3 UEs**: User equipment with different speeds and paths

### Step 3: Start UE Movement

Access the NEF Web UI to start UE movement:

```bash
# Open in browser
open http://localhost:8080/dashboard

# Or via API
curl -X POST "http://localhost:8080/api/v1/ue_movement/start" \
  -H "Content-Type: application/json" \
  -d '{"supi": "202010000000001", "speed": 5.0}'
```

### Step 4: Collect Training Data from NEF

```bash
cd ~/thesis/5g-network-optimization/services/ml-service

# Basic collection (300 seconds, 1-second intervals)
python collect_training_data.py \
  --url http://localhost:8080 \
  --username admin \
  --password admin \
  --duration 300 \
  --interval 1 \
  --output data/collected_samples.json

# Collect and train immediately
python collect_training_data.py \
  --url http://localhost:8080 \
  --username admin \
  --password admin \
  --duration 300 \
  --interval 1 \
  --train

# Advanced: Delegate to ML service's async collector
python collect_training_data.py \
  --ml-service-url http://localhost:5050 \
  --username admin \
  --password admin \
  --duration 600 \
  --interval 2
```

---

## Model Training

### Option 1: Automatic Training (Default)

The ML service trains automatically on startup using synthetic data if no model exists:

```bash
# Model trains in background when service starts
# Check logs:
docker compose -f 5g-network-optimization/docker-compose.yml logs ml-service
```

### Option 2: Manual Training via API

```bash
# Get JWT token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# Train with collected data
curl -X POST http://localhost:5050/api/train \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @data/collected_samples.json

# Or use async training (non-blocking)
curl -X POST http://localhost:5050/api/train-async \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @data/collected_samples.json
```

### Option 3: Training with Hyperparameter Tuning

```bash
# Set environment variable
export LIGHTGBM_TUNE=1
export LIGHTGBM_TUNE_N_ITER=20
export LIGHTGBM_TUNE_CV=5

# Restart ML service
docker compose -f 5g-network-optimization/docker-compose.yml restart ml-service

# Check tuning results in logs
docker compose -f 5g-network-optimization/docker-compose.yml logs -f ml-service
```

### Option 4: Training Script (Standalone)

```bash
cd ~/thesis

# Activate virtual environment if needed
source venv/bin/activate

# Train using synthetic data
python -c "
from ml_service.app.initialization.model_init import ModelManager
from ml_service.app.utils.synthetic_data import generate_synthetic_training_data

# Generate data
data = generate_synthetic_training_data(1000)

# Train model
model = ModelManager.get_instance('output/test_model.joblib')
metrics = model.train(data)

print(f'Training complete: {metrics}')
"
```

### Check Model Status

```bash
# Check model health
curl http://localhost:5050/api/model-health | jq

# List available model versions
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/models | jq

# Switch to a different model version
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5050/api/models/1.0.0"
```

---

## Testing the System

### Step 1: Unit and Integration Tests

```bash
cd ~/thesis

# Run all tests with coverage
./scripts/run_tests.sh

# Run specific test categories
pytest tests/data_generation/          # Data generation tests
pytest tests/mlops/                    # MLOps and QoS tests
pytest 5g-network-optimization/services/ml-service/tests/  # ML service tests
pytest 5g-network-optimization/services/nef-emulator/tests/  # NEF tests

# Run with verbose output
pytest -v

# Run specific test
pytest tests/mlops/test_qos_feature_ranges.py -v
```

### Step 2: Test ML Predictions

```bash
# Get authentication token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# Basic prediction
curl -X POST http://localhost:5050/api/predict \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ue_id": "test-ue-001",
    "latitude": 100.0,
    "longitude": 50.0,
    "connected_to": "antenna_1",
    "rf_metrics": {
      "antenna_1": {"rsrp": -80, "sinr": 15, "rsrq": -9},
      "antenna_2": {"rsrp": -90, "sinr": 10, "rsrq": -12},
      "antenna_3": {"rsrp": -85, "sinr": 12, "rsrq": -10}
    }
  }' | jq

# QoS-aware prediction
curl -X POST http://localhost:5050/api/predict-with-qos \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ue_id": "test-ue-002",
    "latitude": 200.0,
    "longitude": 150.0,
    "connected_to": "antenna_2",
    "rf_metrics": {
      "antenna_1": {"rsrp": -75, "sinr": 18, "rsrq": -8},
      "antenna_2": {"rsrp": -82, "sinr": 14, "rsrq": -10},
      "antenna_3": {"rsrp": -88, "sinr": 11, "rsrq": -11}
    },
    "service_type": "urllc",
    "service_priority": 9,
    "latency_requirement_ms": 5.0,
    "throughput_requirement_mbps": 2.0,
    "reliability_pct": 99.999
  }' | jq
```

### Step 3: Test Handover Decisions

```bash
# Via NEF emulator API (requires UE to be registered)
curl -X POST "http://localhost:8080/api/v1/ml/handover?ue_id=202010000000001" \
  -H "Authorization: Bearer $NEF_TOKEN"

# Check handover history
curl "http://localhost:8080/api/v1/ml/state/202010000000001" \
  -H "Authorization: Bearer $NEF_TOKEN" | jq
```

### Step 4: Verify ML vs A3 Behavior

```bash
# Test with ML enabled
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up -d
# Observe handover decisions in logs
docker compose -f 5g-network-optimization/docker-compose.yml logs -f nef-emulator | grep "handover"

# Stop and test with A3 only
docker compose -f 5g-network-optimization/docker-compose.yml down
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up -d
# Compare handover behavior
docker compose -f 5g-network-optimization/docker-compose.yml logs -f nef-emulator | grep "handover"
```

---

## Monitoring and Metrics

### Step 1: Access Monitoring Dashboards

```bash
# Prometheus (metrics database)
open http://localhost:9090

# Grafana (visualization)
open http://localhost:3000
# Login: admin / admin
```

### Step 2: Key Metrics to Monitor

#### ML Service Metrics:
```promql
# Prediction requests
ml_prediction_requests_total

# Prediction latency (95th percentile)
histogram_quantile(0.95, rate(ml_prediction_latency_seconds_bucket[5m]))

# Model confidence by antenna
ml_prediction_confidence_avg{antenna_id="antenna_1"}

# Training duration
ml_model_training_duration_seconds

# Data drift score
ml_data_drift_score

# Error rate
ml_prediction_error_rate
```

#### NEF Emulator Metrics:
```promql
# Handover decisions (applied vs skipped)
nef_handover_decisions_total{outcome="applied"}
nef_handover_decisions_total{outcome="skipped"}

# ML fallbacks (when confidence too low)
nef_handover_fallback_total

# QoS compliance
nef_handover_compliance_total{outcome="ok"}
nef_handover_compliance_total{outcome="failed"}

# Request latency
histogram_quantile(0.95, rate(nef_request_duration_seconds_bucket[5m]))
```

### Step 3: Export Metrics for Analysis

```bash
# Query Prometheus directly
curl "http://localhost:9090/api/v1/query?query=ml_prediction_requests_total" | jq

# Query time series data
curl "http://localhost:9090/api/v1/query_range?query=ml_prediction_confidence_avg&start=$(date -u -d '1 hour ago' +%s)&end=$(date -u +%s)&step=60" | jq > metrics_export.json
```

### Step 4: Check ML Service Health

```bash
# Basic health
curl http://localhost:5050/api/health | jq

# Model health (detailed)
curl http://localhost:5050/api/model-health | jq

# NEF connectivity status
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/nef-status | jq

# Circuit breaker status (if using NEF client features)
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/v1/circuit-breakers/status | jq
```

---

## Generating Thesis Results

### Step 1: Generate Visualization Assets

```bash
cd ~/thesis

# Generate all presentation assets (coverage maps, trajectories)
python scripts/generate_presentation_assets.py

# Assets are saved to:
# - presentation_assets/antenna_coverage_*.png
# - presentation_assets/linear/trajectory_*.png
# - presentation_assets/l_shaped/trajectory_*.png
```

### Step 2: Generate Antenna Coverage Map

```bash
# Via API endpoint
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5050/api/visualization/coverage-map" \
  --output coverage_map.png

# Check output directory
ls -lh output/coverage/
```

### Step 3: Generate UE Trajectory Visualizations

```bash
# Start UE movement in NEF Web UI or via API
curl -X POST "http://localhost:8080/api/v1/ue_movement/start" \
  -H "Authorization: Bearer $NEF_TOKEN" \
  -d '{"supi": "202010000000001", "speed": 10.0}'

# Let it run for a few minutes, then get trajectory
TRAJECTORY=$(curl "http://localhost:8080/api/v1/ue_movement/202010000000001" \
  -H "Authorization: Bearer $NEF_TOKEN")

# Send to visualization endpoint
curl -X POST http://localhost:5050/api/visualization/trajectory \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$TRAJECTORY" \
  --output trajectory.png

# Check output
ls -lh output/trajectory/
```

### Step 4: Compare ML vs A3 Performance

Create a comparison script:

```bash
cat > ~/thesis/scripts/compare_ml_vs_a3.sh << 'EOF'
#!/bin/bash
set -euo pipefail

echo "=== ML vs A3 Handover Comparison ==="

# Test with ML
echo "Starting test with ML enabled..."
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up -d
sleep 30  # Wait for startup

# Collect ML metrics
echo "Collecting ML metrics..."
ML_HANDOVERS=$(curl -s "http://localhost:9090/api/v1/query?query=nef_handover_decisions_total{outcome=\"applied\"}" | jq -r '.data.result[0].value[1]')
ML_FALLBACKS=$(curl -s "http://localhost:9090/api/v1/query?query=nef_handover_fallback_total" | jq -r '.data.result[0].value[1]')

echo "ML Handovers: $ML_HANDOVERS"
echo "ML Fallbacks: $ML_FALLBACKS"

# Stop ML mode
docker compose -f 5g-network-optimization/docker-compose.yml down

# Test with A3
echo "Starting test with A3 only..."
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up -d
sleep 30

# Collect A3 metrics
echo "Collecting A3 metrics..."
A3_HANDOVERS=$(curl -s "http://localhost:9090/api/v1/query?query=nef_handover_decisions_total{outcome=\"applied\"}" | jq -r '.data.result[0].value[1]')

echo "A3 Handovers: $A3_HANDOVERS"

# Generate comparison report
cat > comparison_report.txt << REPORT
=== ML vs A3 Handover Comparison ===
Generated: $(date)

ML Mode:
  - Total Handovers: $ML_HANDOVERS
  - Fallbacks to A3: $ML_FALLBACKS
  - ML Success Rate: $(echo "scale=2; (1 - $ML_FALLBACKS/$ML_HANDOVERS) * 100" | bc)%

A3 Mode:
  - Total Handovers: $A3_HANDOVERS

Improvement: ML made $(echo "$ML_HANDOVERS - $A3_HANDOVERS" | bc) more handover decisions

REPORT

cat comparison_report.txt
EOF

chmod +x ~/thesis/scripts/compare_ml_vs_a3.sh
./scripts/compare_ml_vs_a3.sh
```

### Step 5: Generate Statistical Analysis

```python
# Create analysis script
cat > ~/thesis/scripts/analyze_results.py << 'PYTHON'
#!/usr/bin/env python3
"""Analyze ML service performance metrics."""

import json
import requests
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta

# Query Prometheus
PROM_URL = "http://localhost:9090"

def query_prometheus(query, hours=1):
    """Query Prometheus for time series data."""
    end = datetime.now()
    start = end - timedelta(hours=hours)
    
    params = {
        'query': query,
        'start': int(start.timestamp()),
        'end': int(end.timestamp()),
        'step': '60'  # 1-minute intervals
    }
    
    resp = requests.get(f"{PROM_URL}/api/v1/query_range", params=params)
    return resp.json()

# Collect metrics
print("Collecting metrics...")
confidence_data = query_prometheus('ml_prediction_confidence_avg')
latency_data = query_prometheus('rate(ml_prediction_latency_seconds_sum[5m]) / rate(ml_prediction_latency_seconds_count[5m])')
handover_data = query_prometheus('rate(nef_handover_decisions_total[5m])')

# Create visualizations
fig, axes = plt.subplots(2, 2, figsize=(15, 10))

# Plot 1: Confidence over time
if confidence_data['data']['result']:
    for result in confidence_data['data']['result']:
        antenna = result['metric'].get('antenna_id', 'unknown')
        values = result['values']
        timestamps = [datetime.fromtimestamp(v[0]) for v in values]
        confidences = [float(v[1]) for v in values]
        axes[0, 0].plot(timestamps, confidences, label=antenna)
    
    axes[0, 0].set_title('ML Prediction Confidence Over Time')
    axes[0, 0].set_xlabel('Time')
    axes[0, 0].set_ylabel('Confidence')
    axes[0, 0].legend()
    axes[0, 0].grid(True)

# Plot 2: Prediction latency
if latency_data['data']['result']:
    values = latency_data['data']['result'][0]['values']
    timestamps = [datetime.fromtimestamp(v[0]) for v in values]
    latencies = [float(v[1]) * 1000 for v in values]  # Convert to ms
    axes[0, 1].plot(timestamps, latencies, color='green')
    axes[0, 1].set_title('Prediction Latency')
    axes[0, 1].set_xlabel('Time')
    axes[0, 1].set_ylabel('Latency (ms)')
    axes[0, 1].grid(True)

# Plot 3: Handover rate
if handover_data['data']['result']:
    for result in handover_data['data']['result']:
        outcome = result['metric'].get('outcome', 'unknown')
        values = result['values']
        timestamps = [datetime.fromtimestamp(v[0]) for v in values]
        rates = [float(v[1]) for v in values]
        axes[1, 0].plot(timestamps, rates, label=outcome)
    
    axes[1, 0].set_title('Handover Decision Rate')
    axes[1, 0].set_xlabel('Time')
    axes[1, 0].set_ylabel('Rate (per second)')
    axes[1, 0].legend()
    axes[1, 0].grid(True)

# Plot 4: Summary statistics
metrics_summary = {
    'Metric': ['Avg Confidence', 'Avg Latency (ms)', 'Total Handovers'],
    'Value': [
        sum([float(v[1]) for v in confidence_data['data']['result'][0]['values']]) / len(confidence_data['data']['result'][0]['values']) if confidence_data['data']['result'] else 0,
        sum(latencies) / len(latencies) if latencies else 0,
        len(handover_data['data']['result']) if handover_data['data']['result'] else 0
    ]
}
df = pd.DataFrame(metrics_summary)
axes[1, 1].axis('tight')
axes[1, 1].axis('off')
table = axes[1, 1].table(cellText=df.values, colLabels=df.columns, cellLoc='center', loc='center')
table.auto_set_font_size(False)
table.set_fontsize(10)
axes[1, 1].set_title('Summary Statistics')

plt.tight_layout()
plt.savefig('output/performance_analysis.png', dpi=300)
print(f"Saved analysis to output/performance_analysis.png")

# Generate CSV report
df.to_csv('output/metrics_summary.csv', index=False)
print("Saved summary to output/metrics_summary.csv")
PYTHON

chmod +x ~/thesis/scripts/analyze_results.py
python3 scripts/analyze_results.py
```

### Step 6: Generate Mobility Model Examples

```bash
cd ~/thesis

# Run NEF mobility tests (generates trajectory plots)
pytest 5g-network-optimization/services/nef-emulator/tests/test_mobility_models.py \
  --tb=short -v

# Check generated plots
ls -lh output/mobility/
```

### Step 7: Build Final Presentation PDF

```bash
cd ~/thesis

# Generate all assets first
python scripts/generate_presentation_assets.py

# Build PDF with all visualizations
python scripts/build_presentation_pdf.py

# Output: overview.pdf in project root
ls -lh overview.pdf
```

---

## Troubleshooting

### Common Issues and Solutions

#### 1. Docker Compose Fails to Start

**Error**: `Cannot connect to Docker daemon`

**Solution**:
```bash
# Check Docker is running
docker ps

# If not, start Docker Desktop (macOS/Windows)
# Or start Docker daemon (Linux)
sudo systemctl start docker
```

#### 2. ML Service Model Not Training

**Error**: `Model initialization failed`

**Solution**:
```bash
# Check logs
docker compose -f 5g-network-optimization/docker-compose.yml logs ml-service

# Manually trigger training
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

curl -X POST http://localhost:5050/api/train \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{"ue_id":"test","latitude":0,"longitude":0,"connected_to":"antenna_1","label":"antenna_1"}]'
```

#### 3. Authentication Errors

**Error**: `401 Unauthorized`

**Solution**:
```bash
# Verify credentials match environment variables
echo $AUTH_USERNAME
echo $AUTH_PASSWORD

# Get fresh token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

echo $TOKEN
```

#### 4. Prometheus Not Scraping Metrics

**Error**: Targets down in Prometheus UI

**Solution**:
```bash
# Check if services are accessible
curl http://localhost:8080/metrics
curl http://localhost:5050/metrics

# Verify Prometheus config
docker compose -f 5g-network-optimization/docker-compose.yml exec prometheus \
  cat /etc/prometheus/prometheus.yml

# Restart Prometheus
docker compose -f 5g-network-optimization/docker-compose.yml restart prometheus
```

#### 5. NEF Database Not Initializing

**Error**: `init_simple.sh` fails

**Solution**:
```bash
# Ensure NEF is fully started
docker compose -f 5g-network-optimization/docker-compose.yml logs nef-emulator | grep "Uvicorn running"

# Check jq is installed
which jq || brew install jq  # macOS
which jq || sudo apt-get install jq  # Linux

# Manually set environment variables
export DOMAIN=localhost
export NGINX_HTTPS=8080  # For Docker Compose use HTTP port
export FIRST_SUPERUSER=admin@my-email.com
export FIRST_SUPERUSER_PASSWORD=pass

# Re-run initialization
cd 5g-network-optimization/services/nef-emulator
./backend/app/app/db/init_simple.sh
```

#### 6. Out of Memory Errors

**Solution**:
```bash
# Increase Docker memory limit (Docker Desktop > Settings > Resources)
# Or reduce model complexity
export LIGHTGBM_TUNE=0
export NEIGHBOR_COUNT=2

# Restart with reduced workers
export ASYNC_MODEL_WORKERS=2
docker compose -f 5g-network-optimization/docker-compose.yml restart ml-service
```

#### 7. Tests Failing

**Solution**:
```bash
# Ensure all dependencies installed
pip install -r requirements.txt
pip install -r tests/requirements.txt

# Set PYTHONPATH
export PYTHONPATH="${PWD}:${PWD}/5g-network-optimization/services"

# Run with verbose output
pytest -vvs tests/

# Run specific failing test
pytest tests/mlops/test_qos_feature_ranges.py::test_qos_validation -vvs
```

#### 8. Grafana Dashboard Not Loading

**Solution**:
```bash
# Check Prometheus data source
# In Grafana UI: Configuration > Data Sources > Add Prometheus
# URL: http://prometheus:9090

# Reload dashboards
docker compose -f 5g-network-optimization/docker-compose.yml restart grafana

# Import dashboard manually
# Dashboards > Import > Upload 5g-network-optimization/monitoring/grafana/dashboards/ml_service.json
```

---

## Advanced Scenarios

### Scenario 1: Multi-Antenna Edge Case Testing

Test how ML handles complex multi-antenna scenarios:

```bash
# Create multiple antennas via NEF API
for i in {5..10}; do
  curl -X POST "http://localhost:8080/api/v1/Cells" \
    -H "Authorization: Bearer $NEF_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"cell_id\": \"CELL$(printf %03d $i)\",
      \"name\": \"cell$i\",
      \"description\": \"Test antenna $i\",
      \"gNB_id\": 1,
      \"latitude\": $(echo "37.997 + 0.001 * $i" | bc),
      \"longitude\": $(echo "23.818 + 0.001 * $i" | bc),
      \"radius\": 100
    }"
done

# ML should automatically enable
# Check mode
curl "http://localhost:8080/api/v1/ml/state/202010000000001" | jq '.use_ml'
```

### Scenario 2: QoS Priority Testing

```bash
# Test different service types
for service in urllc embb mmtc default; do
  echo "Testing $service..."
  curl -X POST http://localhost:5050/api/predict-with-qos \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"ue_id\": \"test-$service\",
      \"latitude\": 100,
      \"longitude\": 50,
      \"connected_to\": \"antenna_1\",
      \"service_type\": \"$service\",
      \"service_priority\": 8,
      \"rf_metrics\": {
        \"antenna_1\": {\"rsrp\": -80, \"sinr\": 15},
        \"antenna_2\": {\"rsrp\": -85, \"sinr\": 12}
      }
    }" | jq '.qos_compliance'
done
```

### Scenario 3: Drift Detection and Retraining

```bash
# Enable drift monitoring
export AUTO_RETRAIN=true
export RETRAIN_THRESHOLD=0.05

# Send many predictions with changing patterns
for i in {1..1000}; do
  curl -X POST http://localhost:5050/api/predict \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"ue_id\": \"drift-test-$i\",
      \"latitude\": $((RANDOM % 1000)),
      \"longitude\": $((RANDOM % 1000)),
      \"connected_to\": \"antenna_1\",
      \"rf_metrics\": {
        \"antenna_1\": {\"rsrp\": $((- RANDOM % 40 - 60)), \"sinr\": $((RANDOM % 20))}
      }
    }" > /dev/null
done

# Check drift score
curl http://localhost:5050/metrics | grep ml_data_drift_score
```

---

## Performance Benchmarking

```bash
# Create benchmark script
cat > ~/thesis/scripts/benchmark.sh << 'EOF'
#!/bin/bash

echo "=== Performance Benchmark ==="

# Warm up
for i in {1..10}; do
  curl -s -X POST http://localhost:5050/api/predict \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"ue_id":"warmup","latitude":0,"longitude":0,"connected_to":"antenna_1","rf_metrics":{"antenna_1":{"rsrp":-80,"sinr":15}}}' > /dev/null
done

# Benchmark
START=$(date +%s%3N)
for i in {1..100}; do
  curl -s -X POST http://localhost:5050/api/predict \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"ue_id\":\"bench-$i\",\"latitude\":$i,\"longitude\":$i,\"connected_to\":\"antenna_1\",\"rf_metrics\":{\"antenna_1\":{\"rsrp\":-80,\"sinr\":15}}}" > /dev/null
done
END=$(date +%s%3N)

DURATION=$((END - START))
AVG=$((DURATION / 100))

echo "100 predictions in ${DURATION}ms"
echo "Average latency: ${AVG}ms per prediction"
EOF

chmod +x ~/thesis/scripts/benchmark.sh
./scripts/benchmark.sh
```

---

## Summary Checklist

Use this checklist to ensure complete system validation:

- [ ] Dependencies installed (`./scripts/install_deps.sh`)
- [ ] Docker Compose stack running (`docker compose up`)
- [ ] NEF emulator accessible (http://localhost:8080)
- [ ] ML service accessible (http://localhost:5050)
- [ ] Prometheus collecting metrics (http://localhost:9090)
- [ ] Grafana dashboards loaded (http://localhost:3000)
- [ ] NEF database initialized (`init_simple.sh`)
- [ ] Synthetic QoS dataset generated
- [ ] ML model trained (check `/api/model-health`)
- [ ] Predictions working (`/api/predict`)
- [ ] QoS predictions working (`/api/predict-with-qos`)
- [ ] Handovers tested (ML vs A3)
- [ ] Unit tests passing (`pytest`)
- [ ] Coverage maps generated
- [ ] Trajectory plots generated
- [ ] Performance analysis completed
- [ ] Metrics exported for thesis
- [ ] Comparison report generated (ML vs A3)

---

## Next Steps for Thesis

1. **Collect Extended Dataset**: Run system for 24+ hours collecting real mobility data
2. **Statistical Analysis**: Analyze handover success rates, latency improvements, QoS compliance
3. **Comparative Study**: Document ML improvements over A3 in multi-antenna scenarios
4. **Edge Case Documentation**: Demonstrate ML handling of complex antenna topologies
5. **Performance Metrics**: Compile latency, throughput, and reliability measurements
6. **Visualization Gallery**: Generate comprehensive set of coverage maps, trajectories, and performance graphs

---

## References

- Main README: `/README.md`
- QoS Architecture: `/docs/architecture/qos.md`
- ML Service Documentation: `/5g-network-optimization/services/ml-service/README.md`
- NEF Emulator Documentation: `/5g-network-optimization/services/nef-emulator/README.md`
- Synthetic Data Generator: `/docs/qos/synthetic_qos_dataset.md`
- Kubernetes Deployment: `/5g-network-optimization/deployment/kubernetes/README.md`

---

**Document Version**: 1.0  
**Last Updated**: November 2025  
**Maintained By**: Thesis Project Team

