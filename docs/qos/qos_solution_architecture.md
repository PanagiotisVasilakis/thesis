# QoS Solution Architecture

## Overview
This document describes how the 5G Network Optimization thesis solution delivers quality of service (QoS) assurances by combining the Network Exposure Function (NEF) emulator, the machine learning (ML) handover service, and the observability toolchain. It aligns terminology with the core thesis components outlined in the project summary and MLOps documentation to ensure a consistent view across engineering and research stakeholders.

## Actors
- **UE Mobility Simulator** – The NEF emulator's mobility models (e.g., Linear, Random Waypoint, Manhattan Grid) generate per-UE movement updates and radio measurements in line with 3GPP TR 38.901 assumptions.
- **Handover Decision Plane** – `HandoverEngine` orchestrates deterministic A3 rule execution and LightGBM-driven predictions via the `LightGBMSelector` model served by the ML API.
- **Feature & Model Operations** – Feast feature store pipelines, MLflow model registry, and CI/CD automation that build images, ingest features, and promote models through canary releases.
- **Observability Stack** – Prometheus metrics exporters and Grafana dashboards monitoring latency, model accuracy, and network KPIs to validate QoS commitments.

## Interaction Summary
1. Mobility updates enter the NEF emulator, which enriches them with signal metrics and invokes the `HandoverEngine`.
2. Depending on configuration flags (e.g., `ML_HANDOVER_ENABLED`, `LIGHTGBM_TUNE`), the engine executes the A3 rule or queries the ML service for an antenna prediction.
3. The selected antenna is applied through `NetworkStateManager`, updating UE state, logging outcomes, and emitting Prometheus metrics for downstream dashboards.
4. Feast ingestion jobs persist historical traces, enabling retraining workflows that feed the LightGBM model registered in MLflow and deployed through the automated MLOps pipeline.

> **Diagram:** [NEF to ML QoS Interaction Flow](diagrams/ml_nef_interaction.drawio) – Visualizes the nominal event path from UE mobility updates through the NEF, decision plane, and downstream observability pipelines.

## Traceability to Thesis Chapters
- **Thesis Project Summary (`docs/THESIS_SUMMARY.md`)** – Provides the high-level component descriptions referenced throughout this QoS architecture.
- **Feature Engineering (`docs/feature_transforms.md` & `docs/feature_ranges_and_alerts.md`)** – Captures the feature catalog and monitoring thresholds that inform QoS scoring logic.
- **Mobility Metric Tracker (`docs/mobility_metric_tracker.md`)** – Details the KPIs visualized in Grafana for QoS validation.
- **MLOps Pipeline (`mlops/README.md`)** – Documents the automated build, registration, and canary rollout processes linked to model lifecycle management.

## Request/Response Extensions
The QoS pipeline adopts the contract documented in [`docs/integration/nef_ml_integration.md`](../integration/nef_ml_integration.md). Prediction calls move to `POST /api/v2/predict` using HTTP/2 with mTLS and OAuth 2.0 client credentials layered for defence in depth. The request payload now bundles serving cell telemetry, candidate cell metrics (including backhaul load), enriched mobility vectors, and service requirements such as latency or throughput SLAs. Responses return explicit actions (`HANDOVER`, `STAY`, `DEGRADE`, `FAILOVER`), model explainability artefacts, and fallback hints to inform deterministic recovery paths.

## Scoring
The LightGBM-based selector produces a probability distribution over all
candidate antennas. The ML service exposes the top class as
`predicted_antenna` alongside a `confidence` value (class probability) and a
derived `qos_compliance` structure. The compliance helper in
`ml_service.app.api_lib.predict` maps the declared `service_priority` to a
required confidence between `0.50` (best-effort traffic) and `0.95`
(mission-critical URLLC) using

```
required_confidence = 0.5 + (service_priority - 1) * (0.45 / 9)
```

The resulting QoS utility is calculated in two layers:

1. **Classifier Metrics** – Offline evaluation relies on the validation split
   returned by `LightGBMSelector.train`. Promotion gates require both
   `val_accuracy ≥ 0.82` and `val_f1 ≥ 0.80` for the latest run. Training jobs
   log these metrics to MLflow as well as to the Prometheus gauges
   `ml_model_training_accuracy` and `ml_model_training_samples` for historical
   tracking.
2. **Operational Utility Score** – Online decisions compute a composite score
   based on the model confidence and the QoS deltas advertised by the NEF or
   predicted by the ML response:

   - `latency_score = clamp(1 - (expected_latency_ms / latency_requirement_ms), 0, 1)`
   - `throughput_score = clamp(expected_throughput_mbps / throughput_requirement_mbps, 0, 1)`
   - `reliability_score = clamp(observed_reliability / reliability_pct, 0, 1)`

   where `clamp(x, 0, 1)` bounds the intermediate ratios to the `[0, 1]` range.
   The control plane weights these components as
   `utility = 0.4*latency_score + 0.35*throughput_score + 0.25*reliability_score`
   and multiplies by the model `confidence`. A final decision is accepted when
   both `utility ≥ 0.70` and the derived `confidence ≥ required_confidence`. The
   utility and compliance verdict are attached to the `handover.decisions` Kafka
   payload so Grafana dashboards can correlate live handovers with the utility
   distribution stored in the data lake.

Threshold breaches (e.g., sustained `utility < 0.70` or
`ml_prediction_confidence_avg < 0.6` for any antenna) emit Prometheus alerts.
Those alerts also annotate the MLflow run as “under review”, ensuring retraining
jobs can prioritise the affected cohort.

## NEF Integration
NEF integration touchpoints align with the sequence outlined in the integration blueprint: telemetry ingress, feature engineering, secure ML invocation, response handling, fallback triggering, and the `/api/v2/feedback` loop. The NEF publishes Prometheus metrics before each ML call, emits Kafka events (`handover.decisions`, `handover.fallbacks`), and stores audit trails tagged by `interaction_id`. Mobility event hooks remain in the NEF emulator's FastAPI layer, which now enforces nonce validation and TTL checks before applying ML-backed decisions.

## Configuration Knobs
Operational behaviour is primarily controlled through environment variables so
both CI pipelines and production clusters can tune safety rails consistently.

| Scope | Setting | Default | Purpose |
|-------|---------|---------|---------|
| NEF | `ML_HANDOVER_ENABLED` | `false` | Forces ML-backed decisions on/off regardless of antenna count heuristic. |
| NEF | `ML_CONFIDENCE_THRESHOLD` | `0.5` | Minimum acceptable model confidence when `qos_compliance` is unavailable. |
| NEF | `A3_HYSTERESIS_DB`, `A3_TTT_S` | `2.0`, `0.0` | Tune deterministic A3 fallback behaviour. |
| NEF | `ML_SERVICE_URL` | `http://ml-service:5050` | Target URL for `/api/predict-with-qos`. |
| ML Service | `MODEL_TYPE` | `lightgbm` | Chooses the estimator class registered in `model_init`. |
| ML Service | `NEIGHBOR_COUNT` | `3` | Number of neighbour cells whose metrics are included in feature vectors. |
| ML Service | `AUTO_RETRAIN` / `RETRAIN_THRESHOLD` | `true` / `0.1` | Enables drift-triggered retraining when `ml_data_drift_score` exceeds the threshold. |
| ML Service | `CIRCUIT_BREAKER_*` (`CB_FAILURE_THRESHOLD`, `CB_TIMEOUT`, `CB_RECOVERY_TIMEOUT`) | `5`, `2s`, `30s` | Cut off external calls while the service is degraded. |
| ML Service | `RATE_LIMIT_PER_MINUTE` | `600` | Limits `/api/predict` traffic to protect model latency SLOs. |
| ML Service | `ASYNC_MODEL_WORKERS`, `MODEL_PREDICTION_TIMEOUT` | `4`, `1.0` | Bound concurrency and per-request runtime of async predictions. |
| Control Plane | `Utility acceptance threshold` | `0.70` | SRE runbooks treat 0.70 as the default composite score required before applying an ML decision. |

Feature store toggles (`ingest_samples`, `fetch_training_data`) are also gated by
whether Feast is available. When disabled the ML pipeline falls back to local
JSON persistence via `collect_training_data.py`.

## Fallback Logic
Fallback behaviour mirrors the decision tree in the integration blueprint with
explicit hooks back into the mobile core:

1. **NEF Policy Reversion** – Every ML response updates
   `nef_handover_decisions_total` (`outcome="applied"` or `"none"`). When the
   moving average of fallbacks (tracked by `HANDOVER_FALLBACKS`) exceeds 5% or a
   single prediction returns
   `qos_compliance.service_priority_ok = False`, the NEF publishes a
   `handover.fallbacks` Kafka event. PCF subscribers treat that event as a
   control-plane trigger: policies revert to the deterministic A3 rule and
   automation patches the NEF configuration (setting `ML_HANDOVER_ENABLED=0`)
   until alerts clear.
2. **Confidence/Threshold Breach** – If the ML service omits a `qos_compliance`
   block, the NEF compares the bare `confidence` to
   `ML_CONFIDENCE_THRESHOLD`. Sub-SLA values raise
   `HANDOVER_FALLBACKS` and the event is logged for retraining.
3. **ML-Service Degradation** – Circuit breaker settings (`CB_FAILURE_THRESHOLD`,
   `CB_TIMEOUT`) wrap outbound predictions. Once tripped, the breaker returns
   synthetic `503` responses, prompting the NEF to mark the ML service as
   unhealthy. Control-plane automation toggles the NEF into policy-only mode and
   opens an incident ticket. Recovery requires both the breaker’s
   `success_threshold` and the Prometheus `ml_prediction_latency_seconds` alert
   to stabilise.
4. **Control-Plane TTLs** – Should the NEF exceed `ttl_seconds` supplied by the
   ML response, it discards the suggestion, reapplies A3, and annotates the
   `handover.fallbacks` event with `reason="ttl_expired"` so OAM automation can
   temporarily throttle UE load while telemetry recovers.

All fallbacks keep the offending payload, utility score, and confidence metrics
in MLflow for post-incident analysis and as seed data for the next retraining
cycle.

> **Diagram:** [NEF Fallback Control Flow](diagrams/ml_nef_fallback.drawio) – Summarizes the guardrails that transition traffic back to deterministic policies and log artefacts for remediation.

## Diagram References
- [NEF to ML QoS Interaction Flow](diagrams/ml_nef_interaction.drawio) – Normal mobility-to-ML orchestration path.
- [NEF Fallback Control Flow](diagrams/ml_nef_fallback.drawio) – Control-plane recovery and remediation triggers.
