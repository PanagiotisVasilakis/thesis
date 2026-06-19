# Physical Handover V3 Runbook

All commands run from the repository root with `.venv/bin/python`. Use a fresh
timestamped result root. Never reuse an output directory.

## 1. Capture Training Data

For every scenario `highway_sparse_v2`, `highway_moderate_v2`, and
`highway_dense_v2`, capture seeds `101-115`:

```bash
.venv/bin/python -m scripts.policy_comparison.capture_scenario_trace \
  --scenario highway_dense_v2 --seed 101 \
  --samples 360 --interval-s 1 \
  --output-dir thesis_results/<root>/training/highway_dense_v2/seed101
```

Validate every trace before continuing:

```bash
.venv/bin/python -m scripts.policy_comparison.validate_physical_trace \
  thesis_results/<root>/training/highway_dense_v2/seed101/trace.jsonl \
  --require-complexity
```

Use `--require-complexity` only for dense/moderate profiles. Sparse is expected
to have no threshold-3 coverage.

## 2. Tune Classic Baselines

Create one tuned-A3 config per density using only training seeds `101-115`:

```bash
.venv/bin/python -m scripts.policy_comparison.calibrate_tuned_a3 \
  --calibration-trace thesis_results/<root>/training/highway_dense_v2/seed101/trace.jsonl \
  --calibration-trace thesis_results/<root>/training/highway_dense_v2/seed102/trace.jsonl \
  --output thesis_results/<root>/baselines/highway_dense_v2_tuned_a3.json
```

Repeat the trace option for every training seed and repeat the command for all
three density profiles.

## 3. Export Oracle Labels And Train The Model Ladder

Export all training traces. Seeds `201-210` remain forbidden:

```bash
.venv/bin/python -m scripts.policy_comparison.export_oracle_ranker_dataset \
  --trace thesis_results/<root>/training/highway_dense_v2/seed101/trace.jsonl \
  --output thesis_results/<root>/model/oracle_dataset.jsonl \
  --manifest thesis_results/<root>/model/oracle_dataset.manifest.json \
  --horizon-steps 20

.venv/bin/python -m scripts.policy_comparison.train_oracle_model_ladder \
  --dataset thesis_results/<root>/model/oracle_dataset.jsonl \
  --manifest thesis_results/<root>/model/oracle_dataset.manifest.json \
  --output-artifact thesis_results/<root>/model/oracle_ranker.joblib
```

Supply every training trace to the export command. Raw UE/cell identifiers are
metadata only and leave-one-seed-out validation is mandatory.

## 4. Capture Tuning Seeds And Apply The Tuning Gate

Capture seeds `116-120` exactly as above. Tune only replay decision parameters
against dense tuning traces:

```bash
.venv/bin/python -m scripts.policy_comparison.tune_oracle_ranker_replay \
  --trace thesis_results/<root>/tuning/highway_dense_v2/seed116/trace.jsonl \
  --tuned-a3-config thesis_results/<root>/baselines/highway_dense_v2_tuned_a3.json \
  --artifact thesis_results/<root>/model/oracle_ranker.joblib \
  --output-artifact thesis_results/<root>/model/oracle_ranker_tuned.joblib \
  --report thesis_results/<root>/tuning/oracle_replay_tuning.json
```

Supply all five tuning traces. Exit code `2` means no configuration passed.
Stop there and report the negative result. A passing run writes
`tuning/protocol_lock.json`; that file freezes the artifact hash, margin, and
complexity threshold and unlocks final capture.

## 5. Final Seeds

Only after tuning passes, capture all three profiles for seeds `201-210` using:

```bash
.venv/bin/python -m scripts.policy_comparison.capture_scenario_trace \
  --scenario highway_dense_v2 --seed 201 --samples 360 --interval-s 1 \
  --protocol-path thesis_results/<root>/tuning/protocol_lock.json \
  --output-dir thesis_results/<root>/final/traces/highway_dense_v2/seed201
```

For every final trace, replay:

```bash
.venv/bin/python -m scripts.policy_comparison.run_offline_replay \
  --trace thesis_results/<root>/final/traces/highway_dense_v2/seed201/trace.jsonl \
  --output-dir thesis_results/<root>/final/replay/highway_dense_v2/seed201 \
  --tuned-a3-config thesis_results/<root>/baselines/highway_dense_v2_tuned_a3.json \
  --ml-backend oracle_ranker \
  --oracle-artifact thesis_results/<root>/model/oracle_ranker_tuned.joblib \
  --high-complexity-threshold <locked-threshold> \
  --policies fixed_a3_baseline,tuned_a3_baseline,strongest_rsrp_baseline,strongest_sinr_baseline,strongest_rsrq_baseline,load_aware_a3_baseline,velocity_adaptive_a3_baseline,conditional_handover_baseline,no_handover_baseline,ml,complexity_aware_ml_a3
```

Validate each replay output. After all 30 paired runs pass validation, run
`summarize_v3_final_gate` with every replay directory and the generated
protocol lock. A failed final gate is the final result; do not retune or replace
the frozen holdout seeds.
