# Thesis Complexity-Aware ML+A3 Comparison Guide

This guide documents the current validation path for the thesis claim:
ML does not replace A3 everywhere. ML is evaluated as an improvement under high
candidate complexity, while tuned A3 remains an appropriate controller in
sparse/simple regimes. Checked-in results are historical unless they pass the
current validator and are explicitly promoted into final thesis evidence.

## Architecture

The comparison has three separate concerns:

- `5g-network-optimization/services/nef-emulator/`
  Shared NEF/exposure and emulation layer. This remains the only NEF path.
- `5g-network-optimization/services/ml-service/`
  Existing ML decision service. It remains separate and is not rewritten by the
  A3 baseline work.
- `5g-network-optimization/services/handover-baseline-service/`
  Pure Python standards-inspired A3 baseline package containing fixed A3,
  tuned A3, typed policy models, parameter validation, adapters, and metrics.

Both ML and A3 comparisons must use the same scenario, topology, UE mobility,
measurement snapshots, random seed, duration, and metrics. The intended
difference is only the decision policy. Creating a second NEF for A3 would make
the comparison weaker because measurement generation, state, timing, API
behavior, logs, and metrics would no longer be shared.

## Policies

Current policy names used by the comparison tooling:

- `ml`
  Live runner mode for the existing ML service through the shared NEF.
- `ml_policy`
  Offline replay adapter name for direct ML-service calls.
- `fixed_a3_baseline`
  Standards-inspired static A3 baseline using the baseline service.
- `tuned_a3_baseline`
  Standards-inspired non-ML A3 baseline selected from an explicit parameter
  grid using separate calibration traces or a real saved tuned config.
- `strongest_rsrp_baseline`, `strongest_sinr_baseline`, `strongest_rsrq_baseline`
  Offline classic strongest-measurement baselines.
- `load_aware_a3_baseline`
  Offline A3-style baseline that penalizes loaded targets.
- `velocity_adaptive_a3_baseline`
  Offline A3-style baseline with speed-tiered A3 parameters.
- `complexity_aware_ml_a3`
  Adaptive policy. Sparse/moderate buckets use tuned A3; high-complexity
  buckets use strict ML only if model health and fallback/override checks pass.
- `a3` and `hybrid`
  Existing legacy/live NEF modes preserved for compatibility.
- `trace_capture`
  NEF infrastructure mode for measurement capture only. UE movement and
  feature-vector generation continue, but no ML, fixed A3, tuned A3, legacy A3,
  or handover application is allowed. This is not a comparison policy.

Fixed A3 uses RSRP as the primary quantity and applies A3 offset, hysteresis,
time-to-trigger, and cooldown. Tuned A3 searches an explicit non-ML grid and
must not consume ML predictions, labels, confidence, or outputs. A3 decisions do
not have ML-like confidence values.

Default candidate-complexity buckets are:

- `0-1` viable non-serving candidates: sparse
- `2` viable non-serving candidates: moderate
- `>=3` viable non-serving candidates: high complexity

A viable candidate has RSRP >= `-115 dBm`; if SINR exists, SINR must be >=
`-5 dB`.

## Scenarios

Current scenario evidence level:

- `highway`
  Primary scenario for the next handover-focused thesis comparison. It models
  high-speed vehicle movement across a corridor and is the strongest current
  scenario, but it is still medium realism and not field validation.
- `smart_city`
  Secondary/partial evidence after the highway path is stable. It has mixed
  mobility and service classes but remains synthetic/emulated.
- Legacy simple runner and synthetic generators
  Smoke, fixture, or regression tools only unless strengthened later.

## Campaign Planning

Prepare a validation-grade command plan before running any evidence campaign:

```bash
.venv/bin/python -m scripts.policy_comparison.prepare_comparison_campaign \
  --campaign-name highway_validation_<timestamp> \
  --output-root thesis_results/campaign_highway_<timestamp> \
  --primary-scenario highway \
  --evaluation-seed 42,43,44 \
  --ue-id 202010000002001 \
  --ue-id 202010000002002 \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline,complexity_aware_ml_a3 \
  --calibration-seed 41 \
  --tuned-a3-config thesis_results/<calibration_run>/tuned_a3_config.json \
  --duration 10
```

This writes:

- `comparison_campaign_plan.json`
- `offline_commands.sh`
- `live_commands.sh`
- `analysis_commands.sh`

The generated live run commands are commented out. The file includes readiness
and plan-only commands first so a human must explicitly choose when to start the
real live runs. If `tuned_a3_baseline` or `complexity_aware_ml_a3` is selected,
the planner requires both a separate `--calibration-seed` and a real
`--tuned-a3-config`; it does not create or invent tuning results.

## Offline Comparison Flow

Policy-free traces must be captured before offline comparison. The recommended
runner starts the existing shared NEF stack, sets `/api/v1/ml/mode` to
`trace_capture`, deploys the scenario through existing scenario classes, starts
selected UEs, samples `/api/v1/ml/state/{ue_id}`, writes canonical JSONL plus
metadata, saves topology and Docker logs, and shuts the stack down. It rejects
reused output directories.

Capture the highway calibration trace:

```bash
.venv/bin/python -m scripts.policy_comparison.capture_scenario_trace \
  --scenario highway \
  --seed 41 \
  --output-dir thesis_results/highway_calibration_seed41_<timestamp> \
  --samples 300 \
  --interval-s 1.0
```

For `highway`, omitting `--ue-id` selects all 10 highway UEs
`202010000002001` through `202010000002010`. For other scenarios, pass explicit
UE IDs.

Generate the reusable tuned A3 config from that calibration trace:

```bash
.venv/bin/python -m scripts.policy_comparison.calibrate_tuned_a3 \
  --calibration-trace thesis_results/highway_calibration_seed41_<timestamp>/trace.jsonl \
  --output thesis_results/highway_calibration_seed41_<timestamp>/tuned_a3_config.json
```

The tuned config contains `selected_parameters`, `selected_score`, objective,
calibration scenario/seed/topology hash, record count, creation timestamp, and
all evaluated parameter scores. It must not consume ML predictions, labels,
confidence, or outputs.

Capture evaluation traces with disjoint seeds:

```bash
.venv/bin/python -m scripts.policy_comparison.capture_scenario_trace \
  --scenario highway \
  --seed 42 \
  --output-dir thesis_results/highway_evaluation_seed42_<timestamp> \
  --samples 300 \
  --interval-s 1.0
```

Repeat for seeds `43` and `44`.

Replay each evaluation trace through all three policies:

```bash
.venv/bin/python -m scripts.policy_comparison.run_offline_replay \
  --trace thesis_results/highway_evaluation_seed42_<timestamp>/trace.jsonl \
  --tuned-a3-config thesis_results/highway_calibration_seed41_<timestamp>/tuned_a3_config.json \
  --output-dir thesis_results/offline_highway_seed42_<timestamp> \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline \
  --ml-base-url "${ML_BASE_URL}"
```

When `ml` is selected, replay requires `/api/model-health` to report ready and
stores non-secret model metadata, including artifact hashes when available, in
the manifest. When `tuned_a3_baseline` is selected, replay prefers
`--tuned-a3-config` and rejects calibration/evaluation seed or topology overlap.
It does not retune on evaluation traces.

The lower-level sampler remains available only for already-running, manually
controlled NEF stacks:

```bash
.venv/bin/python -m scripts.policy_comparison.capture_nef_trace \
  --scenario highway \
  --seed 42 \
  --ue-id 202010000002001 \
  --samples 60 \
  --interval-s 1.0 \
  --output thesis_results/traces/highway_eval_seed42.jsonl
```

Offline replay metrics currently include:

- `handover_count`
- `stay_count`
- `ping_pong_count`
- `low_quality_step_count`
- `avg_dwell_time_s`
- `avg_decision_latency_ms`
- `min_serving_rsrp_dbm`
- `avg_serving_rsrp_dbm`
- `avg_handover_target_rsrp_dbm`
- per-UE handover/stay/ping-pong/low-quality counts

## Candidate Ranker Dataset

The current final ML artifact flow trains an absolute antenna-ID classifier.
The model-improvement path should move toward candidate ranking without
inventing performance evidence. Export labeled per-candidate rows from
policy-free calibration traces first:

```bash
.venv/bin/python -m scripts.policy_comparison.export_candidate_ranker_dataset \
  --trace thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/trace.jsonl \
  --output thesis_results/ranker_datasets/highway_seed41_ranker.jsonl \
  --forbid-evaluation-seed 42,43,44 \
  --sequence-window-steps 3 \
  --overwrite
```

The labels use future measurement windows, a serving-cell stay margin, handover
penalty, RF quality, and load penalty. The exporter writes a manifest with
trace hashes and seed-split metadata. This is a dataset contract for future
ranker training, not proof that the ranker improves handovers.

Train the offline ranker artifact and use it only in replay until it passes the
strict held-out gate:

```bash
.venv/bin/python -m scripts.policy_comparison.train_candidate_ranker_artifact \
  --dataset thesis_results/ranker_datasets/highway_seed41_ranker.jsonl \
  --output-artifact thesis_results/ranker_datasets/candidate_ranker_highway_seed41.joblib \
  --forbid-evaluation-seed 42,43,44 \
  --seed 41 \
  --overwrite
```

For threshold sweeps, replay held-out seeds with:

```bash
.venv/bin/python -m scripts.policy_comparison.run_offline_replay \
  --trace thesis_results/offline_highway_policyfree_20260610_105301/evaluation_seed42/trace.jsonl \
  --output-dir thesis_results/ranker_sweep/threshold_3/offline_replay_seed42 \
  --policies fixed_a3_baseline,tuned_a3_baseline,ml,complexity_aware_ml_a3 \
  --tuned-a3-config thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/tuned_a3_config.json \
  --ml-backend candidate_ranker \
  --ranker-artifact thesis_results/ranker_datasets/candidate_ranker_highway_seed41.joblib \
  --high-complexity-threshold 3
```

Then summarize all threshold directories:

```bash
.venv/bin/python -m scripts.policy_comparison.summarize_threshold_sweep \
  --sweep-root thesis_results/ranker_sweep \
  --output-dir thesis_results/ranker_sweep_summary \
  --required-seeds 42,43,44
```

`pass=false` blocks live ranker promotion. In the 2026-06-12 run, validation
passed but every existing highway trace had `high=0`, so this evidence cannot
support the high-complexity thesis claim.

## Live Comparison Flow

Run readiness before every live experiment:

```bash
RUN_NAME="highway_fresh_$(date +%Y%m%d_%H%M%S)"
./scripts/check_experiment_readiness.sh \
  --scenario highway \
  --output "thesis_results/${RUN_NAME}" \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline \
  --tuned-a3-config thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/tuned_a3_config.json
```

For final thesis evidence, set an explicit pretrained model and enable final
artifact gates:

```bash
.venv/bin/python -m scripts.policy_comparison.train_final_ml_artifact \
  --trace thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/trace.jsonl \
  --output-model 5g-network-optimization/services/ml-service/ml_service/app/models/antenna_selector_final.joblib \
  --feature-config 5g-network-optimization/services/ml-service/ml_service/app/config/features.yaml \
  --forbid-evaluation-seed 42,43,44 \
  --seed 41 \
  --overwrite

export ML_MODEL_HOST_DIR=/home/pvs/thesis/5g-network-optimization/services/ml-service/ml_service/app/models
export MODEL_PATH=/app/final-models/antenna_selector_final.joblib
export MODEL_PATH_HOST=/home/pvs/thesis/5g-network-optimization/services/ml-service/ml_service/app/models/antenna_selector_final.joblib
export FEATURE_CONFIG_PATH=/app/ml_service/app/config/features.yaml
export FEATURE_CONFIG_PATH_HOST=/home/pvs/thesis/5g-network-optimization/services/ml-service/ml_service/app/config/features.yaml
./scripts/check_experiment_readiness.sh \
  --final \
  --scenario highway \
  --output "thesis_results/${RUN_NAME}" \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline \
  --tuned-a3-config thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/tuned_a3_config.json
```

`--final` exports `THESIS_FINAL_RUN=1`, `REQUIRE_PRETRAINED_MODEL=1`, and
`DISABLE_SYNTHETIC_MODEL_BOOTSTRAP=1`. In that mode the ML service refuses
synthetic startup training, and live readiness requires
`/api/model-health.metadata.artifact_complete=true`.

The final model artifact must include all three sibling files:
`antenna_selector_final.joblib`, `antenna_selector_final.joblib.scaler`, and
`antenna_selector_final.joblib.meta.json`. The metadata must record the model
type/version, training source, scenario seeds, dataset size, selected features,
validation metrics, calibration state, git commit, and the SHA-256 hash of the
feature config used for training.

Plan-only mode writes the live policy sequence without starting services:

```bash
python scripts/run_enhanced_experiment.py \
  --env-file 5g-network-optimization/.env \
  --scenario highway \
  --seed 42 \
  --duration 10 \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline \
  --tuned-a3-config thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/tuned_a3_config.json \
  --output "thesis_results/${RUN_NAME}" \
  --plan-only
```

The future fresh run command shape is:

```bash
python scripts/run_enhanced_experiment.py \
  --env-file 5g-network-optimization/.env \
  --scenario highway \
  --seed 42 \
  --duration 10 \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline \
  --tuned-a3-config thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/tuned_a3_config.json \
  --output "thesis_results/${RUN_NAME}"
```

For live `tuned_a3_baseline`, pass
`--tuned-a3-config <path-to-real-tuning-json>`. The runner stages that file into
`<output>/config/tuned_a3_config.json`, mounts the staged copy read-only into the
existing NEF container, and records the staged host path in
`live_experiment_plan.json` for validation. For thesis comparison, use the
artifact produced by `scripts.policy_comparison.calibrate_tuned_a3`; do not use
hand-written selected parameters as evidence. The config must contain
`selected_parameters` with:

- `a3_offset_db`
- `hysteresis_db`
- `time_to_trigger_s`
- `cooldown_s`

Live metrics currently collected through Prometheus queries in
`scripts/run_enhanced_experiment.py` are:

- `total_handovers`
- `skipped_handovers`
- `pingpong_suppressions`
- `qos_compliance_ok`
- `qos_compliance_failed`

If Prometheus returns no series for a queried metric, the runner records that
metric as `null` and writes a `policy_metric_warnings` entry in
`experiment_summary.json`. It must not report missing series as numeric zero.
This is especially important for ML-service metrics while `/metrics` requires
authentication. Final thesis validation treats these warnings as blocking; a
live run with missing policy metrics is a diagnostic artifact, not final
evidence.

## Validation And Reporting

Validate completed run artifacts before treating them as evidence:

```bash
.venv/bin/python -m scripts.policy_comparison.validate_comparison_outputs \
  --path "thesis_results/${RUN_NAME}" \
  --expected-policies ml,fixed_a3_baseline,tuned_a3_baseline,complexity_aware_ml_a3 \
  --report-json "thesis_results/${RUN_NAME}_validation.json"
```

The validator fails on missing summaries, empty outputs, missing decision logs,
missing neighbour measurements, fake A3 confidence, invalid policy names,
offline ML decisions missing ML response/QoS/candidate-complexity debug fields,
complexity-aware decisions routed to the wrong bucket, hidden ML fallback or
geographic override metadata, missing tuned A3 config or tuning artifacts, tuned
A3 artifacts without evaluated scores, live ML logs containing `429`,
`Too Many Requests`, `500 INTERNAL`, or `ML service returned status 429`, live
ML outputs with zero QoS compliance checks, missing ML Prometheus series,
missing or partial topology, empty live metrics/logs, and model-not-ready or
synthetic-bootstrap behavior in ML evidence.

After multiple completed runs exist, generate paired statistical summaries:

```bash
.venv/bin/python -m scripts.policy_comparison.summarize_policy_statistics \
  --run thesis_results/highway_seed_41 \
  --run thesis_results/highway_seed_42 \
  --evidence-type live_experiment \
  --reference-policy fixed_a3_baseline \
  --candidate-policy ml \
  --metrics total_handovers,qos_compliance_ok \
  --output-dir thesis_results/statistics_live_<timestamp>
```

Offline and live evidence must be reported separately.

## Environment

Use `5g-network-optimization/.env.example` as the safe template. Do not commit
real `.env` values. Required runtime values include:

- `NEF_SCHEME`
- `NEF_HOST`
- `NEF_PORT`
- `ML_BASE_URL`
- `PROMETHEUS_URL`
- `FIRST_SUPERUSER`
- `FIRST_SUPERUSER_PASSWORD`

The readiness script also accepts documented local Compose defaults for URL
pieces where safe, but real credentials must be provided and are not printed.

## Limitations

This is an emulated, standards-inspired, operator-style comparison. It is not
real-world field validation and is not a complete operator RAN implementation.
Current scenarios, RF behavior, QoS observations, and Prometheus metrics come
from the local emulator stack and supporting scripts. Unit tests and smoke runs
prove software behavior; they do not prove scientific superiority of ML.

Current checked-in offline highway outputs under
`thesis_results/offline_highway_final_ml_20260611_194609/` are historical. They
show that the current pure ML artifact improves average serving RSRP but
regresses handover count, ping-pong, dwell time, target RSRP, QoS violation
proxy, and decision latency against A3. Do not claim overall ML superiority.
The next thesis evidence target is validated held-out replay where
`complexity_aware_ml_a3` improves high-complexity composite cost without
degrading sparse/moderate regimes relative to tuned A3.
