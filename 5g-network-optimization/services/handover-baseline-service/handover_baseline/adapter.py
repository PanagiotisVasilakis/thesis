"""Adapters from existing NEF/scenario structures to baseline policy inputs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .models import CellMeasurement, MeasurementSnapshot


class BaselineAdapterError(ValueError):
    """Raised when existing NEF data cannot be converted safely."""


@dataclass(frozen=True)
class ExistingNEFReference:
    """Document the shared NEF configuration consumed by future runners.

    This object does not start, own, or call a NEF instance. It only resolves
    the same environment-variable names already used by experiment scripts.
    """

    nef_url: Optional[str]
    nef_username_env: str = "NEF_USERNAME"
    nef_password_env: str = "NEF_PASSWORD"
    fallback_username_env: str = "FIRST_SUPERUSER"
    fallback_password_env: str = "FIRST_SUPERUSER_PASSWORD"


def existing_nef_reference(env: Optional[Mapping[str, str]] = None) -> ExistingNEFReference:
    """Return the existing NEF URL reference without creating a NEF client."""
    env_map = env or os.environ
    nef_url = env_map.get("NEF_URL")
    if not nef_url:
        scheme = env_map.get("NEF_SCHEME")
        host = env_map.get("NEF_HOST")
        port = env_map.get("NEF_PORT")
        if scheme and host and port:
            nef_url = f"{scheme}://{host}:{port}"
    return ExistingNEFReference(nef_url=nef_url)


def snapshot_from_feature_vector(
    feature_vector: Mapping[str, Any],
    *,
    ue_id: Optional[str] = None,
    timestamp_s: Optional[float] = None,
    step_index: Optional[int] = None,
) -> MeasurementSnapshot:
    """Convert the NEF ``NetworkStateManager.get_feature_vector`` shape.

    Required fields match the existing NEF exposure path:
    ``connected_to`` and ``neighbor_rsrp_dbm``. Optional ``neighbor_rsrqs``,
    ``neighbor_sinrs`` and ``neighbor_cell_loads`` are preserved when present.
    """
    resolved_ue_id = ue_id or feature_vector.get("ue_id")
    if not resolved_ue_id:
        raise BaselineAdapterError("feature vector missing ue_id")

    connected_to = feature_vector.get("connected_to")
    if not connected_to:
        raise BaselineAdapterError("feature vector missing connected_to")

    rsrp_map = feature_vector.get("neighbor_rsrp_dbm")
    if not isinstance(rsrp_map, Mapping):
        raise BaselineAdapterError("feature vector missing neighbor_rsrp_dbm mapping")
    if connected_to not in rsrp_map:
        raise BaselineAdapterError(
            f"serving cell {connected_to!r} missing from neighbor_rsrp_dbm"
        )

    rsrq_map = _optional_mapping(feature_vector.get("neighbor_rsrqs"))
    sinr_map = _optional_mapping(feature_vector.get("neighbor_sinrs"))
    load_map = _optional_mapping(feature_vector.get("neighbor_cell_loads"))
    resolved_timestamp = (
        float(timestamp_s)
        if timestamp_s is not None
        else float(feature_vector.get("timestamp_s", feature_vector.get("timestamp", 0.0)))
    )

    def build_measurement(cell_key: Any) -> CellMeasurement:
        return CellMeasurement(
            cell_id=str(cell_key),
            rsrp_dbm=float(rsrp_map[cell_key]),
            rsrq_db=_optional_float(_mapped_value(rsrq_map, cell_key)),
            sinr_db=_optional_float(_mapped_value(sinr_map, cell_key)),
            load=_optional_float(_mapped_value(load_map, cell_key)),
        )

    serving = build_measurement(connected_to)
    neighbours = [
        build_measurement(cell_id)
        for cell_id in rsrp_map
        if str(cell_id) != str(connected_to)
    ]

    return MeasurementSnapshot(
        ue_id=str(resolved_ue_id),
        timestamp_s=resolved_timestamp,
        step_index=step_index,
        serving_cell=serving,
        neighbour_cells=neighbours,
        source="nef_feature_vector",
    )


def _optional_mapping(value: Any) -> Mapping[Any, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _mapped_value(mapping: Mapping[Any, Any], key: Any) -> Any:
    if key in mapping:
        return mapping[key]
    return mapping.get(str(key))


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)
