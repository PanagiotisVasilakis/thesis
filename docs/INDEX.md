# Documentation Index

Use this page as the entry point for the repository documentation. The sections below group the most relevant guides by topic and highlight the canonical sources to consult first.

## Getting Started

- **[docs/README.md](README.md)** – **START HERE**: Documentation overview and navigation guide
- **[QUICK_START.md](QUICK_START.md)** – Essential commands and quick reference for running the system end-to-end
- **[COMPLETE_DEPLOYMENT_GUIDE.md](COMPLETE_DEPLOYMENT_GUIDE.md)** – Comprehensive step-by-step guide from installation to generating thesis results
- **[THESIS_ABSTRACT.md](THESIS_ABSTRACT.md)** – Research overview, problem statement, and contributions
- **[RESULTS_GENERATION_CHECKLIST.md](RESULTS_GENERATION_CHECKLIST.md)** – Systematic workflow for generating thesis results
- **[CODE_ANALYSIS_AND_IMPROVEMENTS.md](CODE_ANALYSIS_AND_IMPROVEMENTS.md)** – Professional code review with improvement recommendations for thesis
- [`README.md`](../README.md) – repository overview, environment variables, and high-level system description

## Services

- [`services/nef-emulator/README.md`](../5g-network-optimization/services/nef-emulator/README.md) – NEF emulator architecture, APIs, and configuration knobs.
- [`services/ml-service/README.md`](../5g-network-optimization/services/ml-service/README.md) – ML service routes, authentication, rate limiting, and deployment guidance.

## Configuration & QoS

- [`docs/architecture/qos.md`](architecture/qos.md) – **Canonical reference for QoS flows, admission control, metrics, configuration, feature store integration, validation architecture, data drift monitoring, and feature transforms.**

## Observability

- [`5g-network-optimization/monitoring/README.md`](../5g-network-optimization/monitoring/README.md) – Prometheus and Grafana configuration, scrape targets, and dashboards.
- Grafana dashboards: `5g-network-optimization/monitoring/grafana/dashboards/` (import into Grafana for a ready-made ML service view).

## Deployment

- [`5g-network-optimization/docker-compose.yml`](../5g-network-optimization/docker-compose.yml) – Compose stack that runs NEF, ML service, Prometheus, and Grafana.
- [`5g-network-optimization/deployment/kubernetes/README.md`](../5g-network-optimization/deployment/kubernetes/README.md) – Kubernetes manifests and tips for running the stack in a cluster.
<!-- legacy overview removed; see README and this index instead -->

## ML & Data Pipeline

- [`mlops/README.md`](../mlops/README.md) – QoS data collectors, Feast feature store layout, and training workflow.
- [`docs/qos/synthetic_qos_dataset.md`](qos/synthetic_qos_dataset.md) – Synthetic dataset schema and sampling profiles with academic references.

## Testing & Tooling

- [`scripts/setup_tests.sh`](../scripts/setup_tests.sh) – Bootstrap script to install dependencies and run pytest with coverage.
- [`tests/README.md`](../tests/README.md) – Test suite layout and prerequisites.
- QoS-specific tests: `services/ml-service/ml_service/tests/` and `tests/mlops/test_qos_feature_ranges.py` provide regression coverage for QoS data paths.

## Contributing & Documentation Hygiene

- **All QoS-related documentation is consolidated in [`docs/architecture/qos.md`](architecture/qos.md).** This single comprehensive document supersedes all previous QoS design notes and covers flows, configuration, metrics, validation, feature stores, and testing.
- When adding or updating QoS features, update `docs/architecture/qos.md` to keep it accurate and complete.
- Archived or exploratory documents live under `docs/_archive/`. Tombstone headers explain why each file was retired; consult them if you need historical context.


