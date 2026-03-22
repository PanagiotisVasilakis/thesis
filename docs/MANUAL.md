# Operations Manual

This guide provides comprehensive instructions for deploying, configuring, and operating the 5G Network Optimization system.

## 📋 Table of Contents
1. [Prerequisites & Installation](#prerequisites--installation)
2. [Configuration](#configuration)
3. [Deployment Options](#deployment-options)
4. [Data Generation](#data-generation)
5. [Model Training](#model-training)
6. [Monitoring & Metrics](#monitoring--metrics)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites & Installation

### System Requirements
- **OS**: Linux, macOS, or Windows (WSL2)
- **Docker**: v23.0+
- **Python**: 3.10+
- **Resources**: 8GB RAM, 10GB Disk

### Installation
```bash
cd ~/thesis

# 1. Install system libraries (libcairo, etc.)
./scripts/install_system_deps.sh

# 2. Install Python dependencies
./scripts/install_deps.sh

# 3. Set Python path
export PYTHONPATH="${PWD}:${PWD}/5g-network-optimization/services:${PYTHONPATH}"
```

---

## Configuration

Control the system behavior using environment variables in `.env` or Docker Compose.

### Core Settings
| Variable | Default | Description |
|----------|---------|-------------|
| `ML_HANDOVER_ENABLED` | `unset` | `1`=ML, `0`=A3. Unset=Auto (uses ML if ≥3 antennas). |
| `ML_CONFIDENCE_THRESHOLD` | `0.5` | Minimum confidence to predict an antenna. |
| `MODEL_TYPE` | `lightgbm` | Options: `lightgbm`, `lstm`, `ensemble`. |

### Ping-Pong Prevention
| Variable | Default | Description |
|----------|---------|-------------|
| `MIN_HANDOVER_INTERVAL_S` | `2.0` | Minimum seconds between handovers. |
| `MAX_HANDOVERS_PER_MINUTE` | `3` | Max rate of handovers. |
| `PINGPONG_WINDOW_S` | `10.0` | Logic window for return detections. |

### QoS Settings
| Variable | Default | Description |
|----------|---------|-------------|
| `QOS_URLLC_MIN_CONFIDENCE` | `0.85` | Required confidence for URLLC slices. |
| `QOS_EMBB_MIN_CONFIDENCE` | `0.70` | Required confidence for eMBB slices. |

---

## Deployment Options

### 1. Docker Compose (Local Development)

**ML Mode (Recommended)**
```bash
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```
- **Access**:
    - NEF Emulator: `http://localhost:8080`
    - ML Service: `http://localhost:5050`
    - Prometheus: `http://localhost:9090`
    - Grafana: `http://localhost:3000` (admin/admin)

**A3-Only Mode (Baseline)**
```bash
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

### 2. Kubernetes (Production)
See [`5g-network-optimization/deployment/kubernetes/README.md`](../5g-network-optimization/deployment/kubernetes/README.md) for manifests and helm charts.

---

## Data Generation

Generate synthetic 3GPP-compliant QoS datasets for training.

```bash
# Balanced dataset (eMBB, URLLC, mMTC)
python scripts/data_generation/synthetic_generator.py \
  --records 10000 \
  --profile balanced \
  --output output/qos_dataset.csv \
  --seed 42

# URLLC-heavy profile
python scripts/data_generation/synthetic_generator.py \
  --records 5000 \
  --profile urllc-heavy \
  --output output/urllc_data.json
```

---

## Model Training

### Automatic Training
The ML service automatically retrains on startup if no model exists or if data drift is detected (`AUTO_RETRAIN=true`).

### Manual Training API
```bash
# 1. Get Token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# 2. Trigger Training
curl -X POST http://localhost:5050/api/train \
  -H "Authorization: Bearer $TOKEN" \
  -d @output/training_data.json
```

---

## Monitoring & Metrics

### Key Prometheus Metrics
- `ml_prediction_requests_total`: Total predictions served.
- `ml_prediction_latency_seconds`: Latency distribution (<30ms goal).
- `ml_pingpong_suppressions_total`: Count of prevented ping-pongs.
- `nef_handover_decisions_total`: Handovers executed vs skipped.

### Grafana Dashboards
Access `http://localhost:3000` to view pre-built dashboards:
1. **ML Service Overview**: Latency, heavy-hitter features, drift.
2. **Network State**: Real-time UE positions, antenna loads.
3. **comparative Analysis**: ML vs A3 performance metrics.

---

## Troubleshooting

### Verification Script
Run the built-in system check:
```bash
bash scripts/verify_system_ready.sh --ml
```

### Common Issues
1. **Service Won't Start**: Check `docker compose logs ml-service`.
2. **Authorization Error**: Ensure `AUTH_USERNAME` matches `.env`.
3. **No Handovers**: Verify UEs are moving (`/api/v1/ue_movement/start`).

---

## Version Control & Release

### Version File
The repository root contains a `VERSION` file with the current semantic version (e.g., `1.0.0`). This file is the single source of truth for release versioning.

### Git Tagging for Thesis Milestones

Use annotated tags to mark significant thesis milestones:

```bash
# Read current version
VERSION=$(cat VERSION)

# Tag thesis submission
git tag -a "v${VERSION}-thesis-final" -m "Thesis final submission - ML-based handover optimization"

# Tag defense version (if updates made)
git tag -a "v${VERSION}-defense" -m "Thesis defense demonstration version"

# Push tags to remote
git push origin --tags
```

### Tag Naming Convention
- **Format**: `v{VERSION}-{milestone}`
- **Examples**:
  - `v1.0.0-thesis-final` — Submitted thesis version
  - `v1.0.0-defense` — Defense demonstration version  
  - `v1.0.1-camera-ready` — Post-review camera-ready version

### Reproducibility
To reproduce any tagged version:
```bash
git checkout v1.0.0-thesis-final
docker compose up -d
```

---

**End-to-End Demo Checklist**: See [`docs/THESIS.md`](THESIS.md) for the defense demonstration walkthrough.

**Full Architecture Reference**: See [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) for service details, data flows, and API reference.
