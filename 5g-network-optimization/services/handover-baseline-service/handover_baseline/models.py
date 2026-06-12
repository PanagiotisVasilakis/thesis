"""Typed models for standards-inspired non-ML handover baselines."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional


DecisionType = Literal["stay", "handover"]


def _validate_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True)
class CellMeasurement:
    """Radio measurement for one serving or neighbour cell."""

    cell_id: str
    rsrp_dbm: float
    rsrq_db: Optional[float] = None
    sinr_db: Optional[float] = None
    load: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.cell_id:
            raise ValueError("cell_id is required")
        _validate_finite("rsrp_dbm", self.rsrp_dbm)
        if self.rsrq_db is not None:
            _validate_finite("rsrq_db", self.rsrq_db)
        if self.sinr_db is not None:
            _validate_finite("sinr_db", self.sinr_db)
        if self.load is not None:
            _validate_finite("load", self.load)


@dataclass(frozen=True)
class MeasurementSnapshot:
    """One UE measurement snapshot for a handover decision policy."""

    ue_id: str
    timestamp_s: float
    serving_cell: CellMeasurement
    neighbour_cells: List[CellMeasurement]
    step_index: Optional[int] = None
    source: str = "nef_feature_vector"

    def __post_init__(self) -> None:
        if not self.ue_id:
            raise ValueError("ue_id is required")
        _validate_finite("timestamp_s", self.timestamp_s)
        if self.timestamp_s < 0:
            raise ValueError("timestamp_s must be non-negative")
        if self.step_index is not None and self.step_index < 0:
            raise ValueError("step_index must be non-negative")
        if any(n.cell_id == self.serving_cell.cell_id for n in self.neighbour_cells):
            raise ValueError("neighbour_cells must not include the serving cell")

    def measurement_by_cell(self) -> Dict[str, CellMeasurement]:
        """Return all visible cells keyed by cell ID, including serving."""
        measurements = {self.serving_cell.cell_id: self.serving_cell}
        measurements.update({cell.cell_id: cell for cell in self.neighbour_cells})
        return measurements


@dataclass(frozen=True)
class HandoverCandidate:
    """A candidate neighbour evaluated by a rule-based policy."""

    cell_id: str
    measurement: CellMeasurement
    margin_db: float
    trigger_condition_met: bool
    ttt_elapsed_s: float
    ttt_required_s: float


@dataclass(frozen=True)
class PolicyDecision:
    """Common output schema for fixed/tuned A3 and future ML policy adapters."""

    ue_id: str
    timestamp_s: float
    step_index: Optional[int]
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
    confidence: Optional[float] = None

    def __post_init__(self) -> None:
        if self.decision_type == "handover" and not self.selected_target_cell:
            raise ValueError("handover decisions require selected_target_cell")
        if self.decision_type == "stay" and self.selected_target_cell is not None:
            raise ValueError("stay decisions must not include selected_target_cell")
        if self.confidence is not None:
            _validate_finite("confidence", self.confidence)
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError("confidence must be in [0, 1]")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the decision for future JSONL/JSON experiment outputs."""
        return asdict(self)


@dataclass(frozen=True)
class PolicyEvaluationSummary:
    """Aggregate non-ML metrics for replayed policy decisions."""

    handover_count: int
    stay_count: int
    ping_pong_count: int
    per_ue: Dict[str, Dict[str, int]]

