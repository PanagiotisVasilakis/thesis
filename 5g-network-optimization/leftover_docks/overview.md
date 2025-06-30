# Project Overview

This document summarizes the architecture and deployment workflow of the 5G Network Optimization system.  The repository contains two main services:

1. **NEF Emulator** – a FastAPI application that emulates a 3GPP Network Exposure Function.  It generates mobility events, keeps track of UE state and performs handover decisions.
2. **ML Service** – a Flask application that predicts the optimal antenna for each UE based on real‑time radio metrics.  It can be used directly or invoked from the NEF emulator.

A monitoring stack using Prometheus and Grafana collects metrics from both services.

## Architecture and Workflow

1. **Mobility Generation** – Trajectories are produced by classes in `services/nef-emulator/backend/app/app/mobility_models`.  See the [Mobility Models README](../services/nef-emulator/backend/app/app/mobility_models/README.md) for details on each model.
2. **Network State Management** – The NEF emulator's [`NetworkStateManager`](../services/nef-emulator/backend/app/app/network/state_manager.py) keeps track of UE locations, antenna configurations and handover history.
3. **Handover Decision** – [`HandoverEngine`](../services/nef-emulator/backend/app/app/handover/engine.py) selects the best antenna:
   - When `ML_HANDOVER_ENABLED` is set, the engine loads the ML model and uses it to predict the target antenna.
   - Otherwise it applies the 3GPP **A3** rule. Parameters `A3_HYSTERESIS_DB` and `A3_TTT_S` fine‑tune the decision.
4. **Monitoring** – Metrics are exposed at `/metrics` on each service and scraped by Prometheus.  Grafana dashboards show request latency, prediction counts and other statistics.  See the [Monitoring README](../monitoring/README.md).

## Running Locally

1. Install [Docker](https://docs.docker.com/get-docker/) and Docker Compose.
2. From the `5g-network-optimization` directory run:
   ```bash
   docker-compose up --build
   ```
3. The NEF emulator will be reachable on `http://localhost:8080` and the ML service on `http://localhost:5050`.

To switch between rule‑based and ML‑driven handovers, set environment variables before launching Docker Compose (or in a `.env` file):

```bash
# Use only the A3 rule
ML_HANDOVER_ENABLED=0 docker-compose up --build

# Enable machine learning
ML_HANDOVER_ENABLED=1 docker-compose up --build
```

## Deploying to Kubernetes

1. Build and push images to a registry accessible by your cluster.  Example commands are provided in the [root README](../README.md#building-docker-images).
2. Update the image references in `deployment/kubernetes/ml-service.yaml` and any NEF emulator manifest you create.
3. Apply the manifests:
   ```bash
   kubectl apply -f deployment/kubernetes/ml-service.yaml
   # create a similar manifest for the NEF emulator
   kubectl apply -f deployment/kubernetes/nef-emulator.yaml
   ```
4. Check the running pods and services:
   ```bash
   kubectl get pods
   kubectl get services
   ```
5. Optionally expose them via `NodePort` or Ingress.  More tips are in [deployment/kubernetes/README.md](../deployment/kubernetes/README.md).

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ML_HANDOVER_ENABLED` | Enable ML-driven handovers. When `false` only the A3 rule is used | `false` |
| `A3_HYSTERESIS_DB` | Hysteresis value in dB for the A3 event rule | `2.0` |
| `A3_TTT_S` | Time-to-trigger in seconds for the A3 event rule | `0.0` |
| `NEF_API_URL` | Base URL of the NEF emulator used by the ML service | `http://localhost:8080` |

Set these variables in your shell or in Docker/Kubernetes manifests to control the behaviour of both services.

## Further Documentation

- [NEF Emulator README](../services/nef-emulator/README.md)
- [ML Service README](../services/ml-service/README.md)
- [Antenna and Path Loss Docs](../services/nef-emulator/docs/antenna_and_path_loss.md)
- [Mobility Models README](../services/nef-emulator/backend/app/app/mobility_models/README.md)
- [Kubernetes Deployment Guide](../deployment/kubernetes/README.md)

