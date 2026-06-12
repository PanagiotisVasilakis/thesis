# Production-Grade Complexity-Aware ML+A3 Comparison Plan

## Summary

Build a production-grade, research-valid comparison between:

- Existing `5g-network-optimization/services/ml-service/`
- Existing shared `5g-network-optimization/services/nef-emulator/`
- Existing/new pure Python baseline package under `5g-network-optimization/services/handover-baseline-service/`

The comparison must isolate only the decision policy:

- same NEF
- same scenario
- same topology
- same UE mobility
- same measurement snapshots
- same random seed
- same duration
- same metrics
- different policy:
  - pure ML policy
  - fixed A3 baseline
  - tuned A3 baseline
  - classic strongest-signal/load-aware/velocity-adaptive baselines where supported
  - complexity-aware ML+A3 policy

No thesis experiment results should be generated until the comparison architecture, validation, readiness checks, and scenario evidence are complete. The thesis claim is not "ML always wins." The defensible claim is: **ML improves handover decisions under high candidate complexity, while tuned A3 remains appropriate in sparse/simple regimes.**

## Complexity-Aware Addendum

- [x] Define viable candidate complexity from policy-free snapshots.
  - [x] Viable candidate default: RSRP >= `-115 dBm`.
  - [x] If SINR exists, require SINR >= `-5 dB`.
  - [x] Buckets: `0-1` sparse, `2` moderate, `>=3` high by default.
- [x] Add offline `complexity_aware_ml_a3`.
  - [x] Sparse/moderate delegates to tuned A3.
  - [x] High complexity delegates to strict ML.
  - [x] Strict ML rejects fallback, geographic override, synthetic bootstrap, and model-not-ready metadata.
- [x] Add classic offline baselines.
  - [x] Strongest RSRP.
  - [x] Strongest SINR/RSRQ where present.
  - [x] Load-aware A3.
  - [x] Velocity-adaptive A3.
- [x] Add constrained composite cost and bucket summaries.
  - [x] Preserve raw counters.
  - [x] Include QoS violation, ping-pong, unnecessary handover, late/failed handover proxies, RF quality, load regression, and latency.
- [x] Add runtime `complexity_aware_ml_a3` mode.
  - [x] Expose through NEF mode API.
  - [x] Propagate candidate complexity, decision source, delegated policy, ML response metadata, QoS compliance, and fallback/override metadata.
- [x] Add candidate-ranker feature construction.
  - [x] Produce one row per viable candidate.
  - [x] Include RF absolute/delta features, load, speed, distance/alignment when available, QoS observations, handover history, and complexity bucket.
  - [x] Add sequence-aware candidate labels from policy-free future windows.
  - [x] Add reproducible JSONL exporter with trace hashes and seed-leakage checks.
  - [x] Train and validate an actual candidate-ranking model against held-out replay; validation failed the strict gate because current held-out traces contain no high-complexity snapshots.
- [x] Harden validation.
  - [x] Validator avoids optional SciPy import unless statistical reporting is requested.
  - [x] Live ML/complexity ML validation fails on missing required metrics.
  - [x] Pure ML and high-complexity ML evidence fails on hidden fallback/override/model-not-ready metadata.
  - [x] Complexity-aware decisions fail if routed to the wrong bucket.
- [x] Execute held-out offline replay for thresholds `3`, `4`, and `5`; no threshold passed the strict gate.
- [ ] Promote live validation only after held-out offline replay improves high-complexity composite cost over fixed and tuned A3.

## Core Rules

- [x] Do not invent files, APIs, routes, environment variables, metrics, datasets, or outputs.
- [x] If something is missing, document it clearly.
- [x] Create adapters/interfaces only when justified by existing repo structure.
- [x] Do not create a second NEF.
- [x] Do not duplicate the NEF emulator.
- [x] Do not create a fake NEF path.
- [x] Do not move or rewrite the ML service.
- [x] Keep the baseline as a pure, tested Python module inside `handover-baseline-service`, not a new HTTP daemon unless later proven necessary.
- [x] Do not fake tuning results.
- [x] Do not claim real-world field validation.
- [x] Use wording such as standards-inspired A3 baseline, operator-style non-ML baseline, traditional handover baseline, and emulated comparison.

## Phase 0 - Plan Tracking

- [x] Create `/home/pvs/thesis/THESIS_COMPARISON_PLAN.md`.
- [x] Store this full plan in this file.
- [x] Use Markdown checkboxes for each implementation task.
- [x] Mark completed tasks as done as work progresses.
- [x] Add notes for blockers, failed validations, and decisions.
- [x] Never mark a task complete unless validation or code evidence supports it.

## Week 1 - Canonical Trace and Policy Interface

- [x] Define a canonical measurement trace schema.
  - [x] Include scenario name.
  - [x] Include seed.
  - [x] Include timestamp or step index.
  - [x] Include UE ID.
  - [x] Include UE position.
  - [x] Include UE speed or velocity if available.
  - [x] Include visible cells.
  - [x] Include serving cell.
  - [x] Include RSRP values.
  - [x] Include RSRQ values if available.
  - [x] Include SINR values if available.
  - [x] Include cell load if available.
  - [x] Include topology hash or topology metadata.
  - [x] Exclude policy decision output.
- [x] Implement trace generation from the existing NEF/scenario path.
  - [x] Reuse existing NEF emulator/scenario data path.
  - [x] Do not create a second NEF.
  - [x] Do not depend on ML or A3 decisions.
  - [x] Fail clearly if required measurement fields are missing.
  - [x] Write deterministic JSONL plus metadata.
- [x] Define shared policy adapter contract.
  - [x] Add `MLPolicyAdapter`.
  - [x] Add `FixedA3PolicyAdapter`.
  - [x] Add `TunedA3PolicyAdapter`.
  - [x] Ensure all adapters return the same decision schema.
- [x] Define canonical decision output schema.
  - [x] Include policy name.
  - [x] Include UE ID.
  - [x] Include timestamp or step.
  - [x] Include current serving cell.
  - [x] Include selected target cell or null.
  - [x] Include decision type: `stay` or `handover`.
  - [x] Include serving measurement value.
  - [x] Include neighbor measurements considered.
  - [x] Include policy parameters.
  - [x] Include reason string.
  - [x] Include debug fields.
  - [x] Include decision latency if measurable.
  - [x] Do not include fake A3 confidence.
- [x] Validate baseline service architecture.
  - [x] No duplicate NEF emulator folder/service exists.
  - [x] `ml-service/` remains separate.
  - [x] `handover-baseline-service/` imports cleanly.
  - [x] Readiness/preflight still passes if touched.

## Week 2 - Offline Replay and Tuned A3 Discipline

- [x] Build deterministic offline replay.
  - [x] Consume canonical traces.
  - [x] Run each policy independently.
  - [x] Keep per-policy serving state.
  - [x] Use identical measurement snapshots for all policies.
  - [x] Allow policy divergence only through policy decisions.
  - [x] Produce comparable decision logs.
- [x] Strengthen fixed A3 baseline.
  - [x] Support RSRP as primary measurement.
  - [x] Support offset.
  - [x] Support hysteresis.
  - [x] Support time-to-trigger.
  - [x] Support cooldown / anti-ping-pong guard.
  - [x] Support deterministic per-UE/per-target state.
  - [x] Include explainable reason strings.
  - [x] Include debug output.
- [x] Strengthen tuned A3 baseline.
  - [x] Define explicit parameter grids.
  - [x] Evaluate offset, hysteresis, TTT, and cooldown combinations.
  - [x] Use only non-ML metrics.
  - [x] Never consume ML predictions, labels, confidence, or outputs.
  - [x] Preserve all tested configurations and scores.
  - [x] Report selected configuration honestly.
  - [x] Separate calibration seeds/traces from evaluation seeds/traces.
- [x] Add comparison metrics where available.
  - [x] Handover count.
  - [x] Ping-pong handovers.
  - [x] Dwell time.
  - [x] Unnecessary handovers.
  - [x] Low-quality serving time.
  - [x] Late handover proxy.
  - [x] Failed handover/RLF proxy if modeled.
  - [x] QoS violation proxy if modeled.
  - [x] Serving quality before/after handover.
  - [x] Load-balance impact if available.
  - [x] Decision latency.
  - [x] Per-UE summary.
  - [x] Aggregate scenario summary.
- [x] Add reproducibility manifest.
  - [x] Capture git commit.
  - [x] Capture dirty state summary.
  - [x] Capture scenario.
  - [x] Capture seed.
  - [x] Capture duration.
  - [x] Capture tick interval.
  - [x] Capture topology hash.
  - [x] Capture policy versions.
  - [x] Capture baseline parameters.
  - [x] Capture ML model metadata if available.
  - [x] Capture config references excluding secrets.

## Week 3 - Live NEF Integration and Readiness

- [x] Add live policy modes without breaking existing behavior.
  - [x] Preserve `ml`.
  - [x] Preserve `a3`.
  - [x] Preserve `hybrid`.
  - [x] Add `fixed_a3_baseline` only if safe.
  - [x] Add `tuned_a3_baseline` only if safe.
- [x] Keep A3 logic authoritative in `handover-baseline-service`.
  - [x] NEF may import/wrap the baseline package.
  - [x] Do not duplicate A3 decision logic inside NEF.
  - [x] Do not create a new NEF route unless required by existing architecture.
  - [x] Fail clearly if baseline package is unavailable.
- [x] Make baseline package available to runtime.
  - [x] Validate local Python import.
  - [x] Validate test import.
  - [x] Validate Docker/Compose import path if live runs need it.
  - [x] Avoid hidden dependency on developer shell state.
- [x] Extend experiment runner.
  - [x] Same scenario.
  - [x] Same seed.
  - [x] Same duration.
  - [x] Same topology.
  - [x] Same metrics.
  - [x] Policy selection.
  - [x] Clean output directory.
  - [x] Captured decision logs.
  - [x] Captured topology/config metadata.
  - [x] Captured Prometheus snapshots if used.
- [x] Extend readiness/preflight.
  - [x] Docker and Docker Compose exist.
  - [x] Compose config renders.
  - [x] Required env vars are present or loadable.
  - [x] ML URL configured.
  - [x] NEF URL configured.
  - [x] Prometheus URL configured.
  - [x] Superuser vars present but not printed.
  - [x] Selected scenario exists.
  - [x] Selected policy exists.
  - [x] Tuned A3 params exist before tuned live run.
  - [x] Output directory is fresh.
  - [x] Baseline import works.
  - [x] No stale output contamination.

## Week 4 - Evidence, Statistics, and Documentation

- [ ] Run validation-grade comparison only after readiness passes.
  - [x] Prepare validation-grade campaign command planner.
  - [x] Offline highway multi-seed comparison.
  - [x] Live smaller repeated highway runs.
  - [ ] Smart city as secondary evidence only after highway is stable.
- [x] Add statistical reporting.
  - [x] Paired comparisons by seed.
  - [x] Confidence intervals.
  - [x] Effect sizes where meaningful.
  - [x] Offline and live evidence separated.
  - [x] Explicit warnings about insufficient paired data.
- [x] Harden failure visibility.
  - [x] ML unavailable.
  - [x] Missing measurements.
  - [x] Invalid tuned A3 parameters.
  - [x] Missing tuned config.
  - [x] Empty output.
  - [x] Reused output directory.
  - [x] Invalid scenario.
  - [x] Invalid policy.
  - [x] Partial topology.
  - [x] Silent fallback from ML to A3 unless explicitly labeled.
- [x] Finalize documentation.
  - [x] One shared NEF.
  - [x] Separate ML service.
  - [x] Separate baseline service.
  - [x] Why a second NEF would weaken the comparison.
  - [x] Fixed A3 meaning.
  - [x] Tuned A3 meaning.
  - [x] Scenario realism level.
  - [x] Synthetic/emulated assumptions.
  - [x] Metric definitions.
  - [x] Exact commands.
  - [x] Limitations.
  - [x] No real-world field validation claim.

## Required Tests

- [x] Baseline unit tests.
  - [x] Stay when neighbor is not better enough.
  - [x] Select correct neighbor when better enough.
  - [x] No handover before TTT.
  - [x] Handover after TTT.
  - [x] Hysteresis changes decision boundary.
  - [x] Cooldown prevents immediate ping-pong.
  - [x] Invalid parameters rejected.
- [x] Tuned A3 tests.
  - [x] Deterministic grid generation.
  - [x] Invalid grid rejected.
  - [x] Best candidate selected on deterministic toy trace.
  - [x] Tested configs and scores preserved.
  - [x] Tuner does not require or consume ML outputs.
- [x] Adapter tests.
  - [x] Converts existing measurement shape.
  - [x] Fails clearly on missing required fields.
  - [x] Does not instantiate NEF.
  - [x] Does not invent measurements.
- [x] Replay tests.
  - [x] Deterministic replay.
  - [x] Identical snapshots across policies.
  - [x] Separate serving state per policy.
  - [x] No policy sees another policy's decisions.
  - [x] CLI rejects missing tuned-A3 calibration traces.
  - [x] CLI rejects calibration/evaluation seed overlap.
  - [x] CLI rejects non-empty output directories.
- [x] Architecture tests/checks.
  - [x] No duplicate NEF emulator service.
  - [x] `ml-service/` remains separate.
  - [x] Baseline imports cleanly.
  - [x] Readiness/preflight still passes if touched.

## Next Step - Offline Highway Calibration/Evaluation

This phase produces engineering evidence for the offline comparison path. It
does not produce final thesis claims or real-world field validation.

- [x] Add policy-free `trace_capture` mode to the existing NEF mode endpoint.
  - [x] Movement and feature-vector generation continue.
  - [x] ML, fixed A3, tuned A3, legacy A3, and handover application are not called.
  - [x] Decision logs include `outcome="trace_capture_no_decision"`.
  - [x] `trace_capture` is not exposed as a comparison policy.
- [x] Add scenario trace capture runner under `scripts.policy_comparison`.
  - [x] Start the existing shared NEF stack only.
  - [x] Set NEF mode to `trace_capture`.
  - [x] Deploy the selected scenario through existing scenario classes.
  - [x] Save topology JSON and stable topology hash.
  - [x] Start selected UEs and sample canonical JSONL from `/api/v1/ml/state/{ue_id}`.
  - [x] Stop UEs, capture Docker logs, and shut the stack down.
  - [x] Reject reused trace/output paths.
- [x] Add reusable tuned A3 config generation.
  - [x] Provide `python -m scripts.policy_comparison.calibrate_tuned_a3`.
  - [x] Reject missing, empty, mixed-scenario, mixed-seed, or RSRP-incomplete traces.
  - [x] Write `selected_parameters`, objective, calibration metadata, record count, evaluated scores, and creation timestamp.
  - [x] Match live `TUNED_A3_CONFIG_PATH` parameter names.
  - [x] Do not fabricate tuning results.
- [x] Strengthen offline replay.
  - [x] Use a generated tuned config for `tuned_a3_baseline` evaluation instead of retuning on evaluation traces.
  - [x] Keep calibration/evaluation split checks.
  - [x] Require ML service health when `ml` is selected.
  - [x] Capture ML model metadata from `/api/model-health` into the manifest without secrets.
  - [x] Preserve policy names: `ml_policy`, `fixed_a3_baseline`, `tuned_a3_baseline`.
- [x] Harden output validation.
  - [x] Reject live ML logs containing `429`, `Too Many Requests`, `500 INTERNAL`, or `ML service returned status 429`.
  - [x] Require live `ml` outputs to include non-zero QoS compliance checks.
  - [x] Require offline `ml_policy` decisions to include ML response/QoS debug fields.
  - [x] Require tuned A3 offline/live outputs to reference a real config or tuning artifact.
  - [x] Add tests for contaminated smoke patterns.
- [x] Run the next offline highway campaign after implementation and validation.
  - [x] Capture calibration trace: `highway`, seed `41`, all 10 highway UEs, 300 samples.
  - [x] Generate `tuned_a3_config.json` from seed `41`.
  - [x] Capture evaluation traces: seeds `42`, `43`, `44`.
  - [x] Replay evaluation traces with `ml,fixed_a3_baseline,tuned_a3_baseline`.
  - [x] Validate each offline output.
  - [x] Generate paired statistics for fixed A3 vs ML, tuned A3 vs ML, and fixed A3 vs tuned A3.
- [x] Update documentation.
  - [x] Explain `trace_capture` mode and why capture must be policy-free.
  - [x] Document calibration/evaluation commands.
  - [x] Document tuned A3 config schema.
  - [x] Separate offline evidence from live evidence.
  - [x] State that this is emulated evidence, not real-world field validation.

## Required Validation Commands

- [x] `git diff --check`
- [x] `pytest 5g-network-optimization/services/handover-baseline-service/tests -q`
- [x] `python -c "import sys; sys.path.insert(0, '5g-network-optimization/services/handover-baseline-service'); import handover_baseline; print(handover_baseline.__name__)"`
- [x] `mypy 5g-network-optimization/services/handover-baseline-service/handover_baseline` if mypy is configured/used.
- [x] `flake8 5g-network-optimization/services/handover-baseline-service --select=E9,F63,F7,F82` if flake8 is configured/used.
- [x] `python scripts/run_enhanced_experiment.py --list-scenarios` if available.
- [x] `./scripts/check_experiment_readiness.sh` if readiness/preflight is touched.

Do not run the full thesis experiment until all readiness and comparison validation requirements pass.

## Future Experiment Command

The exact command must be finalized only after the comparison runner supports policy selection and fresh output names.

Expected future shape:

```bash
bash scripts/run_thesis_experiment.sh \
  --scenario highway \
  --seed <seed> \
  --duration <duration> \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline \
  --output-dir results/thesis_highway_fresh_<timestamp>
```

Do not execute this command until the implementation and readiness checks are complete.

## Assumptions and Defaults

- [x] Primary scenario: `highway`.
- [x] Secondary scenario: `smart_city`.
- [x] `highway` is handover-focused but medium realism, not field validation.
- [x] `smart_city` is partial/secondary evidence.
- [x] Legacy simple runs and synthetic generators are smoke-only unless strengthened.
- [x] Baseline service remains a pure Python package under the service folder.
- [x] No new baseline HTTP daemon will be created unless future integration proves it necessary.
- [x] The comparison target is research-production quality: reproducible, testable, explainable, CI-friendly, and honest about limitations.

## Progress Notes

- Implemented the first production-grade comparison foundation slice:
  canonical trace schema, existing-NEF feature-vector conversion, strict ML/fixed-A3/tuned-A3 policy adapters, deterministic offline replay, offline decision metrics, reproducibility manifest, documentation, tests, and readiness policy validation.
- Added explicit live-NEF trace capture command:
  `python -m scripts.policy_comparison.capture_nef_trace`. It reads only
  `/api/v1/ml/state/{ue_id}`, requires explicit UE IDs, rejects stale trace
  output files, writes metadata, and does not call ML predictions or apply
  handovers.
- Added trace preparation plan command:
  `python -m scripts.policy_comparison.prepare_trace_plan`. It writes
  `trace_plan.json` and `trace_commands.sh` into a fresh directory, validates
  calibration/evaluation seed separation, and emits capture/replay commands
  without executing them.
- Added live NEF baseline modes through the existing `/api/v1/ml/mode` path:
  `fixed_a3_baseline` and `tuned_a3_baseline`. The NEF imports the
  authoritative `handover-baseline-service` package, does not create a second
  NEF, does not duplicate A3 logic, and requires `TUNED_A3_CONFIG_PATH` for
  tuned live mode.
- Extended `scripts/run_enhanced_experiment.py` with explicit live policy
  sequencing, `--seed`, `--policies`, `--tuned-a3-config`, and `--plan-only`.
  The runner now plans/runs each policy against the same scenario, seed,
  duration, metrics collector, and saved topology hash, and refuses stale output
  directories.
- Added statistical reporting over completed run summaries:
  `python -m scripts.policy_comparison.summarize_policy_statistics`. It reads
  existing offline `summary.json` and live `experiment_summary.json` files,
  keeps offline/live evidence separated, reports paired comparisons by seed,
  confidence intervals, effect sizes, and insufficient-pair warnings.
- Added completed-output validation:
  `python -m scripts.policy_comparison.validate_comparison_outputs`. It reads
  existing offline/live output artifacts and fails on missing summaries,
  decision logs, measurements, tuned A3 config references, policy metrics,
  topology, policy logs, invalid policy names, fake A3 confidence, and
  unlabeled ML-to-A3 fallback evidence.
- Added `docs/THESIS_COMPARISON_GUIDE.md` as the consolidated comparison guide
  covering architecture separation, one shared NEF, fixed/tuned A3 meaning,
  scenarios, offline/live commands, metric definitions, validation commands,
  environment requirements, and limitations.
- Added validation-grade campaign planning:
  `python -m scripts.policy_comparison.prepare_comparison_campaign`. It writes
  offline, live readiness/plan-only/future-run, validation, and statistics
  command files into a fresh campaign directory without executing experiments.
  Tuned A3 campaign planning requires a real tuned config and disjoint
  calibration/evaluation seeds.
- Executed a smoke-scale repeated live highway comparison for seeds 42 and 43
  with policies `ml` and `fixed_a3_baseline` only. Output validation passed
  for both runs, and the paired live statistics report was written under
  `thesis_results/campaign_highway_exec_20260601_014750/statistics/`.
  This is not final thesis evidence: it excludes tuned A3, offline multi-seed
  replay, and smart-city secondary validation.
- Fixed live-readiness blockers found during execution: ML model-health could
  stay false under Gunicorn `--preload` plus background initialization, local
  NEF credentials were internally inconsistent, highway/smart-city cell IDs did
  not match the NEF 9-character hex schema, scenario UE speed labels included
  unsupported `MEDIUM`, and generated UE IP/MAC identifiers collided with the
  seeded basic NEF scenario.
- Fixed live smoke blockers discovered after the first repeated highway run:
  ML HTTP exceptions now preserve real status codes instead of masking rate
  limits as 500s; root Compose raises `RATELIMIT_PREDICT` and
  `RATELIMIT_FEEDBACK` explicitly for controlled internal NEF-to-ML traffic;
  and pure `ml` mode now records QoS compliance from `/api/predict-with-qos`
  responses without falling back to A3.
- Rebuilt the ML and NEF images after those fixes and executed a fresh
  smoke-scale repeated live highway comparison for seeds 42 and 43 with
  policies `ml` and `fixed_a3_baseline`. The latest usable smoke artifacts are
  under `thesis_results/campaign_highway_qosfix_20260601_030420/`. Output
  validation passed for both runs, no 429/500 throttling signatures were found
  in the captured logs, and QoS compliance counters are now visible in the live
  summaries.
- The latest smoke results are still not final thesis evidence: they are only
  one-minute live smoke runs, exclude tuned A3, exclude offline multi-seed
  replay, and do not include smart-city secondary validation. In this smoke
  run, ML produced more handovers than fixed A3, so no ML-improvement claim is
  supported by these artifacts.
- Completed the next offline highway evidence step under
  `thesis_results/offline_highway_policyfree_20260610_105301/`. The first
  calibration capture attempt failed because Docker was still running an older
  NEF image without `trace_capture`; the NEF image was rebuilt and the retry
  succeeded in `calibration_seed41_retry1`.
- Captured policy-free highway traces with all 10 UEs and 300 samples each:
  calibration seed `41` plus evaluation seeds `42`, `43`, and `44`. Each trace
  contains 3,000 records and the same stable topology hash
  `222a4d805329894e53129418387e90b3d5bade8d09519a927d401638bc3cb95f`.
- Generated a real tuned A3 config at
  `thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/tuned_a3_config.json`
  from 108 evaluated non-ML A3 configurations. Selected parameters were
  `a3_offset_db=-2.0`, `hysteresis_db=1.0`, `time_to_trigger_s=1.0`, and
  `cooldown_s=5.0`.
- Offline replay initially exposed two concrete integration issues: captured
  QoS payloads included `observed_qos.timestamp`, which the ML API rejects, and
  ML predictions use NEF-supported aliases such as `antenna_2` while traces use
  runtime cell IDs such as `2`. The offline ML adapter now filters observed QoS
  to accepted fields and resolves `antenna_N` aliases using the same digit
  alias behavior as the existing NEF resolver.
- ML replay also encountered a transient dropped connection during Gunicorn
  worker autorestart. The offline ML adapter now has bounded transport retry
  handling for dropped connections while still failing on real HTTP errors.
- Completed and validated offline replay outputs for evaluation seeds `42`,
  `43`, and `44`, and generated paired offline statistics for fixed A3 vs ML,
  tuned A3 vs ML, and fixed A3 vs tuned A3. These are emulated offline evidence
  artifacts, not final thesis claims.
- Final thesis experiment execution is intentionally still unchecked.

## Next Step - Live Highway ML/Fixed-A3/Tuned-A3 Integration

- [x] Inspect live runner, NEF mode API, baseline-service bridge, Compose mounts, tuned A3 artifact, readiness script, and output validator.
- [x] Confirm the live path uses the existing shared `nef-emulator` and existing `ml-service`; no second NEF or duplicate A3 implementation is introduced.
- [x] Fix tuned A3 live runtime config handling by staging the calibrated config into the fresh run output and mounting it read-only into the existing NEF container for the tuned phase.
- [x] Update tests for tuned config staging, generated Compose override ordering, and live tuned-output validation.
- [x] Update documentation to explain the three-policy live path and the staged tuned-config mount.
- [x] Run targeted tests and static checks for the changed live runner and validator.
- [x] Run readiness/preflight for `highway` with policies `ml,fixed_a3_baseline,tuned_a3_baseline`.
- [x] Execute a short live highway comparison using seed `42`, the calibrated tuned A3 config from seed `41`, and policies `ml,fixed_a3_baseline,tuned_a3_baseline`.
- [x] Validate the live output artifacts with `scripts.policy_comparison.validate_comparison_outputs`.
- [x] Record whether the live comparison path is usable and list any real blockers before longer multi-seed live evidence.

### Live Highway Integration Notes - 2026-06-11

- A clean short live three-policy run completed at
  `thesis_results/live_highway_three_policy_clean_20260611_002459/`.
- Policies: `ml`, `fixed_a3_baseline`, `tuned_a3_baseline`; scenario `highway`;
  seed `42`; duration `1` minute per policy; tuned A3 config staged from the
  offline seed `41` calibration artifact.
- Historical note: validation originally passed with metric collection warnings
  recorded as low severity. Current thesis readiness treats
  `policy_metric_warnings` as blocking because missing Prometheus series leave
  final live evidence incomplete. Missing series are still recorded as `null`,
  never as misleading numeric zero values.
- Clean live summary metrics from this short run:
  `ml.total_handovers=203`, `fixed_a3_baseline.total_handovers=111`,
  `tuned_a3_baseline.total_handovers=70`,
  `ml.qos_compliance_ok=247`, `ml.qos_compliance_failed=80`.
- The live path is usable for short integration evidence. It is not final
  thesis evidence and does not establish an ML-improvement claim.
- Remaining production-quality metrics issue: Prometheus currently receives
  `401` when scraping authenticated `ml-service /metrics`, so ML-service-only
  Prometheus metrics such as `ml_prediction_confidence_avg` are unavailable
  until authenticated scraping is configured or those metrics are collected
  through a documented secure path.

## Final Offline Artifact Evidence - 2026-06-11

- Trained `antenna_selector_final.joblib` from the policy-free highway
  calibration trace seed `41` only. The training command explicitly forbids
  evaluation seeds `42`, `43`, and `44`.
- Final artifact files exist under
  `5g-network-optimization/services/ml-service/ml_service/app/models/`:
  `.joblib`, `.joblib.scaler`, `.joblib.meta.json`, and
  `.joblib.training_report.json`. They are intentionally ignored by git.
- `scripts/check_experiment_readiness.sh --final` passes with the artifact
  mounted at `/app/final-models/antenna_selector_final.joblib`; metadata,
  scaler, model hash, and feature-config hash validate successfully.
- Ran fresh offline highway replay for seeds `42`, `43`, and `44` under
  `thesis_results/offline_highway_final_ml_20260611_194609/`; all three output
  directories pass `scripts.policy_comparison.validate_comparison_outputs`.
- Generated statistical reports for ML vs fixed A3 and ML vs tuned A3:
  `statistics_ml_vs_fixed_a3/policy_statistical_report.md` and
  `statistics_ml_vs_tuned_a3/policy_statistical_report.md`.
- Result: current ML improves average serving RSRP, but regresses handover
  count, ping-pong count, dwell time, target RSRP, QoS violation proxy, and
  decision latency. This does not support an overall "ML beats A3" thesis claim.

## Candidate Ranker Offline Gate - 2026-06-12

- Added an offline candidate-ranker backend, trained from the policy-free
  calibration trace seed `41`, with raw UE/cell IDs excluded from features.
- Ranker dataset and artifact were written under
  `thesis_results/ranker_highway_offline_20260612_013141/ranker/`.
- Ran held-out replay for thresholds `3`, `4`, and `5` over evaluation seeds
  `42`, `43`, and `44` under
  `thesis_results/ranker_highway_offline_20260612_013141/sweep/`.
- Validation passed for all replay outputs, but the strict sweep gate failed.
  The policy-free traces contain no high-complexity snapshots:
  calibration seed `41`: `high=0`; evaluation seeds `42`, `43`, and `44`:
  `high=0`.
- Formal gate summary:
  `thesis_results/ranker_highway_offline_20260612_013141/sweep_summary_v2/threshold_sweep_summary.json`.
- Live ranker promotion was intentionally not implemented or run because the
  offline gate did not pass. The next real work is to capture or generate
  policy-free traces with `>=3` viable candidates before retraining/evaluating
  the ranker again.
