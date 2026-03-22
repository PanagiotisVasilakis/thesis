# 5G Network Optimization Thesis

[![Tests](https://img.shields.io/badge/tests-73%2F73%20passing-brightgreen)]() [![Defense Ready](https://img.shields.io/badge/status-defense%20ready-blue)]() [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()

This repository contains a **production-ready** machine learning-based handover decision system for 5G networks, validated through comprehensive experimentation and testing.

## 🎓 Thesis Results Summary

**Key Achievements (validated in controlled experiment):**
- **100% ping-pong elimination** (0% vs 37.50% in traditional A3 mode)
- **422% cell dwell time improvement** (133.71s vs 25.61s median)
- **75% handover reduction** (6 vs 24 handovers, reducing signaling overhead)
- **100% QoS compliance** (all ML handovers improved latency, throughput, and packet loss)
- **73/73 tests passing** (comprehensive validation across 8 development phases)

## 🚀 Quick Start

```bash
# Install dependencies
./scripts/install_system_deps.sh
./scripts/install_deps.sh

# Run the "One-Command" experiment (10-min ML vs A3 comparison)
./scripts/run_thesis_experiment.sh 10 my_experiment

# Run tests
pytest
```

Results are generated in `thesis_results/my_experiment/` with visualizations, metrics, and analysis.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   5G Network Optimization System                        │
│                                                                         │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │   NEF Emulator      │◄──────────►│    ML Service                │    │
│  │   (FastAPI :8080)    │  Feature   │    (Flask :5050)             │    │
│  │   - 3GPP A3 Rules   │  Exchange  │    - LightGBM Prediction    │    │
│  │   - Mobility Models  │            │    - QoS-Aware Decisions    │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│           │                                        │                    │
│           ▼                                        ▼                    │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │  Kinisis UI (:3001) │            │  Prometheus (:9090) +        │    │
│  │  React + Leaflet     │            │  Grafana (:3000)             │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Repository Layout

```
thesis/
├── 5g-network-optimization/
│   ├── services/
│   │   ├── nef-emulator/          # NEF Emulator (FastAPI) — see its README
│   │   ├── ml-service/            # ML Service (Flask) — see its README
│   │   └── kinisis_ui/            # React UI — see its README
│   ├── deployment/kubernetes/     # K8s manifests — see its README
│   ├── monitoring/                # Prometheus + Grafana — see its README
│   └── docker-compose.yml         # Full stack orchestration
├── scripts/                       # Experiment, analysis, and utility scripts
├── tests/                         # Comprehensive test suite (73 tests)
├── mlops/                         # Feast feature store, data pipeline
├── docs/                          # Detailed documentation (see below)
├── requirements.lock              # Locked Python dependencies
├── requirements.txt               # Symlink → requirements.lock
└── pytest.ini                     # Test configuration
```

## Running the System

Both services run via `docker compose`. Set `ML_HANDOVER_ENABLED` to switch modes.

```bash
# ML Mode (recommended)
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build

# A3-Only Mode (baseline)
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up --build

# Single Container Mode (ML inside NEF)
ML_LOCAL=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

## Testing

```bash
# Quick: create venv, install deps, run tests
./scripts/setup_tests.sh

# Or manually
pip install -r requirements.txt
pytest
```

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Full system architecture — service layers, data flows, O-RAN mapping, API reference |
| **[MANUAL.md](docs/MANUAL.md)** | Operations guide — deployment, configuration, monitoring, troubleshooting |
| **[THESIS.md](docs/THESIS.md)** | Technical deep dive — algorithms, methodology, validation results, reproducibility |

Each service also has its own README with component-specific setup:
- [`nef-emulator/README.md`](5g-network-optimization/services/nef-emulator/README.md)
- [`ml-service/README.md`](5g-network-optimization/services/ml-service/README.md)
- [`kinisis_ui/README.md`](5g-network-optimization/services/kinisis_ui/README.md)
- [`monitoring/README.md`](5g-network-optimization/monitoring/README.md)
- [`kubernetes/README.md`](5g-network-optimization/deployment/kubernetes/README.md)
