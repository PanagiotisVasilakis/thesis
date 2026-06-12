# Standards-Inspired Non-ML Handover Baselines

This package contains pure Python decision policies for traditional non-ML
handover baselines. It lives under
`5g-network-optimization/services/handover-baseline-service/` as the
service-level sibling of the existing NEF emulator and ML service. The current
implementation is an importable Python policy package, not a new network daemon.

## Architecture

The comparison architecture is:

```text
Shared existing NEF/emulator/client/config
        |
        | same topology, mobility, measurements, metrics
        |
------------------------------------------------
|                                              |
services/ml-service/                           services/handover-baseline-service/
Existing ML decision system                    Fixed A3 + tuned A3 non-ML policies
|                                              |
------------------------------------------------
        |
Same future comparison output schema
```

There must be only one NEF/exposure layer. Creating a second NEF for the A3
baseline would weaken the comparison because policy effects would be mixed with
different API paths, state stores, timing behavior, and measurement generation.
This package therefore does not start Docker, does not start Prometheus, and
does not own a NEF client. `adapter.py` only converts the existing NEF
`NetworkStateManager.get_feature_vector()` shape into typed policy inputs.

The three service-level concerns are:

- `5g-network-optimization/services/nef-emulator/`: shared NEF/exposure and
  emulation layer.
- `5g-network-optimization/services/ml-service/`: existing ML-assisted
  decision implementation.
- `5g-network-optimization/services/handover-baseline-service/`: this
  standards-inspired non-ML handover baseline implementation.

The existing ML implementation remains separate. This package does not import
or call ML predictions, confidence scores, labels, or model outputs.

## Live NEF Integration

The existing NEF emulator may import this package for explicit live comparison
modes:

- `fixed_a3_baseline`
- `tuned_a3_baseline`

This is still one shared NEF. The NEF process imports the baseline package via
`HANDOVER_BASELINE_SERVICE_PATH` and adapts its existing
`NetworkStateManager.get_feature_vector()` output into `MeasurementSnapshot`.
The baseline package does not expose a separate API, does not own a network
state store, and does not duplicate the NEF emulator.

For Docker Compose runs, the package is mounted read-only at
`/opt/handover-baseline-service`. Tuned live mode requires
`TUNED_A3_CONFIG_PATH` to point to a real saved tuning JSON containing
`selected_parameters`; the runtime fails clearly if that file is absent or
invalid. No tuned parameters are invented at runtime.

## Policies

`FixedA3Policy` is a deterministic operator-style rule baseline. It uses RSRP
Event A3-inspired logic:

```text
neighbour_rsrp_dbm + a3_offset_db > serving_rsrp_dbm + hysteresis_db
```

It also tracks per-UE/per-target time-to-trigger state and applies a cooldown
guard after handovers to reduce immediate ping-pong behavior.

The fixed configuration is:

- `a3_offset_db = 0.0`
- `hysteresis_db = 3.0`
- `time_to_trigger_s = 1.0`
- `cooldown_s = 2.0`

`A3TraceTuner` is a controlled non-ML grid search over A3 offset, hysteresis,
time-to-trigger, and cooldown. It evaluates deterministic measurement traces
using only non-ML metrics:

```text
10*low_quality_steps + 5*ping_pong_count + handover_count
```

It preserves every tested configuration and score in the tuning result. It does
not consume ML outputs or labels.

## Inputs And Outputs

Policy input is `MeasurementSnapshot`, which includes:

- UE ID
- timestamp or step index
- serving-cell RSRP
- neighbour-cell RSRP values
- optional RSRQ/SINR/load if the existing NEF feature vector already provides them

Policy output is `PolicyDecision`, a shared schema with:

- UE ID and timestamp
- current serving cell
- selected target cell, or `None`
- `stay` or `handover`
- policy name and parameters
- serving/neighbour measurements considered
- trigger, time-to-trigger, cooldown, reason, and debug fields

There is no fake A3 confidence value. The `confidence` field remains `None`.

## Limitations

This is a standards-inspired A3 baseline, not a full real operator
implementation and not real-world field validation. Current scenario data is
synthetic/emulated, RF behavior is simplified by the repository’s simulator,
and Prometheus metrics are emitted by the local stack.

The recommended primary scenario remains `highway`, which is useful for
handover-focused thesis evidence but only medium realism. `smart_city` is
secondary/partial. The legacy simple runner and synthetic generator are smoke
or fixture tools, not thesis-valid evidence by themselves.

## Tests

Run the focused tests with:

```bash
.venv/bin/python -m pytest 5g-network-optimization/services/handover-baseline-service/tests -q
```

## Comparison Foundation

The first comparison orchestration layer now lives in `scripts/policy_comparison/`.
It converts the existing NEF feature-vector shape from `/api/v1/ml/state/{ue_id}`
into a policy-free canonical measurement trace, then replays identical snapshots
through interchangeable policy adapters.

The A3 adapters in that package import this baseline service and delegate
decision-making here. They do not contain a second A3 implementation. The ML
adapter calls the existing ML service and raises on ML failures instead of
silently falling back to A3.

Future live comparison work should keep topology, UE mobility, random seed,
duration, snapshots, and metrics identical across policies. Only the decision
policy should differ.
