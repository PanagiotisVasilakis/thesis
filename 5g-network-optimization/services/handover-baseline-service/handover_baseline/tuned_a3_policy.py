"""Controlled non-ML tuning for A3 baseline parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .a3_policy import FixedA3Policy
from .models import CellMeasurement, MeasurementSnapshot, PolicyDecision
from .parameters import A3ParameterGrid, A3Parameters


@dataclass(frozen=True)
class A3EvaluationResult:
    """Score for one A3 parameter configuration on a deterministic trace."""

    parameters: A3Parameters
    score: float
    handover_count: int
    ping_pong_count: int
    low_quality_steps: int
    decisions: List[PolicyDecision]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameters": self.parameters.to_dict(),
            "score": self.score,
            "handover_count": self.handover_count,
            "ping_pong_count": self.ping_pong_count,
            "low_quality_steps": self.low_quality_steps,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


@dataclass(frozen=True)
class A3TuningResult:
    """Selected A3 configuration and all tested scores."""

    selected_parameters: A3Parameters
    selected_score: float
    evaluated_configurations: List[A3EvaluationResult]
    objective: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_parameters": self.selected_parameters.to_dict(),
            "selected_score": self.selected_score,
            "objective": self.objective,
            "evaluated_configurations": [
                result.to_dict() for result in self.evaluated_configurations
            ],
        }


class A3TraceTuner:
    """Grid-search tuner for A3 parameters using only non-ML trace metrics."""

    objective = (
        "minimize 10*low_quality_steps + 5*ping_pong_count + handover_count"
    )

    def __init__(
        self,
        grid: A3ParameterGrid,
        *,
        low_quality_rsrp_floor_dbm: float = -110.0,
        ping_pong_window_s: float = 60.0,
    ) -> None:
        self.grid = grid
        self.low_quality_rsrp_floor_dbm = low_quality_rsrp_floor_dbm
        self.ping_pong_window_s = ping_pong_window_s

    def fit(self, trace: Sequence[MeasurementSnapshot]) -> A3TuningResult:
        """Evaluate every grid point and return the lowest-scoring parameter set."""
        if not trace:
            raise ValueError("trace must contain at least one MeasurementSnapshot")

        evaluated = [
            self.evaluate_parameters(parameters, trace)
            for parameters in self.grid.iter_parameters()
        ]
        selected = min(
            evaluated,
            key=lambda result: (
                result.score,
                result.ping_pong_count,
                result.handover_count,
                result.parameters.hysteresis_db,
                result.parameters.time_to_trigger_s,
                result.parameters.a3_offset_db,
            ),
        )
        return A3TuningResult(
            selected_parameters=selected.parameters,
            selected_score=selected.score,
            evaluated_configurations=evaluated,
            objective=self.objective,
        )

    def evaluate_parameters(
        self, parameters: A3Parameters, trace: Sequence[MeasurementSnapshot]
    ) -> A3EvaluationResult:
        """Replay one deterministic trace with one A3 parameter set."""
        policy = FixedA3Policy(parameters)
        decisions: List[PolicyDecision] = []
        serving_by_ue: Dict[str, str] = {}
        last_handover_by_ue: Dict[str, tuple[str, str, float]] = {}
        handover_count = 0
        ping_pong_count = 0
        low_quality_steps = 0

        for raw_snapshot in trace:
            current_serving = serving_by_ue.get(
                raw_snapshot.ue_id, raw_snapshot.serving_cell.cell_id
            )
            snapshot = self._with_serving_cell(raw_snapshot, current_serving)
            if snapshot.serving_cell.rsrp_dbm < self.low_quality_rsrp_floor_dbm:
                low_quality_steps += 1

            decision = policy.decide(snapshot)
            decisions.append(decision)
            if decision.decision_type != "handover" or decision.selected_target_cell is None:
                continue

            handover_count += 1
            previous = last_handover_by_ue.get(decision.ue_id)
            if previous is not None:
                previous_from, previous_to, previous_time = previous
                if (
                    previous_from == decision.selected_target_cell
                    and previous_to == decision.current_serving_cell
                    and decision.timestamp_s - previous_time <= self.ping_pong_window_s
                ):
                    ping_pong_count += 1

            last_handover_by_ue[decision.ue_id] = (
                decision.current_serving_cell,
                decision.selected_target_cell,
                decision.timestamp_s,
            )
            serving_by_ue[decision.ue_id] = decision.selected_target_cell

        score = float(10 * low_quality_steps + 5 * ping_pong_count + handover_count)
        return A3EvaluationResult(
            parameters=parameters,
            score=score,
            handover_count=handover_count,
            ping_pong_count=ping_pong_count,
            low_quality_steps=low_quality_steps,
            decisions=decisions,
        )

    @staticmethod
    def _with_serving_cell(
        snapshot: MeasurementSnapshot, serving_cell_id: str
    ) -> MeasurementSnapshot:
        measurements = snapshot.measurement_by_cell()
        if serving_cell_id not in measurements:
            return snapshot

        serving = measurements[serving_cell_id]
        neighbours = [
            measurement
            for cell_id, measurement in measurements.items()
            if cell_id != serving_cell_id
        ]
        return MeasurementSnapshot(
            ue_id=snapshot.ue_id,
            timestamp_s=snapshot.timestamp_s,
            step_index=snapshot.step_index,
            serving_cell=serving,
            neighbour_cells=neighbours,
            source=snapshot.source,
        )


class TunedA3Policy:
    """A3 policy wrapper using parameters selected by ``A3TraceTuner``."""

    def __init__(self, tuning_result: A3TuningResult) -> None:
        self.tuning_result = tuning_result
        self._delegate = FixedA3Policy(
            tuning_result.selected_parameters,
            name="tuned_a3_baseline",
        )

    @property
    def name(self) -> str:
        return "tuned_a3_baseline"

    @property
    def parameters(self) -> Dict[str, Any]:
        return self.tuning_result.selected_parameters.to_dict()

    def decide(self, snapshot: MeasurementSnapshot) -> PolicyDecision:
        return self._delegate.decide(snapshot)

    def reset(self, ue_id: Optional[str] = None) -> None:
        self._delegate.reset(ue_id)

    @classmethod
    def from_trace(
        cls,
        trace: Sequence[MeasurementSnapshot],
        grid: A3ParameterGrid,
    ) -> "TunedA3Policy":
        return cls(A3TraceTuner(grid).fit(trace))


def build_snapshot_trace(
    ue_id: str,
    rows: Iterable[tuple[float, str, Dict[str, float]]],
) -> List[MeasurementSnapshot]:
    """Convenience helper for deterministic tests and future smoke commands."""
    trace = []
    for index, (timestamp_s, serving_cell_id, rsrp_by_cell) in enumerate(rows):
        if serving_cell_id not in rsrp_by_cell:
            raise ValueError(f"serving cell {serving_cell_id} missing from row")
        serving = CellMeasurement(serving_cell_id, rsrp_by_cell[serving_cell_id])
        neighbours = [
            CellMeasurement(cell_id, rsrp)
            for cell_id, rsrp in rsrp_by_cell.items()
            if cell_id != serving_cell_id
        ]
        trace.append(
            MeasurementSnapshot(
                ue_id=ue_id,
                timestamp_s=timestamp_s,
                step_index=index,
                serving_cell=serving,
                neighbour_cells=neighbours,
                source="deterministic_toy_trace",
            )
        )
    return trace

