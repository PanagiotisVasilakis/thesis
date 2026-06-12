"""Conversion from the existing NEF feature-vector path to canonical traces."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import requests  # type: ignore[import-untyped]

from .schemas import MeasurementTraceRecord, TraceSchemaError, VisibleCellMeasurement

ML_TRACE_PASSTHROUGH_FIELDS = (
    "direction",
    "velocity",
    "acceleration",
    "cell_load",
    "handover_count",
    "handover_history",
    "time_since_handover",
    "signal_trend",
    "environment",
    "rsrp_stddev",
    "sinr_stddev",
    "stability",
    "heading_change_rate",
    "path_curvature",
    "rsrp_acceleration",
    "sinr_acceleration",
    "speed_jerk",
    "rsrp_ema_short",
    "rsrp_ema_long",
    "rsrp_trend_divergence",
    "distance_to_target",
    "distance_to_current",
    "cell_distances_m",
    "distance_to_cells",
    "angle_to_target",
    "relative_distance_ratio",
    "moving_toward_target",
    "moving_toward_cells",
    "movement_alignment_by_cell",
    "approach_by_cell",
    "service_priority",
    "latency_requirement_ms",
    "throughput_requirement_mbps",
    "reliability_pct",
    "jitter_ms",
)
from .trace_io import topology_hash_from_path


class NefTraceError(RuntimeError):
    """Raised when trace sampling from the existing NEF path fails."""


FeatureFetcher = Callable[[str, str, float], Mapping[str, Any]]


def fetch_nef_feature_vector(
    nef_url: str,
    ue_id: str,
    *,
    timeout_s: float = 5.0,
) -> Dict[str, Any]:
    """Fetch one feature vector from the existing NEF endpoint.

    Uses the repo's current endpoint: GET /api/v1/ml/state/{ue_id}. This
    function does not start or own a NEF emulator instance.
    """
    if not nef_url:
        raise NefTraceError("nef_url is required")
    if not ue_id:
        raise NefTraceError("ue_id is required")

    url = f"{nef_url.rstrip('/')}/api/v1/ml/state/{ue_id}"
    response = requests.get(url, timeout=timeout_s)
    if response.status_code == 404:
        raise NefTraceError(f"UE {ue_id!r} was not found by the existing NEF path")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise NefTraceError("NEF feature-vector response must be a JSON object")
    return data


def capture_nef_trace_records(
    *,
    nef_url: str,
    ue_ids: Sequence[str],
    scenario: str,
    seed: int,
    samples: int,
    interval_s: float,
    timeout_s: float = 5.0,
    topology_hash: Optional[str] = None,
    topology_json: Optional[Path] = None,
    fetcher: Optional[FeatureFetcher] = None,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> List[MeasurementTraceRecord]:
    """Sample canonical trace records from the existing NEF feature endpoint.

    This function only reads existing NEF feature vectors. It does not start
    Docker, create scenarios, move UEs, call ML, or apply handovers.
    """
    if not nef_url:
        raise NefTraceError("nef_url is required")
    clean_ue_ids = [ue_id.strip() for ue_id in ue_ids if ue_id.strip()]
    if not clean_ue_ids:
        raise NefTraceError("at least one UE ID is required")
    if samples <= 0:
        raise NefTraceError("samples must be positive")
    if interval_s < 0:
        raise NefTraceError("interval_s must be non-negative")
    if topology_hash and topology_json:
        raise NefTraceError("provide topology_hash or topology_json, not both")

    resolved_topology_hash = (
        topology_hash
        if topology_hash is not None
        else topology_hash_from_path(topology_json)
        if topology_json is not None
        else None
    )
    selected_fetcher = fetcher or _default_fetcher
    start = monotonic_clock()
    records: List[MeasurementTraceRecord] = []

    for step_index in range(samples):
        timestamp_s = monotonic_clock() - start
        for ue_id in clean_ue_ids:
            feature_vector = selected_fetcher(nef_url, ue_id, timeout_s)
            records.append(
                feature_vector_to_trace_record(
                    feature_vector,
                    scenario=scenario,
                    seed=seed,
                    step_index=step_index,
                    timestamp_s=timestamp_s,
                    topology_hash=resolved_topology_hash,
                    source="nef_live_capture",
                )
            )
        if step_index < samples - 1 and interval_s > 0:
            sleeper(interval_s)

    return records


def _default_fetcher(
    nef_url: str,
    ue_id: str,
    timeout_s: float,
) -> Mapping[str, Any]:
    return fetch_nef_feature_vector(nef_url, ue_id, timeout_s=timeout_s)


def feature_vector_to_trace_record(
    feature_vector: Mapping[str, Any],
    *,
    scenario: str,
    seed: int,
    step_index: int,
    timestamp_s: Optional[float] = None,
    topology_hash: Optional[str] = None,
    source: str = "nef_feature_vector",
) -> MeasurementTraceRecord:
    """Convert the existing NEF feature vector into a policy-free trace row."""
    ue_id = str(_required(feature_vector, "ue_id"))
    serving_cell = str(_required(feature_vector, "connected_to"))
    rsrp_map = _required_mapping(feature_vector, "neighbor_rsrp_dbm")
    if serving_cell not in {str(key) for key in rsrp_map}:
        raise TraceSchemaError(
            f"serving cell {serving_cell!r} missing from neighbor_rsrp_dbm"
        )

    latitude = float(_required(feature_vector, "latitude"))
    longitude = float(_required(feature_vector, "longitude"))
    altitude = _optional_float(feature_vector.get("altitude"))
    speed_mps = _optional_float(feature_vector.get("speed"))
    timestamp_value = float(timestamp_s if timestamp_s is not None else time.time())

    rsrq_map = _optional_mapping(feature_vector.get("neighbor_rsrqs"))
    sinr_map = _optional_mapping(feature_vector.get("neighbor_sinrs"))
    load_map = _optional_mapping(feature_vector.get("neighbor_cell_loads"))

    visible_cells = []
    for cell_id, rsrp in rsrp_map.items():
        visible_cells.append(
            VisibleCellMeasurement(
                cell_id=str(cell_id),
                rsrp_dbm=float(rsrp),
                rsrq_db=_optional_float(_lookup(rsrq_map, cell_id)),
                sinr_db=_optional_float(_lookup(sinr_map, cell_id)),
                load=_optional_float(_lookup(load_map, cell_id)),
            )
        )

    observed_qos = feature_vector.get("observed_qos")
    latest_qos = None
    if isinstance(observed_qos, Mapping) and isinstance(observed_qos.get("latest"), Mapping):
        latest_qos = {
            str(key): float(value)
            for key, value in observed_qos["latest"].items()
            if value is not None
        }

    position = {"latitude": latitude, "longitude": longitude}
    if altitude is not None:
        position["altitude"] = altitude

    return MeasurementTraceRecord(
        scenario=scenario,
        seed=seed,
        timestamp_s=timestamp_value,
        step_index=step_index,
        ue_id=ue_id,
        serving_cell=serving_cell,
        ue_position=position,
        speed_mps=speed_mps,
        visible_cells=visible_cells,
        topology_hash=topology_hash,
        service_type=(
            None
            if feature_vector.get("service_type") is None
            else str(feature_vector.get("service_type"))
        ),
        qos_requirements=_float_mapping_or_none(feature_vector.get("qos_requirements")),
        observed_qos=latest_qos,
        source=source,
        metadata={
            "feature_vector_keys": sorted(str(key) for key in feature_vector.keys()),
            "ml_features": {
                key: feature_vector[key]
                for key in ML_TRACE_PASSTHROUGH_FIELDS
                if feature_vector.get(key) is not None
            },
        },
    )


def _required(mapping: Mapping[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise TraceSchemaError(f"feature vector missing required field {key}")
    return value


def _required_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[Any, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping) or not value:
        raise TraceSchemaError(f"feature vector missing required mapping {key}")
    return value


def _optional_mapping(value: Any) -> Mapping[Any, Any]:
    return value if isinstance(value, Mapping) else {}


def _lookup(mapping: Mapping[Any, Any], key: Any) -> Any:
    if key in mapping:
        return mapping[key]
    return mapping.get(str(key))


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_mapping_or_none(value: Any) -> Optional[Dict[str, float]]:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TraceSchemaError("expected qos_requirements to be a mapping")
    return {str(key): float(raw) for key, raw in value.items() if raw is not None}
