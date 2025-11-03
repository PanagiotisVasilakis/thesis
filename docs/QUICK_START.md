# Quick Start Guide
## 5G Network Optimization - Essential Commands

This is a condensed reference for running the complete system. For detailed explanations, see [COMPLETE_DEPLOYMENT_GUIDE.md](COMPLETE_DEPLOYMENT_GUIDE.md).

---

## Prerequisites

```bash
# Install dependencies
cd ~/thesis
./scripts/install_system_deps.sh
./scripts/install_deps.sh

# Set Python path
export PYTHONPATH="${PWD}:${PWD}/5g-network-optimization/services:${PYTHONPATH}"
```

---

## Start the System

### Option 1: Quick Start (ML Enabled)

```bash
cd ~/thesis
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

**Access Points:**
- NEF Emulator: http://localhost:8080
- ML Service: http://localhost:5050
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)

### Option 2: A3-Only Mode (No ML)

```bash
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

---

## Initialize Network Topology

```bash
cd ~/thesis/5g-network-optimization/services/nef-emulator

# Set environment (adjust if needed)
export DOMAIN=localhost
export NGINX_HTTPS=8080
export FIRST_SUPERUSER=admin@my-email.com
export FIRST_SUPERUSER_PASSWORD=pass

# Run initialization
./backend/app/app/db/init_simple.sh
```

This creates: 2 paths, 1 gNB, 4 cells, 3 UEs

---

## Generate Synthetic Data

```bash
cd ~/thesis

# Balanced dataset
python scripts/data_generation/synthetic_generator.py \
  --records 10000 \
  --profile balanced \
  --output output/qos_balanced.csv \
  --seed 42

# URLLC-heavy (low latency focus)
python scripts/data_generation/synthetic_generator.py \
  --records 5000 \
  --profile urllc-heavy \
  --output output/qos_urllc.json \
  --format json
```

---

## Collect Training Data

```bash
cd ~/thesis/5g-network-optimization/services/ml-service

# Basic collection (5 minutes)
python collect_training_data.py \
  --url http://localhost:8080 \
  --username admin \
  --password admin \
  --duration 300 \
  --interval 1

# Collect and train immediately
python collect_training_data.py \
  --url http://localhost:8080 \
  --username admin \
  --password admin \
  --duration 300 \
  --train
```

---

## Test ML Predictions

```bash
# Get auth token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# Basic prediction
curl -X POST http://localhost:5050/api/predict \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ue_id": "test-ue",
    "latitude": 100.0,
    "longitude": 50.0,
    "connected_to": "antenna_1",
    "rf_metrics": {
      "antenna_1": {"rsrp": -80, "sinr": 15},
      "antenna_2": {"rsrp": -90, "sinr": 10},
      "antenna_3": {"rsrp": -85, "sinr": 12}
    }
  }' | jq

# QoS-aware prediction
curl -X POST http://localhost:5050/api/predict-with-qos \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ue_id": "test-ue-qos",
    "latitude": 200.0,
    "longitude": 150.0,
    "connected_to": "antenna_2",
    "rf_metrics": {
      "antenna_1": {"rsrp": -75, "sinr": 18},
      "antenna_2": {"rsrp": -82, "sinr": 14}
    },
    "service_type": "urllc",
    "service_priority": 9,
    "latency_requirement_ms": 5.0
  }' | jq
```

---

## Run Tests

```bash
cd ~/thesis

# All tests with coverage
./scripts/run_tests.sh

# Specific test categories
pytest tests/data_generation/          # Data generation
pytest tests/mlops/                    # MLOps & QoS
pytest 5g-network-optimization/services/ml-service/tests/  # ML service
pytest 5g-network-optimization/services/nef-emulator/tests/  # NEF

# Verbose mode
pytest -vv
```

---

## Generate Visualizations

```bash
cd ~/thesis

# Generate all assets
python scripts/generate_presentation_assets.py

# Check output
ls -lh presentation_assets/

# Via API: Coverage map
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5050/api/visualization/coverage-map" \
  --output coverage_map.png

# Outputs saved to:
# - output/coverage/
# - output/trajectory/
# - presentation_assets/
```

---

## Monitor Performance

```bash
# Check service health
curl http://localhost:5050/api/health | jq
curl http://localhost:5050/api/model-health | jq

# View metrics
curl http://localhost:5050/metrics
curl http://localhost:8080/metrics

# Prometheus queries
open http://localhost:9090
# Try: ml_prediction_requests_total
# Try: nef_handover_decisions_total

# Grafana dashboards
open http://localhost:3000
# Login: admin / admin
```

---

## Common Operations

### Restart Services

```bash
cd ~/thesis

# Restart all
docker compose -f 5g-network-optimization/docker-compose.yml restart

# Restart specific service
docker compose -f 5g-network-optimization/docker-compose.yml restart ml-service
docker compose -f 5g-network-optimization/docker-compose.yml restart nef-emulator
```

### View Logs

```bash
# All services
docker compose -f 5g-network-optimization/docker-compose.yml logs -f

# Specific service
docker compose -f 5g-network-optimization/docker-compose.yml logs -f ml-service
docker compose -f 5g-network-optimization/docker-compose.yml logs -f nef-emulator
```

### Stop System

```bash
cd ~/thesis

# Stop all services
docker compose -f 5g-network-optimization/docker-compose.yml down

# Stop and remove volumes (clean slate)
docker compose -f 5g-network-optimization/docker-compose.yml down -v
```

### Check Model Status

```bash
# Model health
curl http://localhost:5050/api/model-health | jq

# List model versions
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/models | jq

# Switch model version
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5050/api/models/1.0.0"
```

### Export Metrics for Analysis

```bash
# Export Prometheus data
curl "http://localhost:9090/api/v1/query?query=ml_prediction_requests_total" \
  | jq > metrics_export.json

# Export time series
curl "http://localhost:9090/api/v1/query_range?query=ml_prediction_confidence_avg&start=$(date -u -d '1 hour ago' +%s)&end=$(date -u +%s)&step=60" \
  | jq > confidence_timeseries.json
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check Docker
docker ps

# Check logs
docker compose -f 5g-network-optimization/docker-compose.yml logs

# Rebuild from scratch
docker compose -f 5g-network-optimization/docker-compose.yml down -v
docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

### Authentication Fails

```bash
# Get fresh token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# Verify
echo $TOKEN
```

### Tests Failing

```bash
# Reinstall dependencies
pip install -r requirements.txt
pip install -r tests/requirements.txt

# Set PYTHONPATH
export PYTHONPATH="${PWD}:${PWD}/5g-network-optimization/services"

# Run with verbose output
pytest -vvs
```

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ML_HANDOVER_ENABLED` | unset (auto) | `1`=ML, `0`=A3, unset=auto |
| `MODEL_TYPE` | `lightgbm` | Model type: lightgbm, lstm, ensemble |
| `LIGHTGBM_TUNE` | `0` | Enable hyperparameter tuning |
| `ML_CONFIDENCE_THRESHOLD` | `0.5` | Min confidence for ML predictions |
| `A3_HYSTERESIS_DB` | `2.0` | A3 hysteresis in dB |
| `A3_TTT_S` | `0.0` | A3 time-to-trigger |
| `AUTH_USERNAME` | `admin` | ML service username |
| `AUTH_PASSWORD` | `admin` | ML service password |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## API Quick Reference

### ML Service (http://localhost:5050)

```bash
# Login
POST /api/login
Body: {"username":"admin","password":"admin"}

# Predict
POST /api/predict
Header: Authorization: Bearer <token>
Body: {ue_id, latitude, longitude, connected_to, rf_metrics}

# QoS Predict
POST /api/predict-with-qos
Header: Authorization: Bearer <token>
Body: {...prediction_data, service_type, service_priority}

# Train
POST /api/train
Header: Authorization: Bearer <token>
Body: [training_samples...]

# Health
GET /api/health
GET /api/model-health

# Metrics
GET /metrics
```

### NEF Emulator (http://localhost:8080)

```bash
# Swagger UI
GET /docs

# State
GET /api/v1/ml/state/{ue_id}

# Handover
POST /api/v1/ml/handover?ue_id={ue_id}

# Movement
POST /api/v1/ue_movement/start
GET /api/v1/ue_movement/{ue_id}

# Metrics
GET /metrics
```

---

## Thesis Results Workflow

```bash
# 1. Start system
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up -d

# 2. Initialize topology
cd 5g-network-optimization/services/nef-emulator
./backend/app/app/db/init_simple.sh

# 3. Generate synthetic data
cd ~/thesis
python scripts/data_generation/synthetic_generator.py \
  --records 10000 --profile balanced --output output/qos_data.csv --seed 42

# 4. Collect training data
cd 5g-network-optimization/services/ml-service
python collect_training_data.py --url http://localhost:8080 \
  --username admin --password admin --duration 600 --train

# 5. Generate visualizations
cd ~/thesis
python scripts/generate_presentation_assets.py

# 6. Run performance analysis
python scripts/analyze_results.py  # Create this based on guide

# 7. Export metrics
curl "http://localhost:9090/api/v1/query?query=ml_prediction_requests_total" | jq > results/metrics.json

# 8. Run tests
./scripts/run_tests.sh

# 9. Check outputs
ls -lh output/
ls -lh presentation_assets/
```

---

## Key Directories

- `5g-network-optimization/services/ml-service/` - ML service code
- `5g-network-optimization/services/nef-emulator/` - NEF emulator code
- `5g-network-optimization/monitoring/` - Prometheus/Grafana configs
- `5g-network-optimization/deployment/kubernetes/` - K8s manifests
- `scripts/` - Utility scripts
- `tests/` - Test suite
- `output/` - Generated outputs
- `presentation_assets/` - Thesis visualizations
- `docs/` - Documentation

---

## Additional Resources

- **Complete Guide**: [COMPLETE_DEPLOYMENT_GUIDE.md](COMPLETE_DEPLOYMENT_GUIDE.md)
- **QoS Architecture**: [architecture/qos.md](architecture/qos.md)
- **ML Service README**: [../5g-network-optimization/services/ml-service/README.md](../5g-network-optimization/services/ml-service/README.md)
- **NEF Emulator README**: [../5g-network-optimization/services/nef-emulator/README.md](../5g-network-optimization/services/nef-emulator/README.md)
- **Main INDEX**: [INDEX.md](INDEX.md)

---

**Quick Start Version**: 1.0  
**For detailed explanations, troubleshooting, and advanced scenarios, see the Complete Deployment Guide.**

