"""Canonical trace and decision schemas for fair policy comparison."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Literal, Mapping, Optional


DecisionType = Literal["stay", "handover"]


class TraceSchemaError(ValueError):
    """Raised when trace or decision records are incomplete or unsafe."""


def _require_non_empty(name: str, value: str) -> None:
    if not value:
        raise TraceSchemaError(f"{name} is required")


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise TraceSchemaError(f"{name} must be finite")


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    result = float(value)
    _require_finite("optional float", result)
    return result


@dataclass(frozen=True)
class VisibleCellMeasurement:
    """One visible cell measurement in the canonical trace."""

    cell_id: str
    rsrp_dbm: float
    rsrq_db: Optional[float] = None
    sinr_db: Optional[float] = None
    load: Optional[float] = None

    def __post_init__(self) -> None:
        _require_non_empty("cell_id", self.cell_id)
        _require_finite("rsrp_dbm", self.rsrp_dbm)
        if self.rsrq_db is not None:
            _require_finite("rsrq_db", self.rsrq_db)
        if self.sinr_db is not None:
            _require_finite("sinr_db", self.sinr_db)
        if self.load is not None:
            _require_finite("load", self.load)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VisibleCellMeasurement":
        return cls(
            cell_id=str(data["cell_id"]),
            rsrp_dbm=float(data["rsrp_dbm"]),
            rsrq_db=_optional_float(data.get("rsrq_db")),
            sinr_db=_optional_float(data.get("sinr_db")),
            load=_optional_float(data.get("load")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MeasurementTraceRecord:
    """Policy-free measurement snapshot shared by all comparison policies."""

    scenario: str
    seed: int
    timestamp_s: float
    step_index: int
    ue_id: str
    serving_cell: str
    ue_position: Dict[str, float]
    visible_cells: List[VisibleCellMeasurement]
    speed_mps: Optional[float] = None
    topology_hash: Optional[str] = None
    service_type: Optional[str] = None
    qos_requirements: Optional[Dict[str, float]] = None
    observed_qos: Optional[Dict[str, float]] = None
    source: str = "nef_feature_vector"
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace_schema_version: int = 1
    initial_serving_cell: Optional[str] = None
    topology_cell_ids: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_non_empty("scenario", self.scenario)
        _require_non_empty("ue_id", self.ue_id)
        _require_non_empty("serving_cell", self.serving_cell)
        _require_non_empty("source", self.source)
        if self.seed < 0:
            raise TraceSchemaError("seed must be non-negative")
        if self.step_index < 0:
            raise TraceSchemaError("step_index must be non-negative")
        _require_finite("timestamp_s", self.timestamp_s)
        if self.timestamp_s < 0:
            raise TraceSchemaError("timestamp_s must be non-negative")
        if not self.visible_cells:
            raise TraceSchemaError("visible_cells must not be empty")
        if "latitude" not in self.ue_position or "longitude" not in self.ue_position:
            raise TraceSchemaError("ue_position requires latitude and longitude")
        for key, value in self.ue_position.items():
            _require_finite(f"ue_position.{key}", float(value))
        if self.speed_mps is not None:
            _require_finite("speed_mps", self.speed_mps)
        if self.trace_schema_version < 1:
            raise TraceSchemaError("trace_schema_version must be positive")

        cell_ids = [cell.cell_id for cell in self.visible_cells]
        if len(set(cell_ids)) != len(cell_ids):
            raise TraceSchemaError("visible_cells contains duplicate cell IDs")
        if self.serving_cell not in set(cell_ids):
            raise TraceSchemaError(
                f"serving_cell {self.serving_cell!r} missing from visible_cells"
            )

    @property
    def visible_cell_map(self) -> Dict[str, VisibleCellMeasurement]:
        return {cell.cell_id: cell for cell in self.visible_cells}

    def with_serving_cell(self, serving_cell: str) -> "MeasurementTraceRecord":
        if serving_cell not in self.visible_cell_map:
            raise TraceSchemaError(
                f"policy serving cell {serving_cell!r} is not visible at "
                f"step {self.step_index} for UE {self.ue_id}"
            )
        return replace(self, serving_cell=serving_cell)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MeasurementTraceRecord":
        forbidden_policy_fields = {
            "decision_type",
            "policy_name",
            "policy_parameters",
            "selected_target_cell",
            "confidence",
        }
        present_forbidden = sorted(forbidden_policy_fields.intersection(data))
        if present_forbidden:
            raise TraceSchemaError(
                "measurement trace must not contain policy decision fields: "
                + ", ".join(present_forbidden)
            )

        position = data.get("ue_position")
        if not isinstance(position, Mapping):
            raise TraceSchemaError("ue_position must be a mapping")
        cells = data.get("visible_cells")
        if not isinstance(cells, list):
            raise TraceSchemaError("visible_cells must be a list")

        return cls(
            scenario=str(data["scenario"]),
            seed=int(data["seed"]),
            timestamp_s=float(data["timestamp_s"]),
            step_index=int(data["step_index"]),
            ue_id=str(data["ue_id"]),
            serving_cell=str(data["serving_cell"]),
            ue_position={str(k): float(v) for k, v in position.items()},
            visible_cells=[VisibleCellMeasurement.from_dict(item) for item in cells],
            speed_mps=_optional_float(data.get("speed_mps")),
            topology_hash=(
                None if data.get("topology_hash") is None else str(data["topology_hash"])
            ),
            service_type=(
                None if data.get("service_type") is None else str(data["service_type"])
            ),
            qos_requirements=_optional_float_mapping(data.get("qos_requirements")),
            observed_qos=_optional_float_mapping(data.get("observed_qos")),
            source=str(data.get("source", "nef_feature_vector")),
            metadata=dict(data.get("metadata") or {}),
            trace_schema_version=int(data.get("trace_schema_version", 1)),
            initial_serving_cell=(
                None
                if data.get("initial_serving_cell") is None
                else str(data.get("initial_serving_cell"))
            ),
            topology_cell_ids=[str(item) for item in data.get("topology_cell_ids") or []],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario,
            "seed": self.seed,
            "timestamp_s": self.timestamp_s,
            "step_index": self.step_index,
            "ue_id": self.ue_id,
            "serving_cell": self.serving_cell,
            "ue_position": dict(self.ue_position),
            "speed_mps": self.speed_mps,
            "visible_cells": [cell.to_dict() for cell in self.visible_cells],
            "topology_hash": self.topology_hash,
            "service_type": self.service_type,
            "qos_requirements": self.qos_requirements,
            "observed_qos": self.observed_qos,
            "source": self.source,
            "metadata": self.metadata,
            "trace_schema_version": self.trace_schema_version,
            "initial_serving_cell": self.initial_serving_cell,
            "topology_cell_ids": list(self.topology_cell_ids),
        }


@dataclass(frozen=True)
class PolicyDecisionRecord:
    """Canonical decision output shared by ML, fixed A3, and tuned A3."""

    ue_id: str
    timestamp_s: float
    step_index: int
    current_serving_cell: str
    selected_target_cell: Optional[str]
    decision_type: DecisionType
    policy_name: str
    policy_parameters: Dict[str, Any]
    serving_measurement_value: float
    neighbour_measurements_considered: Dict[str, float]
    trigger_condition_result: bool
    time_to_trigger_state: Dict[str, Any]
    cooldown_state: Dict[str, Any]
    reason: str
    debug: Dict[str, Any] = field(default_factory=dict)
    decision_latency_ms: Optional[float] = None
    confidence: Optional[float] = None

    def __post_init__(self) -> None:
        _require_non_empty("ue_id", self.ue_id)
        _require_non_empty("current_serving_cell", self.current_serving_cell)
        _require_non_empty("policy_name", self.policy_name)
        _require_non_empty("reason", self.reason)
        _require_finite("timestamp_s", self.timestamp_s)
        if self.step_index < 0:
            raise TraceSchemaError("step_index must be non-negative")
        if self.decision_type == "handover" and not self.selected_target_cell:
            raise TraceSchemaError("handover decisions require selected_target_cell")
        if self.decision_type == "stay" and self.selected_target_cell is not None:
            raise TraceSchemaError("stay decisions must not include selected_target_cell")
        _require_finite("serving_measurement_value", self.serving_measurement_value)
        if self.decision_latency_ms is not None:
            _require_finite("decision_latency_ms", self.decision_latency_ms)
            if self.decision_latency_ms < 0:
                raise TraceSchemaError("decision_latency_ms must be non-negative")
        if self.confidence is not None:
            _require_finite("confidence", self.confidence)
            if not 0.0 <= self.confidence <= 1.0:
                raise TraceSchemaError("confidence must be in [0, 1]")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyDecisionRecord":
        return cls(
            ue_id=str(data["ue_id"]),
            timestamp_s=float(data["timestamp_s"]),
            step_index=int(data["step_index"]),
            current_serving_cell=str(data["current_serving_cell"]),
            selected_target_cell=(
                None
                if data.get("selected_target_cell") is None
                else str(data["selected_target_cell"])
            ),
            decision_type=data["decision_type"],
            policy_name=str(data["policy_name"]),
            policy_parameters=dict(data.get("policy_parameters") or {}),
            serving_measurement_value=float(data["serving_measurement_value"]),
            neighbour_measurements_considered={
                str(k): float(v)
                for k, v in (
                    data.get("neighbour_measurements_considered")
                    or data.get("neighbor_measurements_considered")
                    or {}
                ).items()
            },
            trigger_condition_result=bool(data["trigger_condition_result"]),
            time_to_trigger_state=dict(data.get("time_to_trigger_state") or {}),
            cooldown_state=dict(data.get("cooldown_state") or {}),
            reason=str(data["reason"]),
            debug=dict(data.get("debug") or {}),
            decision_latency_ms=_optional_float(data.get("decision_latency_ms")),
            confidence=_optional_float(data.get("confidence")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _optional_float_mapping(value: Any) -> Optional[Dict[str, float]]:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TraceSchemaError("expected mapping of float values")
    return {str(k): float(v) for k, v in value.items() if v is not None}
