# NEF Emulator Mobility & Handover Reference

## Scope
This document summarizes the mobility-model catalogue, handover decision stack, and key configuration levers implemented under `services/nef-emulator/backend/app/app`. It also calls out module relationships and areas that merit refactoring (unused or duplicated logic).

## Mobility Model Catalogue
The `mobility_models.models` module defines a common `MobilityModel` base with deterministic seeding and interpolation helpers that all concrete paths inherit.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L1-L58】 The table below captures each model and notable parameters/behaviour.

| Model | Description & Movement Rules | Key Inputs | Outputs/Side Effects |
| --- | --- | --- | --- |
| `LinearMobilityModel` | Straight-line motion between two 3D points with constant speed; timestamps advance by `time_step`.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L60-L113】 | `start_position`, `end_position`, `speed`, optional `seed/start_time`. | Populates `trajectory` with directional vectors and speed metadata. |
| `LShapedMobilityModel` | Two sequential linear segments with a 90° corner; reuses `LinearMobilityModel` internally and stitches trajectories.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L114-L174】 | `start_position`, `corner_position`, `end_position`, `speed`. | Produces combined trajectory; second leg reuses first leg's terminal timestamp. |
| `RandomWaypointModel` | Random waypoint selection within bounding box, random speed in `[v_min, v_max]`, and configurable pause at each waypoint.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L176-L236】 | `area_bounds`, `v_min`, `v_max`, `pause_time`. | Appends motion and pause samples; suitable as a group centre driver. |
| `ManhattanGridMobilityModel` | Axis-aligned “city block” movement with probabilistic turn selection at intersections.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L248-L305】 | `grid_size` `(x_count, y_count, block_length)`, `speed`. | Generates block-by-block segments; updates heading randomly per TR 38.901. |
| `ReferencePointGroupMobilityModel` | Wraps a “group centre” model, adding random radial offsets up to `d_max` for each sample.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L307-L343】 | `group_center_model`, `d_max`. | Mirrors centre timestamps/velocity, injecting offset UE positions. |
| `RandomDirectionalMobilityModel` | Maintains a heading until an exponentially distributed change time elapses; reflects off boundaries when leaving `area_bounds`.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L345-L462】 | `start_position`, `speed`, optional `area_bounds`, `direction_change_mean`. | Records direction vector in each sample; clamps positions to domain. |
| `UrbanGridMobilityModel` | Grid-constrained walker with probabilistic turns and grid snapping of the start point.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L465-L581】 | `start_position`, `speed`, optional `grid_size`, `turn_probability`. | Maintains current heading state; emits per-step metadata similar to linear model. |

### Integration Surfaces
* `tools/mobility/adapter.MobilityPatternAdapter` exposes factory and serialization helpers for NEF consumption. It directly instantiates the models above (except `RandomWaypointModel`/`ManhattanGridMobilityModel`) and emits NEF-friendly points.【F:5g-network-optimization/services/nef-emulator/backend/app/app/tools/mobility/adapter.py†L1-L189】
* `mobility_models/nef_adapter.py` is a second, narrower adapter that only supports linear and L-shaped paths, returns basic latitude/longitude points, and carries an unused `NetworkStateManager` import.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/nef_adapter.py†L1-L27】 This duplication suggests consolidation opportunities (see § 5).

## Handover Decision Stack
Handover orchestration lives under `handover/` and the network state keeper under `network/`.

### Core Components
* `NetworkStateManager` tracks UE positions, antenna catalogue, and handover history. It computes ML feature vectors—including ordered neighbor RSRP/SINR/RSRQ, inferred loads—and exposes interpolation helpers. Environment variables can override A3 thresholds, resource blocks, and noise floor at runtime.【F:5g-network-optimization/services/nef-emulator/backend/app/app/network/state_manager.py†L1-L197】
* `A3EventRule` implements 3GPP A3 logic with hysteresis, optional RSRQ thresholds, and a time-to-trigger latch. It supports `rsrp_based`, `rsrq_based`, and `mixed` evaluation modes.【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/a3_rule.py†L1-L117】
* `HandoverEngine` chooses between ML-driven handovers and the A3 rule depending on configuration. It:
  * Loads ML location from settings/env and toggles between remote service, local model, or rule-based fallback.【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L17-L160】
  * Wraps ML responses with QoS compliance checks; insufficient confidence or QoS violations trigger the deterministic A3 fallback and metrics updates.【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L191-L238】
  * Delegates the final state transition to `NetworkStateManager.apply_handover_decision` so history and logging stay centralized.【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L191-L238】【F:5g-network-optimization/services/nef-emulator/backend/app/app/network/state_manager.py†L138-L160】

### Data Flow
1. Mobility models (or telemetry ingestion) write UE trajectories into `NetworkStateManager.ue_states`.
2. `HandoverEngine.decide_and_apply` fetches the live feature vector, optionally queries the ML service, and evaluates QoS/thresholds.
3. If ML is disabled or unsuitable, the embedded `A3EventRule` scans neighbor metrics generated by `NetworkStateManager` to propose a target cell.
4. Approved decisions are applied via `NetworkStateManager`, updating connection state and history logs.

## Configuration Knobs
Runtime behaviour is controlled by both Pydantic settings and ad-hoc environment variables.

### Settings (`core.config.Settings`)
Key `.env` fields include server metadata, database DSNs (Postgres and Mongo), CAPIF endpoints, SMTP credentials, and the default ML service URL.【F:5g-network-optimization/services/nef-emulator/backend/app/app/core/config.py†L15-L123】 Email enablement auto-derives from SMTP presence, and DSNs can be assembled from individual components.

### Environment Overrides
* `NetworkStateManager`: `A3_HYSTERESIS_DB`, `A3_TTT_S`, `RESOURCE_BLOCKS`, `NOISE_FLOOR_DBM` tweak link metrics and A3 criteria.【F:5g-network-optimization/services/nef-emulator/backend/app/app/network/state_manager.py†L13-L70】
* `HandoverEngine`: `ML_SERVICE_URL`, `ML_CONFIDENCE_THRESHOLD`, `ML_LOCAL`, `ML_HANDOVER_ENABLED` govern ML usage, while constructor args expose the same toggles for programmatic control.【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L21-L160】

## Module Relationships
* Mobility adapters depend on `mobility_models.models` and (indirectly) feed UE trajectories into `NetworkStateManager` for handover decisions.
* `HandoverEngine` depends on `NetworkStateManager` both for telemetry (`get_feature_vector`) and for applying decisions, while embedding `A3EventRule` for deterministic fallbacks.【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L94-L238】
* Metrics instrumentation (`..monitoring.metrics`) records ML vs. rule fallbacks, enabling observability coupling with the monitoring stack.【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L200-L232】

## Gaps & Cleanup Opportunities
1. **Unused Mobility Implementations** – Neither `RandomWaypointModel` nor `ManhattanGridMobilityModel` are referenced outside their definitions (aside from documentation comments), meaning they are currently dead code unless instantiated elsewhere at runtime.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L176-L305】
2. **Adapter/API Drift** – `MobilityPatternAdapter`’s `group` branch expects `reference_model`/`relative_position`, but `ReferencePointGroupMobilityModel` still requires `group_center_model`/`d_max`. The mismatch will raise `TypeError` at runtime and signals stale API evolution.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L307-L339】【F:5g-network-optimization/services/nef-emulator/backend/app/app/tools/mobility/adapter.py†L107-L117】
3. **Duplicated NEF Serialization Paths** – `mobility_models/nef_adapter.py` overlaps with the richer `tools/mobility/adapter` but is limited to two models, omits altitude/timestamps, and imports `NetworkStateManager` without using it.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/nef_adapter.py†L1-L27】 Consolidating on a single adapter would reduce drift.
4. **Repeated Interpolation Logic** – `MobilityModel._interpolate_position` and `NetworkStateManager.get_position_at_time` duplicate trajectory interpolation, differing only in error handling.【F:5g-network-optimization/services/nef-emulator/backend/app/app/mobility_models/models.py†L25-L57】【F:5g-network-optimization/services/nef-emulator/backend/app/app/network/state_manager.py†L162-L197】 Extracting a shared utility would eliminate divergence risk.
5. **Minor Hygiene Items** – `handover.engine` imports `RequestException` but does not use it, and metrics updates are wrapped in broad `except Exception` blocks that could be narrowed when the registry is stable.【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L3-L158】【F:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py†L200-L232】

---
This reference should accelerate onboarding for future work on UE mobility simulation, ML handover integration, or control-plane tuning within the NEF emulator service.
