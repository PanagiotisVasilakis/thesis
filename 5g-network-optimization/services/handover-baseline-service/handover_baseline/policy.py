"""Policy protocol and helpers for interchangeable handover controllers."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from .models import MeasurementSnapshot, PolicyDecision


class HandoverPolicy(Protocol):
    """Common strategy interface for non-ML baselines and future ML adapters."""

    @property
    def name(self) -> str:
        """Stable policy name for outputs and metrics."""

    @property
    def parameters(self) -> Dict[str, Any]:
        """JSON-serializable policy parameters."""

    def decide(self, snapshot: MeasurementSnapshot) -> PolicyDecision:
        """Return a stay/handover decision for one measurement snapshot."""

    def reset(self, ue_id: Optional[str] = None) -> None:
        """Reset state for one UE or all UEs."""


def stay_decision(
    snapshot: MeasurementSnapshot,
    *,
    policy_name: str,
    policy_parameters: Dict[str, Any],
    trigger_condition_result: bool,
    time_to_trigger_state: Dict[str, Any],
    cooldown_state: Dict[str, Any],
    reason: str,
    debug: Optional[Dict[str, Any]] = None,
) -> PolicyDecision:
    """Build a schema-compatible stay decision."""
    return PolicyDecision(
        ue_id=snapshot.ue_id,
        timestamp_s=snapshot.timestamp_s,
        step_index=snapshot.step_index,
        current_serving_cell=snapshot.serving_cell.cell_id,
        selected_target_cell=None,
        decision_type="stay",
        policy_name=policy_name,
        policy_parameters=policy_parameters,
        serving_measurement_value=snapshot.serving_cell.rsrp_dbm,
        neighbour_measurements_considered={
            cell.cell_id: cell.rsrp_dbm for cell in snapshot.neighbour_cells
        },
        trigger_condition_result=trigger_condition_result,
        time_to_trigger_state=time_to_trigger_state,
        cooldown_state=cooldown_state,
        reason=reason,
        debug=debug or {},
        confidence=None,
    )

