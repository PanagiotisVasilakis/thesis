# Documentation Index

Use this page as the entry point for the repository documentation. The sections below group the most relevant guides by topic and highlight the canonical sources to consult first.

## Getting Started

- **[docs/README.md](README.md)** – **START HERE**: Documentation overview and navigation guide
- **[QUICK_START.md](QUICK_START.md)** – Essential commands and quick reference for running the system end-to-end
- **[COMPLETE_DEPLOYMENT_GUIDE.md](COMPLETE_DEPLOYMENT_GUIDE.md)** – Comprehensive step-by-step guide from installation to generating thesis results
- **[THESIS_ABSTRACT.md](THESIS_ABSTRACT.md)** – Research overview, problem statement, and contributions
- **[RESULTS_GENERATION_CHECKLIST.md](RESULTS_GENERATION_CHECKLIST.md)** – Systematic workflow for generating thesis results
- **[CODE_ANALYSIS_AND_IMPROVEMENTS.md](CODE_ANALYSIS_AND_IMPROVEMENTS.md)** – Professional code review with improvement recommendations for thesis
- **[PING_PONG_PREVENTION.md](PING_PONG_PREVENTION.md)** – **NEW FEATURE**: ML ping-pong prevention implementation and thesis demonstration
- **[ML_VS_A3_COMPARISON_TOOL.md](ML_VS_A3_COMPARISON_TOOL.md)** – **NEW TOOL**: Automated comparative experiment runner and visualization generator
- **[AUTOMATED_EXPERIMENT_RUNNER.md](AUTOMATED_EXPERIMENT_RUNNER.md)** – **NEW TOOL**: Comprehensive thesis-grade experiment automation with full audit trail
- **[HANDOVER_HISTORY_ANALYZER.md](HANDOVER_HISTORY_ANALYZER.md)** – **NEW TOOL**: Deep handover pattern analysis and behavioral insights
- **[MULTI_ANTENNA_TESTING.md](MULTI_ANTENNA_TESTING.md)** – **NEW TESTS**: Comprehensive multi-antenna scenario validation (15+ tests)
- **[ENHANCED_LOGGING.md](ENHANCED_LOGGING.md)** – **NEW FEATURE**: JSON-structured handover decision logging for thesis analysis
- **[CONFIDENCE_CALIBRATION.md](CONFIDENCE_CALIBRATION.md)** – **NEW FEATURE**: ML probability calibration for better QoS decisions
- **[THESIS_CLAIMS_VALIDATION.md](THESIS_CLAIMS_VALIDATION.md)** – **NEW TESTS**: Automated validation of all thesis claims
- **[THESIS_DEMONSTRATIONS.md](THESIS_DEMONSTRATIONS.md)** – **CRITICAL**: Live defense demonstrations with honest assessment
- **[⚠️_HONEST_ASSESSMENT_AND_RECOMMENDATIONS.md](⚠️_HONEST_ASSESSMENT_AND_RECOMMENDATIONS.md)** – **MUST READ**: Truthful evaluation and mitigation strategies
- [`README.md`](../README.md) – repository overview, environment variables, and high-level system description
- [`IMPLEMENTATION_SUMMARY.md`](../IMPLEMENTATION_SUMMARY.md) – Summary of ping-pong prevention implementation

## Services

- [`services/nef-emulator/README.md`](../5g-network-optimization/services/nef-emulator/README.md) – NEF emulator architecture, APIs, and configuration knobs.
- [`services/ml-service/README.md`](../5g-network-optimization/services/ml-service/README.md) – ML service routes, authentication, rate limiting, and deployment guidance.

## Configuration & QoS

- [`docs/architecture/qos.md`](architecture/qos.md) – **Canonical reference for QoS flows, admission control, metrics, configuration, feature store integration, validation architecture, data drift monitoring, and feature transforms.**
- [`QOS_INTEGRATION_PLAN.md`](../QOS_INTEGRATION_PLAN.md) – **ROADMAP**: 5-phase plan for full QoS integration with real metrics, compliance engine, and closed-loop adaptation
- [`QOS_MODEL_PERFORMANCE.md`](QOS_MODEL_PERFORMANCE.md) – **RESULTS**: Latest QoS-aware training run, feature importances, and retraining workflow guidance

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


