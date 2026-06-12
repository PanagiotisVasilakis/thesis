# Policy Comparison Foundation

This package contains the offline comparison foundation for the thesis
handover experiments. It is orchestration code only. It does not create a NEF,
does not duplicate the NEF emulator, and does not move or rewrite the ML
service.

## Architecture

The intended comparison path is:

```text
existing nef-emulator measurement path
        |
        | canonical policy-free measurement trace
        |
------------------------------------------------
|                       |                      |
MLPolicyAdapter         A3/classic adapters    ComplexityAwarePolicyAdapter
existing ml-service     baseline service       tuned A3 + strict ML
------------------------------------------------
        |
common decision schema and offline metrics
```

The A3 adapters delegate to
`5g-network-optimization/services/handover-baseline-service/`. They do not
contain another A3 implementation. The ML adapter calls the existing
`/api/predict-with-qos` endpoint and raises on errors instead of silently
falling back to A3.

## Campaign Planning

Use the campaign planner to generate a validation-grade command set without
executing any experiment:

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

It writes `comparison_campaign_plan.json`, `offline_commands.sh`,
`live_commands.sh`, and `analysis_commands.sh`. The real live run commands are
commented out; readiness and plan-only commands are listed first. Selecting
`tuned_a3_baseline` or `complexity_aware_ml_a3` requires a disjoint
`--calibration-seed` and a real `--tuned-a3-config` path.

## Trace Records

`MeasurementTraceRecord` is policy-free. It stores scenario, seed, timestamp,
UE position, current serving cell, visible cell measurements, and topology hash.
It rejects policy fields such as `decision_type`, `policy_name`, and
`selected_target_cell` so stale decision output cannot contaminate replay input.

The existing NEF feature-vector endpoint is:

```text
GET /api/v1/ml/state/{ue_id}
```

`feature_vector_to_trace_record()` converts that response into the canonical
trace schema. It fails if required fields such as `ue_id`, `connected_to`,
`latitude`, `longitude`, or `neighbor_rsrp_dbm` are missing.

Capture a trace from an already-running shared NEF stack with explicit UE IDs:

```bash
.venv/bin/python -m scripts.policy_comparison.capture_nef_trace \
  --scenario highway \
  --seed 42 \
  --ue-id 202010000002001 \
  --ue-id 202010000002002 \
  --samples 60 \
  --interval-s 1.0 \
  --topology-json thesis_results/<run>/topology.json \
  --output thesis_results/traces/highway_eval_seed42.jsonl
```

The command only reads `GET /api/v1/ml/state/{ue_id}`. It does not start the
stack, start UE movement, call ML predictions, or apply handovers. It rejects a
non-empty output trace and also writes a `.metadata.json` file next to the
trace.

For a policy-free scenario run, prefer the scenario wrapper. It starts the
existing shared NEF stack, sets the existing mode endpoint to `trace_capture`,
deploys the scenario, starts selected UEs, samples the same feature-vector
endpoint, saves topology/logs, and shuts the stack down:

```bash
.venv/bin/python -m scripts.policy_comparison.capture_scenario_trace \
  --scenario highway \
  --seed 41 \
  --output-dir thesis_results/highway_calibration_seed41_<timestamp> \
  --samples 300 \
  --interval-s 1.0
```

`trace_capture` is not a comparison policy. It is an infrastructure mode that
allows movement and feature-vector generation while preventing ML, A3,
baseline policies, and handover application.

For the candidate-complexity thesis claim, use `highway_dense` rather than the
standard `highway` scenario. The standard highway profile is useful for
sparse/simple regimes; `highway_dense` keeps the same corridor and UE IDs but
uses a deterministic 24-cell overlapping topology so traces can naturally
exercise `>=3` viable non-serving candidates.

Before exporting or training a candidate ranker, run the trace-complexity
preflight on every calibration and evaluation trace:

```bash
.venv/bin/python -m scripts.policy_comparison.summarize_trace_complexity \
  --trace thesis_results/highway_dense_ranker_<timestamp>/calibration_seed51/trace.jsonl \
  --trace thesis_results/highway_dense_ranker_<timestamp>/evaluation_seed61/trace.jsonl \
  --trace thesis_results/highway_dense_ranker_<timestamp>/evaluation_seed62/trace.jsonl \
  --trace thesis_results/highway_dense_ranker_<timestamp>/evaluation_seed63/trace.jsonl \
  --trace thesis_results/highway_dense_ranker_<timestamp>/evaluation_seed64/trace.jsonl \
  --trace thesis_results/highway_dense_ranker_<timestamp>/evaluation_seed65/trace.jsonl \
  --output-dir thesis_results/highway_dense_ranker_<timestamp>/trace_complexity_preflight
```

The command fails unless each trace has sufficient high-complexity coverage at
threshold `3`: at least `500` high-complexity records or at least `15%`
high-complexity records. Do not continue to tuned A3 calibration, ranker
export, or replay if this preflight fails.

## Offline Replay

`OfflineReplayRunner` replays the same measurement snapshots independently
through each policy. It maintains separate serving-cell state per policy. A
policy can diverge only through its own handover decisions; it cannot see
another policy's decisions.

## Final ML Artifact

Build the final ML artifact only from calibration traces that are disjoint from
evaluation seeds:

```bash
.venv/bin/python -m scripts.policy_comparison.train_final_ml_artifact \
  --trace thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/trace.jsonl \
  --output-model 5g-network-optimization/services/ml-service/ml_service/app/models/antenna_selector_final.joblib \
  --feature-config 5g-network-optimization/services/ml-service/ml_service/app/config/features.yaml \
  --forbid-evaluation-seed 42,43,44 \
  --seed 41 \
  --overwrite
```

The command writes `.joblib`, `.joblib.scaler`, `.joblib.meta.json`, and
`.joblib.training_report.json` files. The metadata records trace hashes,
feature-config hash, selected features, validation metrics, calibration state,
git commit, label policy, and post-training prediction sanity checks.

## Candidate Ranker Dataset

The current final artifact trainer is still absolute antenna classification.
For the next model iteration, export a per-candidate ranking dataset from the
same policy-free calibration traces:

```bash
.venv/bin/python -m scripts.policy_comparison.export_candidate_ranker_dataset \
  --trace thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/trace.jsonl \
  --output thesis_results/ranker_datasets/highway_seed41_ranker.jsonl \
  --forbid-evaluation-seed 42,43,44 \
  --sequence-window-steps 3 \
  --overwrite
```

Each row represents one viable non-serving candidate. Labels use a short future
measurement window, serving-cell stay margin, handover penalty, RF quality, and
load penalty, so the target is not a greedy strongest-signal-now label. The
exporter writes `<output>.manifest.json` with trace hashes, label-policy
parameters, seed split, feature columns, label columns, and complexity-bucket
counts. This prepares the ranker training stage without claiming ranker
performance before held-out replay validates it.

Train the offline ranker artifact from that exported dataset:

```bash
.venv/bin/python -m scripts.policy_comparison.train_candidate_ranker_artifact \
  --dataset thesis_results/ranker_datasets/highway_seed41_ranker.jsonl \
  --output-artifact thesis_results/ranker_datasets/candidate_ranker_highway_seed41.joblib \
  --forbid-evaluation-seed 42,43,44 \
  --seed 41 \
  --overwrite
```

Replay with the local ranker backend only in offline mode:

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

After replaying thresholds `3`, `4`, and `5` across held-out seeds, run the
strict gate:

```bash
.venv/bin/python -m scripts.policy_comparison.summarize_threshold_sweep \
  --sweep-root thesis_results/ranker_sweep \
  --output-dir thesis_results/ranker_sweep_summary \
  --required-seeds 42,43,44
```

If the summary reports `pass=false`, stop before live ranker work. Live serving
must not be promoted from a failed offline gate.

Prepare a safe trace workflow before capturing or replaying:

```bash
.venv/bin/python -m scripts.policy_comparison.prepare_trace_plan \
  --scenario highway \
  --ue-id 202010000002001 \
  --ue-id 202010000002002 \
  --calibration-seed 41 \
  --evaluation-seed 42,43 \
  --output-root thesis_results/trace_plan_highway_<timestamp> \
  --samples 60 \
  --interval-s 1.0 \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline,complexity_aware_ml_a3
```

This writes `trace_plan.json` and `trace_commands.sh` into a fresh directory.
It validates that calibration and evaluation seeds are disjoint and currently
allows exactly one calibration trace for tuned A3 replay. The generated command
file is explicit; it is not executed by the planner.

Use the command wrapper for trace-file replay:

```bash
.venv/bin/python -m scripts.policy_comparison.run_offline_replay \
  --trace path/to/evaluation_trace.jsonl \
  --output-dir thesis_results/offline_replay_<timestamp> \
  --policies fixed_a3_baseline,strongest_rsrp_baseline,load_aware_a3_baseline
```

For tuned A3 or complexity-aware ML+A3, first generate a reusable calibration
artifact from a separate trace:

```bash
.venv/bin/python -m scripts.policy_comparison.calibrate_tuned_a3 \
  --calibration-trace path/to/calibration_trace.jsonl \
  --output path/to/tuned_a3_config.json
```

Then replay evaluation traces with that config:

```bash
.venv/bin/python -m scripts.policy_comparison.run_offline_replay \
  --trace path/to/evaluation_trace.jsonl \
  --tuned-a3-config path/to/tuned_a3_config.json \
  --output-dir thesis_results/offline_tuned_a3_<timestamp> \
  --policies tuned_a3_baseline,complexity_aware_ml_a3 \
  --ml-base-url "${ML_BASE_URL}"
```

The command rejects reused output directories, missing tuned config or
calibration inputs for tuned A3, identical calibration/evaluation trace files,
overlapping exact records, shared calibration/evaluation seeds, and tuned
configs whose calibration scenario/topology does not match evaluation. This
prevents tuning on the same data used for evaluation.

This is not a full thesis experiment runner and it does not produce final thesis
results. It is the safe foundation required before live comparison runs. The
intended claim is adaptive: tuned A3 may win in sparse/simple regimes, while ML
must earn its use in high-candidate-complexity regimes.

## Statistical Reporting

After multiple completed offline replay or live experiment runs exist, generate
paired statistical summaries from their existing summary files:

```bash
.venv/bin/python -m scripts.policy_comparison.summarize_policy_statistics \
  --run thesis_results/offline_seed_41 \
  --run thesis_results/offline_seed_42 \
  --reference-policy fixed_a3_baseline \
  --candidate-policy ml_policy \
  --metrics handover_count,ping_pong_count,avg_dwell_time_s \
  --output-dir thesis_results/statistics_offline_<timestamp>
```

For live runs, use the live policy names and keep evidence separate:

```bash
.venv/bin/python -m scripts.policy_comparison.summarize_policy_statistics \
  --run thesis_results/live_seed_41 \
  --run thesis_results/live_seed_42 \
  --evidence-type live_experiment \
  --reference-policy fixed_a3_baseline \
  --candidate-policy ml \
  --metrics total_handovers,qos_compliance_ok \
  --output-dir thesis_results/statistics_live_<timestamp>
```

The command reads existing `summary.json` or `experiment_summary.json` files,
requires fresh output directories, keeps offline and live evidence separated,
and reports insufficient-pair warnings instead of pretending a single run is
statistically meaningful.

## Output Validation

Before using an offline replay or live run as thesis evidence, validate the
saved artifacts:

```bash
.venv/bin/python -m scripts.policy_comparison.validate_comparison_outputs \
  --path thesis_results/highway_seed_42 \
  --expected-policies ml,fixed_a3_baseline \
  --report-json thesis_results/highway_seed_42_validation.json
```

For offline replay outputs, the validator checks `summary.json`,
`manifest.json`, policy summaries, decision JSONL files, canonical decision
schema fields, neighbour measurements, and the rule that A3 policies must not
emit fake ML confidence.

For live outputs, it checks `experiment_summary.json`,
`live_experiment_plan.json`, policy metrics, policy logs, per-policy topology
files, tuned A3 config references, invalid policy names, partial topology, and
unlabeled or hidden ML-to-A3 fallback evidence. It also rejects ML
throttling/server error signatures, live ML runs with zero QoS compliance
checks, missing ML metrics, offline ML decisions without ML response/QoS/
candidate-complexity debug fields, wrong complexity-gate routing, and tuned A3
artifacts without evaluated configuration scores. It exits non-zero on blocking
issues.
