# Automated MLOps Pipeline

This directory documents the continuous deployment pipeline that builds the
Docker images, registers trained models to MLflow and gradually deploys them
using canary releases.

## Overview
1. **Docker Build** – Docker images for the NEF emulator and ML service are
   built and pushed to the registry on every commit.
2. **Model Registration** – After training, models are registered to the
   project MLflow tracking server.
3. **Canary Deployment** – Kubernetes manifests are updated to point at the new
   image tags and rolled out with a small traffic percentage before full
   promotion.

The Feast feature store under `feast_repo/` stores training features so model
training scripts can fetch consistent data across environments.  The feature
view includes mobility metrics such as `heading_change_rate`,
`path_curvature`, per-user signal variance and altitude in addition to basic
location and handover statistics.  The list of stored columns is centralised in
`feast_repo/constants.py` to avoid drift between ingestion helpers and the
schema definition.
