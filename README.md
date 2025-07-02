# 5G Network Optimization Thesis

This repository contains the code and configuration for optimizing 5G handover decisions using a 3GPP-compliant Network Exposure Function (NEF) emulator and a machine learning service.  All implementation lives in the [`5g-network-optimization`](5g-network-optimization/) directory.

**Getting Started:** see [5g-network-optimization/leftover_docks/GETTING_STARTED.md](5g-network-optimization/leftover_docks/GETTING_STARTED.md) for prerequisites and a full setup walkthrough.

## Project Overview
The system follows a microservices architecture where the NEF emulator manages network events and the ML service predicts the best antenna based on UE mobility patterns.

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
For detailed setup instructions, see the READMEs in [`5g-network-optimization/services/nef-emulator`](5g-network-optimization/services/nef-emulator/README.md) and [`5g-network-optimization/services/ml-service`](5g-network-optimization/services/ml-service/README.md).

## Repository Layout
This directory groups the code and configuration needed to run the system:

- `5g-network-optimization/services/` – source code for the NEF emulator and the ML service. Each service includes its own Dockerfile and tests. These services are referenced by `docker-compose.yml` for local development and by the manifests under `5g-network-optimization/deployment/`.
- `5g-network-optimization/deployment/` – Kubernetes manifests for running the pre-built images in a cluster. They rely on images built from `5g-network-optimization/services/` being pushed to your registry.
- `5g-network-optimization/monitoring/` – Prometheus and Grafana configuration used to collect metrics from the running services.
- `5g-network-optimization/docker-compose.yml` – orchestrates all services locally, including the monitoring stack.
- `pytest.ini` – shared configuration for running the automated tests.

Run the stack locally from this directory with:

```bash
docker-compose -f 5g-network-optimization/docker-compose.yml up --build
```
Set `MODEL_TYPE` to choose the ML algorithm for the `ml-service`. The compose file defaults to `random_forest`.

## Installation
Install the Python dependencies before running any of the services:

```bash
pip install -r requirements.txt
# or run the helper script
scripts/install_deps.sh
```

The environment variables documented below (`ML_HANDOVER_ENABLED` and others) can be passed on the command line or in an `.env` file to control the behavior of both services.

## Mobility Models and A3 Handover
The emulator includes several 3GPP-compliant mobility models located under `5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models`:

- **Linear** and **L‑shaped** movement
- **Random Waypoint** and **Random Directional**
- **Manhattan Grid** and **Urban Grid** patterns
- **Reference Point Group** mobility for UE clusters

For rule-based scenarios the NEF implements the 3GPP **A3 event** rule. Disable machine learning with `ML_HANDOVER_ENABLED=0` and use `A3_HYSTERESIS_DB` and `A3_TTT_S` to tune the hysteresis and time-to-trigger parameters.

## Environment Variables
The NEF emulator's `NetworkStateManager` supports several configuration options. Set these variables in your shell or through `docker-compose`:

| Variable | Description | Default |
|----------|-------------|---------|
| `ML_HANDOVER_ENABLED` | Enable ML-driven handovers (`true`/`false`). If unset, the engine uses ML automatically when at least three antennas are configured | `false` |
| `A3_HYSTERESIS_DB` | Hysteresis value in dB for the A3 event rule | `2.0` |
| `A3_TTT_S` | Time-to-trigger in seconds for the A3 event rule | `0.0` |
| `NEF_API_URL` | Base URL of the NEF emulator used by the ML service | `http://localhost:8080` |
| `MODEL_TYPE` | Algorithm used by the ML service (`random_forest`, `lightgbm`, etc.) | `random_forest` |

The ML service defaults to a random forest model but can also load a LightGBM model when `MODEL_TYPE=lightgbm`.

## Running the System
Both services run via `docker-compose`. Use the environment variables above to switch between rule-based and ML-based modes.

### Simple A3 Mode
```bash
ML_HANDOVER_ENABLED=0 docker-compose -f 5g-network-optimization/docker-compose.yml up --build
```

### ML Mode
```bash
ML_HANDOVER_ENABLED=1 docker-compose -f 5g-network-optimization/docker-compose.yml up --build
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
docker build -t <registry>/nef-emulator:latest -f 5g-network-optimization/services/nef-emulator/backend/Dockerfile.backend 5g-network-optimization/services/nef-emulator
docker build -t <registry>/ml-service:latest 5g-network-optimization/services/ml-service
```

Push the images so your cluster can pull them:

```bash
docker push <registry>/nef-emulator:latest
docker push <registry>/ml-service:latest
```

## Testing
### Installing Test Dependencies
Install the Python packages required by the test suite:
```bash
pip install -r requirements.txt
# or run ./scripts/install_deps.sh
```
Some tests rely on optional packages such as `matplotlib` for generating plots
and `Flask` for API integration checks. These are included in
`requirements.txt`, so ensure they are installed before running the tests.

After installing the Python dependencies, set up the required system libraries
and run the test suite:
```bash
./scripts/install_system_deps.sh
pytest
```

To run the same steps automatically and produce a coverage report, execute:

```bash
./scripts/run_tests.sh
```
The coverage results are written under `CI-CD_reports/coverage_<timestamp>.txt`.
Tests also run automatically on merges via the workflow
[`tests.yml`](.github/workflows/tests.yml).

### Extended Integration Tests
Start the containers and run the full integration suite:
```bash
ML_HANDOVER_ENABLED=1 docker-compose -f 5g-network-optimization/docker-compose.yml up --build
pip install -r requirements.txt
pytest 5g-network-optimization/services/nef-emulator/tests/integration \
       5g-network-optimization/services/ml-service/tests/integration
```

### Temporary Files
Unit tests that generate plots now write all images to the pytest `tmp_path` fixture. The tests assert the files exist and remove them automatically so the repository remains clean.

### Output Directories
Visualizations generated by the ML service and NEF emulator are organized under
subfolders of `output/`:

- `output/coverage/` – antenna coverage maps
- `output/trajectory/` – UE movement trajectories
- `output/mobility/` – mobility model examples from the NEF emulator tests
- `presentation_assets/` – pre-rendered graphs and captions for reports

These folders are created automatically when the plots are produced.

Run the helper scripts below to create the presentation assets and a PDF
overview:

```bash
python scripts/generate_presentation_assets.py
python scripts/build_presentation_pdf.py
```
The second command collects the generated images and captions under
`presentation_assets/` and writes `overview.pdf`.

## Useful Scripts

- `scripts/install_deps.sh` – install Python dependencies listed in `requirements.txt`.
- `scripts/install_system_deps.sh` – install OS libraries needed by the services and tests.
- `scripts/run_tests.sh` – install dependencies and run the tests with coverage output.
