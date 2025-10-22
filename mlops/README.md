# Automated MLOps Pipeline

This directory documents the continuous deployment pipeline that builds the
Docker images, registers trained models to MLflow and gradually deploys them
using canary releases.

## Overview
The automation stitches together both the **training pipeline** and
**serving pipeline** so that the same artefacts, schema definitions, and
validation gates apply throughout the model lifecycle.

### Training Pipeline Stages
1. **Feature Materialisation** – Nightly Feast jobs materialise feature views
   defined in `feast_repo/feature_repo.py` to the online store and historical
   parquet buckets. The schema is anchored in
   `feast_repo/constants.py` so offline training code and online serving
   requests stay aligned.
2. **Model Training** – `collect_training_data.py` streams labelled mobility
   traces from the NEF emulator, optionally persisting them through
   `ml_service.app.data.feature_store_utils.ingest_samples`. The ML service
   consumes that dataset through `/api/train`, invoking
   `ml_service.app.models.lightgbm_selector.LightGBMSelector.train` with
   validation splits and early-stopping callbacks to persist a new model
   artifact.
3. **Evaluation & Approval** – Continuous integration executes
   `pytest -k train` against the ML service package, surfacing the weighted QoS
   metrics logged by the training route. Pipeline logic inspects the resulting
   MLflow run for minimum accuracy/F1 scores and records a promotion decision in
   the registry tags. Models that meet the service-level thresholds are
   transitioned to the `Staging` stage automatically.
4. **Model Registration** – Approved runs are versioned and promoted within the
   MLflow registry. Model metadata (feature store commit hash, training config)
   is stored alongside the model to guarantee reproducibility.

### Serving Pipeline Stages
1. **Docker Build** – Multi-stage Dockerfiles build the NEF emulator and ML
   service images on every commit. The build output is tagged with the MLflow
   model version when the pipeline is triggered by a registry event.
2. **Artifact Sync** – The deployment job syncs the promoted model bundle from
   MLflow to the serving image, injecting the corresponding Feast registry
   snapshot so online features stay consistent with the trained schema.
3. **Canary Deployment** – Kubernetes manifests are rendered through Helm to
   reference the new image tag and model version. Argo Rollouts shifts 5% of the
   traffic to the canary, running online shadow evaluations before promoting to
   100%.
4. **Post-Deployment Verification** – Automated smoke tests call
   `/api/v2/predict` with synthetic telemetry, while Prometheus monitors model
   drift, latency, and error budgets. Failing checks trigger rollback hooks that
   revert the rollout to the previous stable tag.

The Feast feature store under `feast_repo/` stores training features so model
training scripts can fetch consistent data across environments. The feature view
includes mobility metrics such as `heading_change_rate`, `path_curvature`,
per-user signal variance and altitude in addition to basic location and
handover statistics. The list of stored columns is centralised in
`feast_repo/constants.py` to avoid drift between ingestion helpers and the
schema definition.
