# 5G Network Optimization Using NEF Emulator and Machine Learning

## Project Overview
This project aims to optimize 5G handover decisions using a 3GPP-compliant Network Exposure Function (NEF) emulator and a dedicated machine learning service. The system follows a microservices architecture where the NEF emulator manages network events and the ML service predicts the best antenna based on UE mobility patterns.

## System Architecture
```
┌─────────────────────────────────────────────────────────────────────────┐
│                   5G Network Optimization System                        │
│                                                                         │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │                     │            │                              │    │
│  │   NEF Emulator      │<───────────┤    ML Service                │    │
│  │   (Original)        │            │    - Antenna Selection       │    │
│  │                     │────────────┤    - Performance Metrics     │    │
│  │                     │            │    - Decision Engine         │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│           │                                        │                    │
│           ▼                                        ▼                    │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │                     │            │                              │    │
│  │   3GPP Mobility     │────────────┤    Monitoring & Evaluation   │    │
│  │   Models            │            │    - Prometheus              │    │
│  │                     │            │    - Grafana                 │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```
For detailed setup instructions, see the READMEs in [`services/nef-emulator`](services/nef-emulator/README.md) and [`services/ml-service`](services/ml-service/README.md).

## Repository Layout

This directory groups the code and configuration needed to run the system:

- `services/` – source code for the NEF emulator and the ML service. Each
  service includes its own Dockerfile and tests. These services are referenced by
  `docker-compose.yml` for local development and by the manifests under
  `deployment/`.
- `deployment/` – Kubernetes manifests for running the pre-built images in a
  cluster. They rely on images built from `services/` being pushed to your
  registry.
- `monitoring/` – Prometheus and Grafana configuration used to collect metrics
  from the running services.
- `docker-compose.yml` – orchestrates all services locally, including the
  monitoring stack.
- `pytest.ini` – shared configuration for running the automated tests.

Run the stack locally from this directory with:

```bash
docker-compose up --build
```

## Installation
Install the Python dependencies before running any of the services:

```bash
pip install -r requirements.txt
# or run the helper script
scripts/install_deps.sh
```

The environment variables documented below (`SIMPLE_MODE`, `ML_HANDOVER_ENABLED`
and others) can be passed on the command line or in an `.env` file to control
the behavior of both services.


## Mobility Models and A3 Handover
The emulator includes several 3GPP-compliant mobility models located under
`services/nef-emulator/backend/app/app/mobility_models`:

- **Linear** and **L‑shaped** movement
- **Random Waypoint** and **Random Directional**
- **Manhattan Grid** and **Urban Grid** patterns
- **Reference Point Group** mobility for UE clusters

For rule-based scenarios the NEF implements the 3GPP **A3 event** rule. Enable
it with `SIMPLE_MODE=true`; use `A3_HYSTERESIS_DB` and `A3_TTT_S` to tune the
hysteresis and time-to-trigger parameters.

## Environment Variables
The NEF emulator's `NetworkStateManager` supports several configuration options. Set these variables in your shell or through `docker-compose`:

| Variable | Description | Default |
|----------|-------------|---------|
| `SIMPLE_MODE` | Apply the A3 handover rule before executing any decision (`true`/`false`) | `false` |
| `ML_HANDOVER_ENABLED` | Enable ML-driven handovers (`true`/`false`). If unset, the engine uses ML automatically when at least three antennas are configured | `false` |
| `A3_HYSTERESIS_DB` | Hysteresis value in dB for the A3 event rule | `2.0` |
| `A3_TTT_S` | Time-to-trigger in seconds for the A3 event rule | `0.0` |
| `NEF_API_URL` | Base URL of the NEF emulator used by the ML service | `http://localhost:8080` |

## Running the System
Both services run via `docker-compose`. Use the environment variables above to switch between rule-based and ML-based modes.

### Simple A3 Mode
```bash
ML_HANDOVER_ENABLED=0 SIMPLE_MODE=true docker-compose up --build
```

### ML Mode
```bash
ML_HANDOVER_ENABLED=1 docker-compose up --build
```

### Example API Calls
Trigger a handover:
```bash
curl -X POST "http://localhost:8080/api/v1/ml/handover?ue_id=u1"
```

Get a direct prediction from the ML service:
```bash
curl -X POST http://localhost:5050/api/predict \
     -H 'Content-Type: application/json' \
     -d '{"ue_id":"u1","latitude":100,"longitude":50,"connected_to":"antenna_1","rf_metrics":{"antenna_1":{"rsrp":-80,"sinr":15},"antenna_2":{"rsrp":-90,"sinr":10}}}'
```

## Building Docker Images

Build the NEF emulator and ML service images before deploying to Kubernetes:

```bash
docker build -t <registry>/nef-emulator:latest -f services/nef-emulator/backend/Dockerfile.backend services/nef-emulator
docker build -t <registry>/ml-service:latest services/ml-service
```

Push the images so your cluster can pull them:

```bash
docker push <registry>/nef-emulator:latest
docker push <registry>/ml-service:latest
```

## Testing
First install the required system libraries, then the Python packages. Use the helper script `scripts/install_system_deps.sh` from the repository root:
```bash
./scripts/install_system_deps.sh
pip install -r requirements.txt
```

### Extended Integration Tests
Start the containers and run the full integration suite:
```bash
ML_HANDOVER_ENABLED=1 docker-compose up --build
pip install -r requirements.txt
pytest services/nef-emulator/tests/integration \
       services/ml-service/tests/integration
```

### Temporary Files
Unit tests that generate plots now write all images to the pytest `tmp_path`
fixture. The tests assert the files exist and remove them automatically so the
repository remains clean.
