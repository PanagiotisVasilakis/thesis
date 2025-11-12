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

**Getting Started:** see [`docs/INDEX.md`](docs/INDEX.md) for prerequisites, quickstart, and navigation. The defence-ready walkthrough lives in [`docs/END_TO_END_DEMO.md`](docs/END_TO_END_DEMO.md). QoS behaviour and admission control are documented in [`docs/architecture/qos.md`](docs/architecture/qos.md).

**Reproducibility:** Run the full thesis experiment with:
```bash
./scripts/run_thesis_experiment.sh 10 my_experiment
```

Results will be generated in `thesis_results/my_experiment/` with visualizations, metrics, and analysis.

## Project Overview

The system follows a microservices architecture where the NEF emulator manages network events and the ML service predicts the best antenna based on UE mobility patterns, trajectory analysis, and QoS history.

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
docker compose -f 5g-network-optimization/docker-compose.yml up --build
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

## Synthetic QoS Dataset Generator

The thesis uses `scripts/data_generation/synthetic_generator.py` to create reproducible datasets for experimentation with enhanced Mobile Broadband (eMBB), Ultra-Reliable Low-Latency Communications (URLLC), massive Machine-Type Communications (mMTC), and a fall-back `default` profile. The generator is dependency-free beyond the packages in `requirements.txt` and only requires CPython 3.10 or newer.

### CSV schema

Each CSV row produced by the generator is ordered exactly as shown below so downstream notebooks and pipelines can load the file without additional schema discovery:

| Column | Description |
| --- | --- |
| `request_id` | Stable identifier in the form `req_000000`, ensuring deterministic joins across derivative datasets. |
| `service_type` | One of `embb`, `urllc`, `mmtc`, or `default`, representing the 3GPP traffic class sampled for the record. |
| `latency_ms` | Round-trip latency in milliseconds sampled from a triangular distribution tuned to industry guidance. |
| `reliability_pct` | Probability of successful delivery expressed as a percentage (e.g., `99.995`). |
| `throughput_mbps` | Expected user-plane throughput in megabits per second. |
| `priority` | Integer priority bucket aligned with 5QI-alike scheduling tiers used in the experiments. |

JSON output preserves the same field names for parity with the CSV schema.

### Traffic distributions and rationale

Service parameter envelopes align with 3GPP TS 22.261 and TR 38.913 for eMBB/URLLC and 3GPP TS 22.104 for mMTC, while the priority ranges mirror the conversational/mission-critical 5QI groupings from 3GPP TS 23.501 Annex E. By sampling bounded triangular distributions we bias the generator toward the operating points highlighted in those specifications while staying within their recommended minimum/maximum targets. A deeper explanation of the envelopes, trade-offs, and academic references is available in [`docs/qos/synthetic_qos_dataset.md`](docs/qos/synthetic_qos_dataset.md).

### CLI usage

Run the generator directly to produce a CSV dataset using the built-in balanced mix:

```bash
python scripts/data_generation/synthetic_generator.py   --records 10000   --profile balanced   --output output/samples.csv   --format csv   --seed 42
```

To rebalance the service mix, supply raw weights for any subset of traffic classes. The generator normalises the weights against the chosen profile (including the `default` catch-all) and validates that at least one class remains non-zero:

```bash
python scripts/data_generation/synthetic_generator.py   --records 5000   --profile urllc-heavy   --embb-weight 0.5   --urllc-weight 1.0   --mmtc-weight 0.2   --format json   --output output/urllc_bias.json
```

Use `--seed` for deterministic datasets and omit `--output` to stream results to stdout, which is helpful when piping samples into exploratory notebooks.

### Reproducing thesis experiments

1. Install dependencies via `pip install -r requirements.txt`.
2. Generate the desired datasets with the commands above, capturing both CSV and JSON formats as needed.
3. Execute the statistical and CLI regression tests to confirm the generator is behaving within the calibrated tolerances:

   ```bash
   pytest tests/data_generation/test_synthetic_generator.py
   ```

4. Record the random seeds and CLI options used so the experiment notebooks can recreate the same service mix distributions.

## Mobility Models and A3 Handover

The emulator includes several 3GPP-compliant mobility models located under `5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models`:

- **Linear** and **L‑shaped** movement
- **Random Waypoint** and **Random Directional**
- **Manhattan Grid** and **Urban Grid** patterns
- **Reference Point Group** mobility for UE clusters

For rule-based scenarios the NEF implements the 3GPP **A3 event** rule. Disable machine learning with `ML_HANDOVER_ENABLED=0` and use `A3_HYSTERESIS_DB` and `A3_TTT_S` to tune the hysteresis and time-to-trigger parameters.

## Environment Variables

The NEF emulator's `NetworkStateManager` supports several configuration options. Set these variables in your shell or through `docker compose`:

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
| `MIN_HANDOVER_INTERVAL_S` | Minimum seconds between handovers (ping-pong prevention) | `2.0` |
| `MAX_HANDOVERS_PER_MINUTE` | Maximum handovers allowed in 60-second window | `3` |
| `PINGPONG_WINDOW_S` | Time window for detecting immediate ping-pong returns | `10.0` |
| `PINGPONG_CONFIDENCE_BOOST` | Required confidence when ping-pong is detected | `0.9` |
| `CALIBRATE_CONFIDENCE` | Enable ML confidence calibration for better probability estimates | `1` (enabled) |
| `CALIBRATION_METHOD` | Calibration method: `isotonic` or `sigmoid` | `isotonic` |

`LOG_LEVEL` sets the verbosity of both services (`DEBUG`, `INFO`, etc.) while
`LOG_FILE` enables file-based logging with automatic rotation when specified.

The ML service writes its trained model to the path given by `MODEL_PATH` (default `app/models/antenna_selector_v1.0.0.joblib`).
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
`ML_SERVICE_URL` at `/api/predict-with-qos` for every UE in motion.  The response
contains the recommended antenna, the model confidence, and a QoS compliance summary which is then applied automatically.

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

## Feature Configuration

`AntennaSelector` no longer hardcodes its feature list. During initialization it
loads `app/config/features.yaml` which specifies feature names and optional
transforms. These transforms are resolved through a central registry that maps
feature names to callables.  Configuration entries may reference built-in
transform names (e.g. `float`, `int`) or fully qualified Python paths such as
`math.sqrt`.  The registry is also accessible programmatically for custom
registrations. The path to the configuration file can be overridden using the
`FEATURE_CONFIG_PATH` environment variable. See
[`docs/architecture/qos.md`](docs/architecture/qos.md) for details on feature transforms and data drift monitoring.

## Running the System

Both services run via `docker compose`. Use the environment variables above to switch between rule-based and ML-based modes.

### Simple A3 Mode

```bash
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

### ML Mode

```bash
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

### Single Container Mode

Install the ML service inside the NEF emulator image and omit the standalone
`ml-service` container:

```bash
ML_LOCAL=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
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

### Quick setup

To create a virtual environment, install all dependencies, and execute the
test suite in one step, run:

```bash
./scripts/setup_tests.sh
```

The script installs packages from both `requirements.txt` and
`tests/requirements.txt`, exports `PYTHONPATH` for module discovery, and runs
`pytest -q`.

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
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
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
