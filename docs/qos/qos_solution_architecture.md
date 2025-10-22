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

## Traceability to Thesis Chapters
- **Thesis Project Summary (`docs/THESIS_SUMMARY.md`)** – Provides the high-level component descriptions referenced throughout this QoS architecture.
- **Feature Engineering (`docs/feature_transforms.md` & `docs/feature_ranges_and_alerts.md`)** – Captures the feature catalog and monitoring thresholds that inform QoS scoring logic.
- **Mobility Metric Tracker (`docs/mobility_metric_tracker.md`)** – Details the KPIs visualized in Grafana for QoS validation.
- **MLOps Pipeline (`mlops/README.md`)** – Documents the automated build, registration, and canary rollout processes linked to model lifecycle management.

## Request/Response Extensions
The QoS pipeline adopts the contract documented in [`docs/integration/nef_ml_integration.md`](../integration/nef_ml_integration.md). Prediction calls move to `POST /api/v2/predict` using HTTP/2 with mTLS and OAuth 2.0 client credentials layered for defence in depth. The request payload now bundles serving cell telemetry, candidate cell metrics (including backhaul load), enriched mobility vectors, and service requirements such as latency or throughput SLAs. Responses return explicit actions (`HANDOVER`, `STAY`, `DEGRADE`, `FAILOVER`), model explainability artefacts, and fallback hints to inform deterministic recovery paths.

## Scoring
*Placeholder for describing QoS scoring formulas, thresholds, and integration with Prometheus alerts.*

## NEF Integration
NEF integration touchpoints align with the sequence outlined in the integration blueprint: telemetry ingress, feature engineering, secure ML invocation, response handling, fallback triggering, and the `/api/v2/feedback` loop. The NEF publishes Prometheus metrics before each ML call, emits Kafka events (`handover.decisions`, `handover.fallbacks`), and stores audit trails tagged by `interaction_id`. Mobility event hooks remain in the NEF emulator's FastAPI layer, which now enforces nonce validation and TTL checks before applying ML-backed decisions.

## Configuration Knobs
*Placeholder for enumerating environment variables, feature flags, and tuning parameters impacting QoS behaviour.*

## Fallback Logic
Fallback behaviour mirrors the decision tree in the integration blueprint. Transport or security failures immediately trigger the deterministic A3 rule while opening incidents. Low-confidence ML responses (<0.8) or expired TTLs defer to the A3 rule but keep predictions for retraining datasets. If the ML service requests `FAILOVER`, the NEF suspends further ML invocations until health checks pass, ensuring QoS guarantees remain intact during degradations.

## Diagram References
*Placeholder for linking sequence diagrams, deployment topologies, and data flow illustrations supporting the QoS architecture.*
