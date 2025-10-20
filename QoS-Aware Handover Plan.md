QoS-Aware Handover Plan

Instructions for the agent : This document outlines a detailed plan to enhance the existing ML-based handover system to be QoS-aware, accommodating different service types (eMBB, URLLC, mMTC) with their specific requirements. The plan is structured into phases with clear deliverables, timelines, and success criteria. The goal is to tackle it step by step, ensuring thorough validation and integration at each stage. Every time a phase is completed, cross a line through it to indicate progress. Use the sequentialthinking mcp if you think it will help.

Progress to date (concrete repo changes):

- Repaired and rebuilt `services/ml-service/ml_service/app/api/di_routes.py` (fixed syntax, restored DI endpoints including `/predict-with-qos`).
- Added `PredictionRequestWithQoS` schema and unit tests in `services/ml-service/ml_service/tests/test_qos_schema.py` (2 tests, green).
- Updated `services/ml-service/ml_service/app/config/features.yaml` to include QoS-related feature definitions.
- Added `/predict-with-qos` route to the non-DI API (`services/ml-service/ml_service/app/api/routes.py`).

These baseline, low-risk changes complete Phase 0's discovery and initial API/schema readiness for QoS fields.

~~Phase 0 – Discovery (Week 1)~~ ✅ COMPLETED

~~Audit PredictionRequest, feature config, NEF event payloads; capture current QoS-related gaps.~~
~~Define QoS taxonomies (eMBB/URLLC/mMTC/default) and required fields (latency, reliability, throughput, priority).~~
~~Gather any available traces or craft synthetic profiles to cover each service class.~~
~~Exit: Approved spec describing new fields, signal processing expectations, success metrics (QoS compliance, throughput, latency hit rates).~~

Phase 1 – Solution Architecture (Week 2)

Status: IN-PROGRESS (initial, low-risk implementation started)

Design request/response extensions, storage schema updates, and config knobs (per-service weights, defaults).
Choose modeling approach: single LightGBM with QoS features vs. service-conditional models; draft multi-objective scoring function.
Align NEF handover engine changes: how confidence thresholds map to QoS priorities and fallbacks.
Exit: Architecture doc + sequence diagrams, backlog of implementation tasks.

Phase 2 – Data & Feature Pipeline (Weeks 2–3)

Extend synthetic data generators and NEF collectors to emit QoS annotations and service requirements.
Update features.yaml, validation ranges, and Feast feature definitions (if used) to include QoS metrics and priority weights.
Introduce data quality checks for service-type balance and requirement bounds.
Exit: Sample dataset with QoS coverage, passing validation scripts.

Phase 3 – Service & API Implementation (Weeks 3–5)

Add PredictionRequestWithQoS, request validators, and backward-compatible API routes (/predict-with-qos or upgrade existing route).
Implement QoSServiceClassifier module, priority weighting utilities, and configuration injection.
Update AntennaSelector (and derived models) to ingest QoS features, compute multi-objective scores, and expose compliance metadata.
Wire Prometheus metrics for QoS compliance, service-type success counts, and misclassification alerts.
Exit: Flask app routes, helpers, and schema updates with unit tests green.

Phase 4 – Model Training & Tuning (Weeks 5–6)

Retrain baseline LightGBM with QoS-enhanced features; evaluate per-service precision/latency.
Experiment with class-specific weighting, threshold tuning, and optional ensemble strategies.
Capture training notebooks/scripts, feature importance, and confusion matrices per service type.
Exit: Frozen model artifact, documented training pipeline, automated retraining path.

Phase 5 – NEF Integration & End-to-End Logic (Weeks 6–7)

Extend NEF handover engine to pass QoS context, interpret compliance flags, and adjust fallback heuristics.
Add safe degradation: if QoS data missing or compliance low, revert to A3 rule with logged reason.
Update integration tests to cover ML + QoS pipeline and rule-based fallback.
Exit: End-to-end tests (unit, integration, e2e) passing with QoS scenarios.

Phase 6 – Evaluation & Experiments (Weeks 7–8)

Define scenarios per service class (low latency, high throughput, massive device density); run ML vs A3 baselines.
Collect metrics: handover success, QoS compliance rates, latency/throughput distributions, resource utilization.
Perform statistical analysis (paired t-tests, Cohen’s d, confidence intervals) for each scenario.
Exit: Experiment report ready for thesis appendix, reproducible scripts, figures generated.

Phase 7 – Deployment & Monitoring (Week 9)

Update Docker/K8s manifests with new env vars and secrets for QoS weights.
Create rollout checklist: config migration, model update, feature flags, rollback procedures.
Enhance dashboards with QoS lens (service-type success charts, compliance heatmaps).
Exit: Deployment docs, runbooks, QA sign-off.

Phase 8 – Documentation & Thesis Integration (Weeks 9–10)

Refresh API docs, README, and thesis chapters (design, implementation, evaluation, discussion).
Document limitations, assumptions (synthetic QoS data, service labeling heuristics), and future work.
Compile verification artifacts (test report, coverage updates, metrics snapshots).
Exit: Thesis-ready narrative, supplemental materials packaged.

Risks & Mitigations

Data imbalance between service types → synthesize balanced datasets, apply sampling/weighting.
QoS labels unreliable → add validation rules, fallback defaults, telemetry on missing/invalid inputs.
Model regressions for default traffic → run regression suite comparing legacy vs QoS-enhanced outputs.
Increased inference latency → profile pipeline, cache classifier outputs, enforce async execution path.

Success Criteria

≥95% QoS compliance for URLLC latency targets in simulation; ≥10% throughput improvement for eMBB vs A3; mMTC resource usage within configured ceilings.
No regression in overall handover success rate or latency budget.
Prometheus metrics and dashboards reflect QoS status with alerting thresholds defined.
Thesis evaluation chapter includes statistically significant results supporting conclusions.

Next Steps

- Continue Phase 1: implement QoS classifier and feature injection into AntennaSelector; add unit tests and run CI.
- After Phase 1, proceed to Phase 2 (data pipeline) and Phase 3 (service/API implementation).

