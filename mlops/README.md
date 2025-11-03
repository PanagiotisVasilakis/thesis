# Automated MLOps Pipeline

This directory contains the utilities that collect QoS data from the NEF emulator, define the Feast feature store, and orchestrate model training for the ML service. The workflow supports both fully synthetic datasets and live captures streamed from the NEF stack.

## Training Workflow

1. **Collect QoS requirements** – `mlops/data_pipeline/nef_collector.py` offers synchronous helpers (`NEFQoSCollector`) that normalise QoS payloads returned by the NEF API. The module enforces type coercion, required thresholds, and descriptive errors so malformed payloads never reach the model.
2. **Generate synthetic traces** – `scripts/data_generation/synthetic_generator.py` (documented in `docs/qos/synthetic_qos_dataset.md`) can emit CSV/JSON request datasets that conform to the QoS envelopes used by the LightGBM selector.
3. **Populate Feast** – The Feast repository in `mlops/feature_store/feature_repo/` defines entities, feature views and the schema used by offline and online stores. `feature_repo/schema.py` keeps the canonical list of columns, including the QoS metrics tracked by tests in `tests/mlops/test_qos_feature_ranges.py`.
4. **Train via the ML service** – `collect_training_data.py` (under `services/ml-service/`) can call into the NEF emulator or reuse synthetic data, then trigger `/api/train`/`/api/train-async` on the ML service. Training runs emit Prometheus metrics such as `ml_model_training_duration_seconds`, which are scraped by the monitoring stack.
5. **Regression tests** – `pytest -k qos` exercises the collector, schema validation and model scoring logic. The dedicated QoS tests in `services/ml-service/ml_service/tests/` ensure confidence gating and feature extraction stay in sync with `features.yaml`.

## Serving & Deployment

- **Container builds** – `docker compose -f 5g-network-optimization/docker-compose.yml up --build` builds and runs the NEF emulator, ML service, Prometheus and Grafana locally. The same images back the Kubernetes manifests under `5g-network-optimization/deployment/kubernetes/`.
- **Configuration** – Runtime settings for QoS (handovers, circuit breakers, rate limits) are described in `docs/architecture/qos.md`. Use environment variables such as `ML_HANDOVER_ENABLED`, `ML_CONFIDENCE_THRESHOLD`, and `ASYNC_MODEL_WORKERS` to tune behaviour per deployment.
- **Observability** – Both services expose `/metrics` endpoints. Grafana dashboards in `5g-network-optimization/monitoring/grafana/` visualise prediction latency, training statistics, and QoS compliance/fallback counters.

## Repository Layout Highlights

- `data_pipeline/nef_collector.py` – Validates and structures QoS requirements fetched from the NEF API.
- `feature_store/feature_repo/` – Feast configuration (entities, feature view, schema utilities).
- `feast_repo/` – Example Feast repository for local materialisation and experimentation.
- `tests/mlops/test_qos_feature_ranges.py` – Regression tests ensuring the Feast schema and QoS validators accept in-range data and reject violations.

Together these components provide a repeatable path from QoS data ingestion to model training and deployment under Docker Compose or Kubernetes. Whenever you extend the pipeline, update the relevant schema helpers and tests so the training and serving paths remain aligned.
