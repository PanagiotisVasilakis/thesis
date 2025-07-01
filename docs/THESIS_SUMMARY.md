# Thesis Project Summary

## Main Goal
The 5G Network Optimization project demonstrates how advanced handover algorithms can be applied in a reproducible testbed.  A 3GPP‑compliant Network Exposure Function (NEF) emulator emits mobility events for multiple UEs while a machine learning (ML) service learns from historical traces to predict the best serving cell.  The overall objective is to balance coverage and quality of service by dynamically combining rule‑based decisions with ML‑driven insights【F:README.md†L1-L14】.

## Implemented Components
- **NEF Emulator** – FastAPI application that exposes REST endpoints to create UEs, retrieve movement state and trigger handovers.  It bundles several mobility models and path‑loss calculations so it can simulate realistic radio conditions.  When ML support is disabled, it falls back to the pure A3 rule for deterministic behaviour.
- **ML Service** – Lightweight Flask API offering `/api/predict` and `/api/train` routes.  It loads or trains the `AntennaSelector` model on demand, persists the model to disk and exposes metrics for accuracy and request latency.  Training data is gathered from the NEF emulator or from prerecorded traces.
- **Monitoring Stack** – Prometheus scrapes metrics from both services and Grafana dashboards visualise throughput, latency and model accuracy【F:5g-network-optimization/monitoring/README.md†L1-L21】.  Alerts can be configured to detect performance regressions during experiments.
- **Docker & Kubernetes** – `docker-compose.yml` spins up the NEF emulator, ML service and monitoring stack for local development.  Kubernetes manifests under `deployment/` replicate the same setup in a cluster for scale testing and CI pipelines【F:README.md†L31-L37】.

## Handover Technique
`HandoverEngine` orchestrates the decision flow for every UE event.  It first determines if ML handover is enabled through environment variables or the configured number of antennas.  If the ML model is available, it loads the saved `AntennaSelector`, extracts the UE features and asks the model for the best antenna.  Otherwise it applies the A3 rule.  The engine also handles retries and logs metrics for each decision【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L16-L62】【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L60-L98】.

## A3 Rule-Based Logic
`A3EventRule` accumulates measurements of the reference signal received power (RSRP) for the serving and neighbouring cells.  The rule checks whether the target cell’s RSRP is higher by a hysteresis margin and whether this condition holds for the entire time‑to‑trigger window.  Once both thresholds are met the event is raised and a handover is initiated【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/a3_rule.py†L1-L23】.

## ML-Based Logic
The `AntennaSelector` class wraps a `RandomForestClassifier` and extracts location, movement and signal metrics from each UE.  Features include latitude, longitude, speed, normalised direction and the current antenna’s RSRP and SINR.  Training is performed with `scikit-learn`; the resulting model is exported with `joblib` and reloaded at startup.  Predictions are served in real time through the Flask API and can be logged to assess feature importance and accuracy【F:5g-network-optimization/services/ml-service/ml_service/app/models/antenna_selector.py†L18-L73】【F:5g-network-optimization/services/ml-service/ml_service/app/models/antenna_selector.py†L73-L145】.

## Enterprise Standards
The radio propagation layer mirrors enterprise standards.  Antenna models rely on TR 38.901 path‑loss formulas such as ABG and Close‑In for realistic link budget calculations【F:5g-network-optimization/services/nef-emulator/docs/antenna_and_path_loss.md†L1-L28】.  Mobility patterns like Linear, Random Waypoint and Manhattan Grid are implemented according to the same specification to emulate common deployment scenarios【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/README.md†L1-L30】.

## Testing & Coverage
`scripts/run_tests.sh` installs the required system packages, installs Python dependencies along with the ML service itself and then executes `pytest --cov` to gather coverage results under `CI-CD_reports/coverage_<timestamp>.txt`【F:scripts/run_tests.sh†L1-L16】.  The unit tests build a synthetic dataset via `generate_synthetic_data` and validate training as well as prediction accuracy in `test_model_training_and_prediction`【F:5g-network-optimization/services/ml-service/tests/test_model.py†L1-L30】【F:5g-network-optimization/services/ml-service/tests/test_model.py†L60-L98】.  When all 144 tests pass, coverage hovers around 83%, ensuring most modules are exercised.

---
Additional references can be found in [GETTING_STARTED](../5g-network-optimization/leftover_docks/GETTING_STARTED.md), the [Monitoring README](../5g-network-optimization/monitoring/README.md) and [Antenna & Path Loss documentation](../5g-network-optimization/services/nef-emulator/docs/antenna_and_path_loss.md).
