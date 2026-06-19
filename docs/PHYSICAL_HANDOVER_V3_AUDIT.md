# Physical Handover V3 Audit

## Evidence Status

The thesis claim remains unproven. All traces and policy results produced from
the original `highway_dense` scenario are diagnostic only and must not be used
as final thesis evidence.

Affected roots include the original dense ranker, segment recovery, churn
recovery, and sparse-authority experiments. They are retained to document the
engineering investigation and negative results, not to support an ML win.

## Confirmed Defects In Previous Evidence

- The scenario declared 24 cells, while traces contained 28 because the four
  default NEF cells remained in the database.
- The intended RF package was outside the Docker build context. The runtime
  silently used an emergency formula with GHz/km units, reducing path loss by
  approximately 60 dB.
- Four co-located sectors were modeled as identical omnidirectional antennas
  and full-power interferers. Azimuth, tilt, gain, configured power, height,
  bandwidth, band, and reuse group were discarded by the API/runtime path.
- The movement loop advanced ten path indices per second while reporting
  `10 m/s`. Derived speed was typically around `740 m/s`, with endpoint
  wraparound spikes above `14,000 m/s`.
- UE service type and QoS requirements were not persisted. QoS was generated
  from RSRP only, then reused by offline policies after their serving cells had
  diverged.
- A3 calibration used an RSRP-only objective. Segment labels weighted SINR by
  only `0.2`, and adjacent snapshots from the same trajectories crossed the
  train/validation split.
- ML-only frequently won by rejecting every handover. There was no explicit
  no-handover baseline to expose that behavior.

## Implemented V3 Corrections

- The container packages the real RF modules and thesis mode fails closed if
  fallback RF is active.
- Cell schemas persist physical RF parameters. The runtime uses directional
  3GPP TR 38.901 Rural Macro path loss, reference-element RSRP, bandwidth/noise
  figure, co-channel interference, reuse groups, and deterministic spatial
  shadowing.
- Thesis capture starts with an empty topology and verifies canonical runtime
  cell IDs exactly match the saved scenario.
- Mobility uses numeric speed and distance-over-time interpolation with
  endpoint reversal rather than teleportation. Trace records include explicit
  path distance, path length, direction, elapsed time, and endpoint-reversal
  provenance so velocity checks do not infer endpoint behavior.
- QoS requirements are persisted. Live and replay QoS use the same versioned,
  deterministic SINR/CQI proxy. Replay evolves separate attachment and load
  state for every policy.
- Trace schema v3 records RF/QoS/movement provenance and all topology-cell
  measurements needed for counterfactual policy replay. It is rejected on
  fallback, incomplete cell measurements, topology mismatch, missing QoS,
  duplicate sectors, impossible speed, or implausible RF distributions.
- Physical density profiles contain 8, 16, and 24 dual-sector cells on the
  same 10 km corridor. Site reuse-3 creates legitimate inter-frequency
  candidates while interference remains co-channel.
- Baselines now include explicit no-handover and conditional handover.
- Metric v3 uses policy-independent environment buckets and per-UE-minute
  physical/QoS costs. Tuned A3 uses the same objective.
- Oracle labels use a 20-step cost-to-go dynamic program with an explicit stay
  action. Model selection compares linear utility and LambdaMART using
  leave-one-seed-out complete trajectories.
- Final seeds `201-210` are blocked until tuning writes a frozen protocol lock.

## Diagnostic RF Preflight

Result: `thesis_results/physical_rf_preflight_20260619_120927/preflight.json`.

| Profile | Cells | High-complexity coverage | Median RSRP | Median all-cell SINR |
|---|---:|---:|---:|---:|
| Sparse | 8 | 0.0% | -91.54 dBm | -1.01 dB |
| Moderate | 16 | 20.0% | -91.68 dBm | -8.67 dB |
| Dense | 24 | 37.22% | -91.42 dBm | -18.58 dB |

This preflight directly evaluates the packaged RF model but does not exercise
the NEF container, movement threads, database, or trace endpoint. It is marked
`evidence_eligible=false` and is not a thesis result.

## Current Gate

- Compilation: passed.
- Docker daemon and Compose access: passed in the full-access environment.
- Corrected NEF image build and strict trace capture: passed.
- Evidence root:
  `thesis_results/physical_v3_counterfactual_20260619_231019/`.
- Training traces: `45/45` passed physical validation across seeds `101-115`
  and all three densities (`162,000` snapshots). Every trace has movement
  provenance, complete topology-cell measurements, and a stable per-scenario
  topology hash.
- Tuned A3: the full `108`-configuration grid completed separately for each
  density using training seeds only.
- Oracle dataset: `554,986` action rows over `162,000` snapshot groups with
  explicit stay actions and no raw UE/cell ID model features.
- Leave-one-seed-out model selection: LambdaMART beat linear utility on mean
  oracle regret (`0.1924` versus `0.2695`) and top-action accuracy (`0.9690`
  versus `0.9591`).
- Tuning traces: `15/15` passed physical validation across seeds `116-120`
  and all three densities.
- Dense tuning replay: failed. No margin/complexity-threshold configuration
  passed every tuning seed and the preregistered safety/overall constraints.
  The best mean high-complexity improvement was `3.41%`, below the required
  `5%`, and several seeds regressed in overall adaptive cost.
- Protocol lock: not written. Final seeds `201-210`, runtime integration, live
  validation, and smart-city generalization remain correctly blocked.

The corrected physical pipeline now runs end to end through tuning, but no
final claim can be made because the tuning gate failed. The result is a real
negative model result, not a Docker, RF fallback, stale-output, or validation
failure.
