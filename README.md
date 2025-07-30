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
- The NEF emulator exposes Prometheus metrics at `/metrics` which the monitoring stack scrapes.
- `5g-network-optimization/docker-compose.yml` – orchestrates all services locally, including the monitoring stack.
- `pytest.ini` – shared configuration for running the automated tests.

Run the stack locally from this directory with:

```bash
docker-compose -f 5g-network-optimization/docker-compose.yml up --build
```

The ML service relies on a LightGBM model. Set `LIGHTGBM_TUNE=1` to run hyperparameter tuning when the service starts.

## Installation
Install the Python dependencies before running any of the services:

```bash
pip install -r requirements.txt
# or run the helper script (use --skip-if-present to avoid reinstalling)
scripts/install_deps.sh --skip-if-present
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
| `ML_SERVICE_URL` | URL of the ML service contacted by the NEF emulator | `http://ml-service:5050` |
| `A3_HYSTERESIS_DB` | Hysteresis value in dB for the A3 event rule | `2.0` |
| `A3_TTT_S` | Time-to-trigger in seconds for the A3 event rule | `0.0` |
| `NEF_API_URL` | Base URL of the NEF emulator used by the ML service | `http://localhost:8080` |
| `ML_LOCAL` | Install the ML service in the NEF emulator container and skip the separate `ml-service` container | `0` |
| `LOG_LEVEL` | Root logger level used by both services | `INFO` |
| `LOG_FILE` | Optional path for a rotating log file | *(unset)* |
| `min_antennas_ml` (param) | Minimum antennas required for automatic ML mode. Override when instantiating `HandoverEngine` | `3` |

`LOG_LEVEL` sets the verbosity of both services (`DEBUG`, `INFO`, etc.) while
`LOG_FILE` enables file-based logging with automatic rotation when specified.

The ML service writes its trained model to the path given by `MODEL_PATH` (default `app/models/antenna_selector.joblib`).
Override this variable and mount a host directory in a `docker-compose.override.yml` file if you want the model to persist across container runs.

When `ML_HANDOVER_ENABLED` is *unset*, `HandoverEngine` toggles ML based on the
number of registered antennas. ML becomes active once at least
`min_antennas_ml` antennas exist. To change this threshold pass the parameter
explicitly when constructing the engine:

```python
state_mgr = NetworkStateManager()
engine = HandoverEngine(state_mgr, min_antennas_ml=2)
```

With two antennas registered the engine operates in rule-based mode. Adding a
third antenna makes it switch to ML automatically:

```python
nsm = NetworkStateManager()
nsm.antenna_list = {"A": Antenna(...), "B": Antenna(...)}
engine = HandoverEngine(nsm)
print(engine.use_ml)  # False

nsm.antenna_list["C"] = Antenna(...)
engine._update_mode()
print(engine.use_ml)  # True
```

When `ML_HANDOVER_ENABLED` is enabled the NEF emulator sends a POST request to
`ML_SERVICE_URL` at `/api/predict` for every UE in motion.  The response
contains the recommended antenna which is then applied automatically.

## Altitude Input for AntennaSelector

The UE feature set now includes an `altitude` field representing the z‑axis
position of the device. `AntennaSelector` exposes this value in
`base_feature_names` and incorporates it when extracting features for both
training and live predictions. Including altitude lets the model distinguish
between scenarios such as multi‑storey buildings or drones flying at different
heights. Prediction requests should therefore supply an `altitude` value along
with latitude and longitude for best accuracy.

Example test data demonstrating altitude usage can be found in
[`test_antenna_selector.py`](5g-network-optimization/services/ml-service/tests/test_antenna_selector.py),
where altitude is assigned before training【F:5g-network-optimization/services/ml-service/tests/test_antenna_selector.py†L188-L200】.

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

### Single Container Mode
Install the ML service inside the NEF emulator image and omit the standalone
`ml-service` container:

```bash
ML_LOCAL=1 docker-compose -f 5g-network-optimization/docker-compose.yml up --build
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

Check ML service connectivity with the NEF emulator:
```bash
curl http://localhost:5050/api/nef-status
```

Fetch Prometheus metrics exposed by the ML service:
```bash
curl http://localhost:5050/metrics
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
Before running `pytest`, install all required packages.  You can execute the
helper scripts or run `pip install -r requirements.txt` manually:
```bash
./scripts/install_system_deps.sh
./scripts/install_deps.sh --skip-if-present
# or simply
pip install -r requirements.txt
```
These helper scripts install everything in `requirements.txt` (including
`fastapi` and `matplotlib`) and register the `ml_service` package in editable
mode. They also pull in OS libraries such as `libcairo` and `libjpeg` that the
tests require. If you encounter errors about missing shared libraries, rerun the
system dependency step.

After the dependencies are installed, execute the test suite:
```bash
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
pip install -e 5g-network-optimization/services/ml-service
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

- `scripts/install_system_deps.sh` – install OS libraries needed by the services and tests.
- `scripts/install_deps.sh` – install Python dependencies listed in `requirements.txt` and the `ml_service` package. Pass `--skip-if-present` to bypass installation when a suitable virtual environment already has them.
- `scripts/run_tests.sh` – run both installation steps and execute the tests with coverage output.
