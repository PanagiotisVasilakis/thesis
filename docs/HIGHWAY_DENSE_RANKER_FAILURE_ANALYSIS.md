# Highway Dense Ranker Failure Analysis

This note freezes `thesis_results/highway_dense_ranker_20260612_023651/` as diagnostic evidence, not thesis-final proof.

The dense highway trace generation and validation pipeline worked:

- Calibration seed `51` and held-out seeds `61-65` were captured from policy-free `trace_capture` mode.
- Trace-complexity preflight passed for thresholds `3` and `4`.
- Replay output validation reported no validation issues.
- The strict offline threshold sweep completed and produced `pass=false`.

The failure is a real controller/model failure:

- Threshold `3` failed with mean high-complexity improvement `-2.5075`.
- Threshold `4` failed with mean high-complexity improvement `-2.4405`.
- Threshold `5` had no high-complexity observations in this topology.
- On seed `61`, tuned A3 produced `600` handovers, ML everywhere produced `866`, and adaptive ML+A3 produced `1370`.

Main diagnosis:

- The ranker selected handover targets too often.
- The adaptive controller alternated between ML high-complexity decisions and sparse A3 decisions.
- ML handovers changed serving-cell state in a way that caused extra subsequent sparse-region A3 handovers.
- The old ranker validation had good RMSE but poor target-selection behavior, so RMSE alone was not a defensible promotion signal.

Live validation was correctly blocked. The current ranker artifact must not be promoted to the runtime ML service. The next valid step is offline model recovery: stay-aware labels, conservative ranker thresholds, replay-state features, dwell guards, A3 re-entry guards, and held-out replay before any live run.

## Recovery Attempt: `highway_dense_ranker_recovery_20260612_102052`

The recovery implementation added stay-aware labels, state-aware replay features, conservative ranker margins, an A3 re-entry guard, replay tuning on calibration seed `51`, and decision diagnostics.

Calibration replay tuning passed on seed `51` with:

- complexity threshold `4`
- ranker minimum margin `30.0`
- ML dwell guard `0.0s`
- A3 re-entry guard `3.0 dB`
- calibration high-complexity improvement `15.43%`

Held-out replay on seeds `61-65` still failed the strict gate:

- Threshold `3`: mean high-complexity improvement `-0.6225`.
- Threshold `4`: mean high-complexity improvement `-0.6126`.
- Threshold `5`: no high-complexity observations.
- Threshold `4` validation issues: none.
- Threshold `4` ping-pong increased to a mean of `67.2` versus tuned A3 mean `6.8`.
- Threshold `4` adaptive ML+A3 did not beat ML-everywhere or tuned-A3-everywhere overall.

Decision diagnostics for threshold `4` show the main remaining failure:

- Adaptive ML+A3 still alternates between `ml_high_complexity` and `a3_complexity_gate`.
- Sparse handovers after recent ML handovers remain high: `151-181` per held-out seed.
- ML-everywhere is sometimes lower cost than adaptive routing, which means the sparse A3 re-entry behavior is still damaging the mixed controller.

This recovery run is diagnostic only. Live ranker promotion remains blocked until a future held-out offline sweep passes the strict gate.

## Segment Authority Recovery Attempts

Two controller-level segment-authority variants were tested after the stay-aware ranker recovery.

### Segment Ranker-Hold: `highway_dense_ranker_segment_recovery_20260612_110906`

This variant let ML retain authority for a short post-ML segment by routing sparse/moderate records to the ranker during the hold window.

Calibration selected:

- complexity threshold `4`
- ranker minimum margin `30.0`
- ML dwell guard `0.0s`
- segment hold `6.0s`
- A3 re-entry guard `3.0 dB`

Held-out replay failed:

- threshold `3` mean high-complexity improvement: `-0.0896`
- threshold `4` mean high-complexity improvement: `-0.0623`
- threshold `4` mean ping-pong: `20.0`
- validation issues: `0`

### Segment Stay-Hold: `highway_dense_ranker_segment_stay_recovery_20260612_114806`

This variant made the post-ML segment hold an explicit controller stay decision. It did not call ranker or A3 during sparse/moderate hold records.

Calibration selected:

- complexity threshold `4`
- ranker minimum margin `30.0`
- ML dwell guard `0.0s`
- segment stay-hold `6.0s`
- A3 re-entry guard `10.0 dB`

Held-out replay still failed:

- threshold `3` mean high-complexity improvement: `-0.0838`
- threshold `4` mean high-complexity improvement: `-0.0643`
- threshold `4` mean ping-pong: `20.0`
- validation issues: `0`

The segment stay-hold guard executed correctly: threshold `4` produced `696-888` `ml_segment_stay_hold` records per held-out seed. The remaining failure is that A3 resumes after the calibrated `6s` hold and still creates `149-177` sparse handovers after recent ML handovers per seed.

Live validation remains blocked.

## Multi-Calibration Segment Controller: `highway_dense_segment_model_20260618_164934`

This run implemented the next offline-only recovery path: five calibration
seeds, multi-trace tuned A3 calibration, and a two-stage segment controller.
It remains diagnostic, not thesis-final evidence.

What passed:

- New policy-free calibration traces `52-55` were captured in
  `trace_capture` mode with no handovers applied by the runner.
- Existing calibration seed `51` was copied into the same root for a
  five-seed calibration bundle.
- Calibration seeds `51-55` and held-out seeds `61-65` all share topology hash
  `5c3561197501a4e9acb66628be58a8bdc3d0db077928217d003b86518cdea5eb`.
- Trace-complexity preflight passed for thresholds `3` and `4`; threshold `5`
  still has no high-complexity coverage.
- Multi-trace tuned A3 calibration used `18,000` calibration records.
- Segment dataset export produced `18,249` candidate rows, `4,750` entry rows,
  and `165,037` exit rows, with no raw UE/cell ID features.
- Segment training passed row/model gates:
  - candidate target-selection error `0.0`
  - entry precision `0.9793`
  - exit precision `0.99996`
- After hardening the validation split, the segment artifact was retrained as
  `segment_controller_grouped_v2.joblib`; its exit-stage validation now groups
  by simulated `segment_group`, not by future snapshot.
- The grouped artifact passed model gates:
  - candidate target-selection error `0.0`
  - entry precision `0.9738`
  - exit precision `0.99979`

What failed:

- Calibration replay tuning evaluated `12` conservative first-pass
  configurations and produced `pass=false`.
- Every evaluated configuration improved high-complexity composite cost over
  tuned A3 on calibration, but every configuration failed safety constraints:
  `ping_pong_not_above_tuned=false` and `unnecessary_bounded=false`.
- Best first-pass overall configuration was config `7`
  (`threshold=4`, `candidate_margin_min=20`, `min_segment_duration_s=6`), but
  it still had mean adaptive overall cost `1280.478` and mean adaptive
  ping-pong `57.2`, far above tuned A3 ping-pong (`6-10` per seed).
- Config `10` diagnostics on calibration seed `52` showed:
  - `complexity_aware_ml_a3` segment entries: `0`
  - high-complexity rejected-stay count: `722`
  - adaptive A3 handovers: `550`, almost entirely in sparse/moderate records
  - adaptive ping-pong: `63` versus tuned A3 `9`
  - adaptive unnecessary handovers: `97` versus tuned A3 `33`
- A validated timing replay with the grouped artifact on calibration seed `52`
  (`threshold=4`, `entry_threshold=0.45`, `candidate_margin_min=10`,
  `min_segment_duration_s=10`) still failed the safety direction:
  - tuned A3: `600` handovers, `9` ping-pongs, composite cost `959.08`
  - adaptive segment controller: `541` handovers, `45` ping-pongs, composite
    cost `1163.16`
  - segment entries: `24`
  - high-complexity rejected-stay decisions: `636`
  - A3-gated handovers: `512`
  - post-segment A3 handovers: `86`

Interpretation:

- The segment controller became too conservative about entering ML segments.
- Rejecting high-complexity entry improves high-bucket cost by avoiding bad
  high-complexity handovers, but it leaves sparse/moderate A3 to recover later.
- That delayed A3 recovery creates excessive ping-pong and unnecessary
  handovers, so the adaptive controller still fails the thesis safety gate.
- Because calibration replay tuning failed, held-out replay and live validation
  were correctly blocked.
- The literal full replay-tuning grid now remains available in code, but at
  `3,456` configurations × `5` calibration seeds and roughly `22s` for one
  three-policy replay on this machine, running it naively would be a multi-day
  compute job. That is not final evidence and was not used to bypass the
  calibration gate.

Next engineering direction:

- Tune the entry model/objective so useful segment entries occur when they can
  prevent delayed sparse A3 churn.
- Add an explicit sparse-A3 recovery penalty to calibration tuning, not only to
  labels.
- Consider making high-complexity rejected-stay conditional on serving-cell
  stability; if serving is likely to force sparse A3 recovery soon, ML should
  either enter a segment or the controller should use a conservative A3 action
  with explicit accounting.
- Do not promote this artifact to live ML service.

## Churn-Guard Segment Recovery: `highway_dense_segment_churn_recovery_20260618_201513`

This run implemented the staged A3-churn recovery plan. It remains diagnostic,
not thesis-final evidence.

What changed:

- Added audited post-segment A3 guard controls:
  `segment_post_exit_a3_guard_s` and
  `segment_post_exit_a3_extra_margin_db`.
- Added audited high-complexity reject hold control:
  `segment_high_reject_hold_s`.
- Added decision source `ml_segment_rejected_stay_hold`.
- Extended validation, metrics, decision diagnostics, and threshold summaries
  for guard suppressions, high-reject holds, and sparse/moderate churn after ML
  authority.
- Added churn-aware segment labels from calibration traces only. Future A3
  recovery pressure affects labels and metadata, but future-derived columns are
  excluded from runtime model features.
- Added staged replay tuning so the full `207,360`-configuration grid is not
  run naively. Stage A sampled `48` configurations on seed `52`; Stage B
  replayed the top `20` configurations across calibration seeds `51-55`.

Verification before experiment:

- `py_compile` passed for `scripts/policy_comparison/*.py`.
- `pytest tests/policy_comparison -q` passed with `154` tests.
- Trace-complexity preflight passed for calibration seeds `51-55` and held-out
  seeds `61-65`.
- All calibration and held-out traces shared topology hash
  `5c3561197501a4e9acb66628be58a8bdc3d0db077928217d003b86518cdea5eb`.
- Thresholds `3` and `4` had high-complexity coverage. Threshold `5` remains
  no-coverage for this topology.

Training and calibration:

- Churn-aware dataset export produced `89,117` rows:
  - `18,249` candidate rows
  - `4,750` entry rows
  - `66,118` exit rows
- Segment artifact:
  `segment_model/segment_controller_churn.joblib`.
- Training gates passed:
  - candidate target-selection error `0.0148`
  - entry precision `0.9486`
  - exit precision `0.9995`
- Staged calibration tuning passed and wrote
  `segment_model/segment_controller_churn_tuned.joblib`.
- Selected calibration parameters:
  - complexity threshold `4`
  - entry threshold `0.55`
  - candidate margin minimum `30.0`
  - exit threshold `0.8`
  - consecutive exit votes `4`
  - minimum segment duration `15s`
  - maximum segment duration `60s`
  - post-exit A3 guard `30s`
  - post-exit A3 extra margin `9 dB`
  - high-reject hold `20s`
- Calibration mean high-complexity improvement was `0.9437`, with mean adaptive
  ping-pong `0.0` and mean adaptive handovers `6.0`.

Held-out replay on seeds `61-65` was run only after calibration passed. The
held-out validation was clean, but the strict gate failed:

- Overall pass: `false`.
- Threshold `3` failed because adaptive did not beat ML-only overall:
  - mean adaptive composite cost `25.9671`
  - mean ML-only composite cost `21.3521`
  - mean high-complexity improvement over tuned A3 `0.9330`
  - mean ping-pong `0.0`
- Threshold `4` failed for the same reason:
  - mean adaptive composite cost `25.4701`
  - mean ML-only composite cost `18.3346`
  - mean high-complexity improvement over tuned A3 `0.9402`
  - mean ping-pong `0.0`
- Validation issues: none.

Decision diagnostics show the new failure mode:

- For threshold `4`, worst seed `64`:
  - `ml_policy`: `0` handovers, `0` segment entries, `2,775`
    high-reject holds, composite cost `18.4989`.
  - `complexity_aware_ml_a3`: `11` handovers, all sparse A3 handovers from
    `a3_complexity_gate`, `0` segment entries, `2,697` high-reject holds,
    composite cost `31.1730`.
  - `tuned_a3_baseline`: `600` handovers, including `445` sparse handovers.
- For threshold `3`, worst seed `65`:
  - adaptive made `6` sparse A3 handovers and `0` segment entries.
  - ML-only made `0` handovers.
- The churn guards worked in the narrow sense: ping-pong, post-segment A3
  handovers, post-segment ping-pong, and sparse/moderate churn after ML all
  dropped to `0`.
- But the controller became too conservative to enter ML segments. The adaptive
  policy still delegates a few sparse records to A3, while ML-only simply stays
  everywhere and wins overall.

Interpretation:

- This is progress over the previous failure: the catastrophic A3 churn and
  ping-pong were removed.
- It is still not thesis-final proof because the adaptive controller does not
  beat ML-only segment control overall.
- The current dense highway data suggests a stronger baseline may be
  "conservative stay unless serving quality is actually weak", not A3 by
  default in every sparse record.
- The next modeling question is therefore not more guard tuning. It is whether
  sparse/simple authority should be A3, tuned A3 with a serving-quality gate, or
  a conservative stay/A3 hybrid. That must be evaluated honestly against tuned
  A3 and ML-only.

Live validation and smart-city validation remain blocked.

## Sparse Authority Study: `highway_dense_sparse_authority_20260619_021532`

This study tested the next proposed sparse/simple authority choices instead of
assuming tuned A3 must always control every non-high-complexity snapshot. It is
diagnostic evidence, not thesis-final proof.

Implementation changes:

- Added three explicit segment-controller sparse authority modes:
  - `tuned_a3`: unchanged tuned A3 behavior.
  - `quality_gated_a3`: allow weak-serving recovery or an unusually strong A3
    gain.
  - `stay_unless_weak`: allow A3 only when serving quality is weak and the A3
    gain clears the configured margin.
- Added audited RSRP/SINR floors, A3 margin, allow/suppress result, and reason to
  every segment-controller decision.
- Added validator failures for missing or malformed sparse-authority metadata.
- Added sparse-authority suppression/handover metrics and decision diagnostics.
- Added a dedicated calibration-only sparse-authority tuner. Its gate requires
  adaptive to beat ML-only and tuned A3 on every calibration seed, in addition
  to the existing high-complexity and safety constraints.

Verification passed:

- `py_compile` passed for all policy-comparison modules.
- The full policy-comparison suite passed with `164` tests.

### Composite Cost V1 Studies

The broad staged study enumerated a `130`-configuration grid, sampled `24`
balanced Stage-A configurations on seed `52`, and replayed the best `8` on all
calibration seeds `51-55`. No configuration passed.

Best broad near-miss, config `8`:

- complexity threshold `3`
- mode `quality_gated_a3`
- serving floors `-100 dBm` and `0 dB SINR`
- extra A3 margin `6 dB`
- mean adaptive cost `32.5083`
- mean ML-only cost `25.1738`
- mean high-complexity improvement over tuned A3 `90.62%`
- adaptive beat ML-only only on seeds `53` and `54`

Decision inspection showed why the initial gate was ineffective: sparse A3
handovers occurred at step `1` with very strong serving RSRP (`-8` to `-22
dBm`) but serving SINR between approximately `-12` and `-27 dB`. SINR floors
of `-5` and `0 dB` classified all these records as weak.

A focused strict-SINR study enumerated `192` configurations, sampled `36`, and
replayed the best `8` across seeds `51-55`. It also failed.

Best low-cost focused candidate, config `145`:

- complexity threshold `4`
- mode `stay_unless_weak`
- serving floors `-110 dBm` and `-30 dB SINR`
- extra A3 margin `6 dB`
- mean adaptive cost `16.8160`
- mean ML-only cost `16.2070`
- mean adaptive handovers `0.6`
- mean authority suppressions `4.4`
- mean high-complexity improvement over tuned A3 `94.66%`

On seed `52`, adaptive and ML-only both made zero handovers and had identical
network-quality proxies. Adaptive still cost `15.9437` versus `14.8672`. The
old composite cost accumulated every sub-millisecond latency difference across
all `3,600` snapshots, while it did not score SINR at all. This contradicted the
written metric design, which requires RSRP and SINR quality.

### Composite Cost V2 Audit

The metric was corrected without deleting or relabeling the v1 failures.
Version `v2_rsrp_sinr_latency_budget`:

- penalizes serving SINR below `-5 dB`;
- penalizes handover targets below `-5 dB`;
- applies latency cost only above a `10 ms` budget;
- reports raw average latency separately;
- warms each local segment model symmetrically before measured replay, then
  resets all replay state.

The warm-up smoke replay confirmed that identical adaptive and ML-only network
decisions now have identical cost (`6898.0` each on seed `52`).

The final metric-v2 calibration study enumerated `36` conservative
`stay_unless_weak` configurations and replayed the best `6` across seeds
`51-55`. It still failed.

Best metric-v2 candidate, config `23`:

- complexity threshold `4`
- serving floors `-110 dBm` and `-25 dB SINR`
- extra A3 margin `12 dB`
- mean adaptive cost `6949.8`
- mean ML-only cost `6900.8`
- mean tuned-A3 cost `9195.2`
- mean high-complexity improvement over tuned A3 `12.82%`
- mean adaptive handovers `1.8`
- ping-pong `0`
- validation passed, but adaptive increased low-SINR exposure and poor-SINR
  target selections compared with ML-only.

Conclusion:

- Sparse authority guards removed almost all A3 churn.
- They did not make adaptive control beat ML-only on every calibration seed.
- The remaining rare A3 handovers are not reliably beneficial in SINR terms.
- The segment model still enters zero ML segments in the important near-miss
  cases, so the current `ml_policy` comparator is effectively a learned
  reject-and-stay controller.
- No tuned sparse-authority artifact was promoted.
- Held-out seeds `61-65`, live validation, and smart city were not run.

Next engineering direction:

- Audit the dense-highway RF generator and SINR calculation. Serving RSRP near
  `-10 dBm` together with thousands of snapshots below `-5 dB` SINR needs a
  physical-model/unit sanity check before further thesis claims.
- Add an explicit no-handover/stay baseline so ML-only rejection is not credited
  as ML intelligence.
- Train segment entry and target utility against future SINR and QoS, not only
  conservative rejection and RSRP-oriented A3 recovery.
- Keep held-out and live gates closed until calibration passes under the
  versioned metric.
## 2026-06-19 Physical Validity Audit

The original dense-highway traces are no longer eligible for final evidence.
The investigation found RF fallback, topology contamination, duplicate omni
sectors, impossible movement velocity, missing QoS requirements, stale replay
QoS, and trajectory leakage in validation. The corrected protocol and current
gate are documented in `docs/PHYSICAL_HANDOVER_V3_AUDIT.md`.

The thesis claim remains unproven. Final seeds and live validation remain
blocked until corrected NEF traces, oracle training, and tuning pass.

## Physical V3 Tuning Result

Docker access was restored and the corrected physical pipeline ran through
the preregistered tuning gate. The retained evidence root is
`thesis_results/physical_v3_counterfactual_20260619_231019/`.

Before accepting traces, two additional integration defects were found and
fixed:

- fixed-interval movement advanced less distance than real loop elapsed time;
- runtime-visible-only snapshots could drop a serving cell selected by an
  offline policy, making counterfactual replay invalid.

The final training/tuning traces therefore include explicit movement
provenance and measurements for every topology cell at every step. All `45`
training traces and all `15` tuning traces passed physical validation.

LambdaMART was selected over the linear learned baseline using leave-one-seed-
out validation. The dense replay tuning gate still failed. The best candidate
used margin `0.0` and complexity threshold `3`; its mean high-complexity
improvement over tuned A3 was `3.41%`, below the required `5%`. It did not pass
all five tuning seeds and did not satisfy all overall/safety comparisons.

No `protocol_lock.json` was written. Final seeds `201-210` were not captured
or inspected, and live validation remains blocked. Because the dataset has
`162,000` independent snapshots, the preregistered model ladder now permits a
sequence Model C investigation; that is future model work, not permission to
retune against final seeds.
