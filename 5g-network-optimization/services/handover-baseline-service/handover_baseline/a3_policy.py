"""Fixed standards-inspired A3 handover policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .models import HandoverCandidate, MeasurementSnapshot, PolicyDecision
from .parameters import A3Parameters, FIXED_A3_PARAMETERS
from .policy import stay_decision


@dataclass
class _CandidateTimer:
    started_at_s: float


class FixedA3Policy:
    """Deterministic A3-style non-ML handover baseline.

    This policy is standards-inspired, not a full operator implementation.
    It uses the RSRP-based Event A3 idea with offset, hysteresis,
    per-UE/per-target time-to-trigger, and a cooldown guard.
    """

    def __init__(
        self,
        parameters: A3Parameters = FIXED_A3_PARAMETERS,
        *,
        name: str = "fixed_a3_baseline",
    ) -> None:
        self._parameters = parameters
        self._name = name
        self._candidate_timers: Dict[Tuple[str, str], _CandidateTimer] = {}
        self._last_handover_at_s: Dict[str, float] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._parameters.to_dict()

    def reset(self, ue_id: Optional[str] = None) -> None:
        """Reset TTT/cooldown state for one UE or the entire policy."""
        if ue_id is None:
            self._candidate_timers.clear()
            self._last_handover_at_s.clear()
            return
        self._candidate_timers = {
            key: value for key, value in self._candidate_timers.items() if key[0] != ue_id
        }
        self._last_handover_at_s.pop(ue_id, None)

    def decide(self, snapshot: MeasurementSnapshot) -> PolicyDecision:
        """Evaluate the A3 condition and return an explainable decision."""
        cooldown_state = self._cooldown_state(snapshot)
        if cooldown_state["active"]:
            return stay_decision(
                snapshot,
                policy_name=self.name,
                policy_parameters=self.parameters,
                trigger_condition_result=False,
                time_to_trigger_state=self._ttt_debug(snapshot),
                cooldown_state=cooldown_state,
                reason=(
                    "cooldown_active: suppressing handover to avoid immediate "
                    "ping-pong after the previous handover"
                ),
                debug={
                    "candidate_measurements": {
                        cell.cell_id: cell.rsrp_dbm for cell in snapshot.neighbour_cells
                    }
                },
            )

        candidates = self._evaluate_candidates(snapshot)
        active_candidate_ids = {
            candidate.cell_id for candidate in candidates if candidate.trigger_condition_met
        }
        self._clear_stale_timers(snapshot.ue_id, active_candidate_ids)

        eligible = [
            candidate
            for candidate in candidates
            if candidate.trigger_condition_met
            and candidate.ttt_elapsed_s >= candidate.ttt_required_s
        ]

        if not eligible:
            trigger_any = any(candidate.trigger_condition_met for candidate in candidates)
            reason = (
                "a3_condition_not_met"
                if not trigger_any
                else "time_to_trigger_pending"
            )
            return stay_decision(
                snapshot,
                policy_name=self.name,
                policy_parameters=self.parameters,
                trigger_condition_result=trigger_any,
                time_to_trigger_state=self._ttt_debug(snapshot),
                cooldown_state=cooldown_state,
                reason=reason,
                debug={"candidates": [self._candidate_to_debug(c) for c in candidates]},
            )

        selected = max(
            eligible,
            key=lambda candidate: (
                candidate.measurement.rsrp_dbm,
                candidate.margin_db,
                candidate.cell_id,
            ),
        )
        self._last_handover_at_s[snapshot.ue_id] = snapshot.timestamp_s
        self._clear_ue_timers(snapshot.ue_id)

        return PolicyDecision(
            ue_id=snapshot.ue_id,
            timestamp_s=snapshot.timestamp_s,
            step_index=snapshot.step_index,
            current_serving_cell=snapshot.serving_cell.cell_id,
            selected_target_cell=selected.cell_id,
            decision_type="handover",
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=snapshot.serving_cell.rsrp_dbm,
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm for cell in snapshot.neighbour_cells
            },
            trigger_condition_result=True,
            time_to_trigger_state={
                selected.cell_id: {
                    "elapsed_s": selected.ttt_elapsed_s,
                    "required_s": selected.ttt_required_s,
                    "satisfied": True,
                }
            },
            cooldown_state={"active": False, "remaining_s": 0.0},
            reason=(
                f"a3_triggered: {selected.cell_id} RSRP "
                f"{selected.measurement.rsrp_dbm:.2f} dBm satisfied offset/"
                f"hysteresis and TTT"
            ),
            debug={
                "selected_margin_db": selected.margin_db,
                "candidates": [self._candidate_to_debug(c) for c in candidates],
            },
            confidence=None,
        )

    def _cooldown_state(self, snapshot: MeasurementSnapshot) -> Dict[str, Any]:
        last = self._last_handover_at_s.get(snapshot.ue_id)
        if last is None:
            return {"active": False, "remaining_s": 0.0, "last_handover_at_s": None}

        elapsed = snapshot.timestamp_s - last
        remaining = max(0.0, self._parameters.cooldown_s - elapsed)
        return {
            "active": remaining > 0.0,
            "remaining_s": remaining,
            "last_handover_at_s": last,
        }

    def _evaluate_candidates(
        self, snapshot: MeasurementSnapshot
    ) -> list[HandoverCandidate]:
        candidates = []
        for neighbour in snapshot.neighbour_cells:
            margin_db = (
                neighbour.rsrp_dbm
                + self._parameters.a3_offset_db
                - snapshot.serving_cell.rsrp_dbm
            )
            threshold_ok = (
                self._parameters.minimum_neighbour_rsrp_dbm is None
                or neighbour.rsrp_dbm >= self._parameters.minimum_neighbour_rsrp_dbm
            )
            condition_met = margin_db > self._parameters.hysteresis_db and threshold_ok

            timer_key = (snapshot.ue_id, neighbour.cell_id)
            if condition_met and timer_key not in self._candidate_timers:
                self._candidate_timers[timer_key] = _CandidateTimer(snapshot.timestamp_s)
            timer = self._candidate_timers.get(timer_key)
            elapsed = 0.0 if timer is None else snapshot.timestamp_s - timer.started_at_s

            candidates.append(
                HandoverCandidate(
                    cell_id=neighbour.cell_id,
                    measurement=neighbour,
                    margin_db=margin_db,
                    trigger_condition_met=condition_met,
                    ttt_elapsed_s=max(0.0, elapsed),
                    ttt_required_s=self._parameters.time_to_trigger_s,
                )
            )
        return candidates

    def _clear_stale_timers(self, ue_id: str, active_candidate_ids: set[str]) -> None:
        self._candidate_timers = {
            key: timer
            for key, timer in self._candidate_timers.items()
            if key[0] != ue_id or key[1] in active_candidate_ids
        }

    def _clear_ue_timers(self, ue_id: str) -> None:
        self._candidate_timers = {
            key: timer for key, timer in self._candidate_timers.items() if key[0] != ue_id
        }

    def _ttt_debug(self, snapshot: MeasurementSnapshot) -> Dict[str, Any]:
        debug = {}
        for (ue_id, cell_id), timer in self._candidate_timers.items():
            if ue_id == snapshot.ue_id:
                elapsed = max(0.0, snapshot.timestamp_s - timer.started_at_s)
                debug[cell_id] = {
                    "started_at_s": timer.started_at_s,
                    "elapsed_s": elapsed,
                    "required_s": self._parameters.time_to_trigger_s,
                    "satisfied": elapsed >= self._parameters.time_to_trigger_s,
                }
        return debug

    @staticmethod
    def _candidate_to_debug(candidate: HandoverCandidate) -> Dict[str, Any]:
        return {
            "cell_id": candidate.cell_id,
            "rsrp_dbm": candidate.measurement.rsrp_dbm,
            "margin_db": candidate.margin_db,
            "trigger_condition_met": candidate.trigger_condition_met,
            "ttt_elapsed_s": candidate.ttt_elapsed_s,
            "ttt_required_s": candidate.ttt_required_s,
        }
