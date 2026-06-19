"""Interchangeable policy adapters for offline comparison replay."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from dataclasses import replace
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence

import requests  # type: ignore[import-untyped]

from .complexity import (
    DEFAULT_HIGH_COMPLEXITY_THRESHOLD,
    DEFAULT_MIN_VIABLE_RSRP_DBM,
    DEFAULT_MIN_VIABLE_SINR_DB,
    candidate_complexity_for_record,
    is_viable_cell,
)
from .candidate_ranker import build_candidate_ranker_features
from .candidate_ranker_artifact import (
    CandidateRankerArtifact,
    DEFAULT_A3_REENTRY_EXTRA_MARGIN_DB,
    DEFAULT_ML_SEGMENT_HOLD_S,
    DEFAULT_RANKER_MIN_MARGIN,
    DEFAULT_RANKER_MIN_ML_DWELL_S,
    load_candidate_ranker_artifact,
)
from .nef_trace import ML_TRACE_PASSTHROUGH_FIELDS
from .schemas import MeasurementTraceRecord, PolicyDecisionRecord, TraceSchemaError
from .segment_controller_artifact import (
    SEGMENT_CONTROLLER_MODEL_FAMILY,
    SEGMENT_SPARSE_AUTHORITY_MODES,
    SegmentControllerArtifact,
    load_segment_controller_artifact,
)
from .oracle_policy import action_features
from .oracle_ranker_artifact import (
    OracleRankerArtifact,
    load_oracle_ranker_artifact,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_SERVICE_PATH = (
    REPO_ROOT / "5g-network-optimization" / "services" / "handover-baseline-service"
)


class PolicyAdapterError(RuntimeError):
    """Raised when a policy adapter cannot produce a reliable decision."""


class ComparisonPolicyAdapter(Protocol):
    """Common strategy interface for offline ML/A3 policy comparison."""

    @property
    def name(self) -> str:
        """Stable policy name used in output files."""

    @property
    def parameters(self) -> Dict[str, Any]:
        """JSON-serializable policy parameters without secrets."""

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        """Return a canonical policy decision for one trace record."""

    def reset(self, ue_id: Optional[str] = None) -> None:
        """Reset any per-UE or global policy state."""


def ensure_baseline_service_importable() -> None:
    """Expose the local baseline package path without creating a service."""
    if not BASELINE_SERVICE_PATH.exists():
        raise PolicyAdapterError(
            f"baseline service path is missing: {BASELINE_SERVICE_PATH}"
        )
    service_path = str(BASELINE_SERVICE_PATH)
    if service_path not in sys.path:
        sys.path.insert(0, service_path)


def trace_record_to_baseline_snapshot(record: MeasurementTraceRecord):
    """Convert a canonical trace record to the baseline service input model."""
    ensure_baseline_service_importable()
    from handover_baseline.models import CellMeasurement, MeasurementSnapshot  # type: ignore[import-not-found]

    visible = record.visible_cell_map
    if record.serving_cell not in visible:
        raise TraceSchemaError(
            f"serving cell {record.serving_cell!r} is not visible for UE {record.ue_id}"
        )

    def convert(cell_id: str) -> CellMeasurement:
        cell = visible[cell_id]
        return CellMeasurement(
            cell_id=cell.cell_id,
            rsrp_dbm=cell.rsrp_dbm,
            rsrq_db=cell.rsrq_db,
            sinr_db=cell.sinr_db,
            load=cell.load,
        )

    return MeasurementSnapshot(
        ue_id=record.ue_id,
        timestamp_s=record.timestamp_s,
        step_index=record.step_index,
        serving_cell=convert(record.serving_cell),
        neighbour_cells=[
            convert(cell.cell_id)
            for cell in record.visible_cells
            if cell.cell_id != record.serving_cell
        ],
        source=record.source,
    )


class FixedA3PolicyAdapter:
    """Adapter around the authoritative baseline-service fixed A3 policy."""

    def __init__(self, policy: Any = None) -> None:
        ensure_baseline_service_importable()
        if policy is None:
            from handover_baseline import FixedA3Policy  # type: ignore[import-not-found]

            policy = FixedA3Policy()
        self._policy = policy

    @property
    def name(self) -> str:
        return str(self._policy.name)

    @property
    def parameters(self) -> Dict[str, Any]:
        return dict(self._policy.parameters)

    def reset(self, ue_id: Optional[str] = None) -> None:
        self._policy.reset(ue_id)

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        started = time.perf_counter()
        baseline_decision = self._policy.decide(trace_record_to_baseline_snapshot(record))
        latency_ms = (time.perf_counter() - started) * 1000.0
        return _from_baseline_decision(
            baseline_decision,
            latency_ms=latency_ms,
            source_record=record,
        )


class TunedA3PolicyAdapter(FixedA3PolicyAdapter):
    """Adapter around a tuned A3 policy selected from real calibration traces."""

    def __init__(self, policy: Any, *, config_data: Optional[Mapping[str, Any]] = None) -> None:
        if policy is None:
            raise PolicyAdapterError(
                "TunedA3PolicyAdapter requires a real tuned policy; "
                "no tuning result will be fabricated."
            )
        super().__init__(policy=policy)
        self._config_data = dict(config_data or {})

    @property
    def tuning_result_dict(self) -> Dict[str, Any]:
        if self._config_data:
            return dict(self._config_data)
        result = getattr(self._policy, "tuning_result", None)
        if result is None or not hasattr(result, "to_dict"):
            raise PolicyAdapterError("tuned A3 policy does not expose a tuning result")
        return dict(result.to_dict())

    @classmethod
    def from_calibration_trace(
        cls,
        calibration_records: Sequence[MeasurementTraceRecord],
        grid: Any = None,
    ) -> "TunedA3PolicyAdapter":
        ensure_baseline_service_importable()
        from handover_baseline import A3ParameterGrid, TunedA3Policy  # type: ignore[import-not-found]

        if not calibration_records:
            raise PolicyAdapterError("calibration_records must not be empty")
        snapshots = [trace_record_to_baseline_snapshot(record) for record in calibration_records]
        selected_grid = grid if grid is not None else A3ParameterGrid()
        return cls(TunedA3Policy.from_trace(snapshots, selected_grid))

    @classmethod
    def from_tuned_config(cls, config_path: Path) -> "TunedA3PolicyAdapter":
        from scripts.policy_comparison.tuned_a3_config import build_tuned_policy_from_config

        policy, config_data = build_tuned_policy_from_config(config_path)
        return cls(policy, config_data=config_data)


class StrongestSignalPolicyAdapter:
    """Classic strongest-neighbour baseline using one RF measurement."""

    def __init__(
        self,
        *,
        metric: str = "rsrp",
        min_margin: float = 0.0,
        name: Optional[str] = None,
    ) -> None:
        if metric not in {"rsrp", "sinr", "rsrq"}:
            raise PolicyAdapterError("metric must be one of rsrp, sinr, rsrq")
        self.metric = metric
        self.min_margin = float(min_margin)
        self._name = name or f"strongest_{metric}_baseline"

    @property
    def name(self) -> str:
        return self._name

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"metric": self.metric, "min_margin": self.min_margin}

    def reset(self, ue_id: Optional[str] = None) -> None:
        return None

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        started = time.perf_counter()
        visible = record.visible_cell_map
        serving = visible[record.serving_cell]
        serving_value = _cell_metric(serving, self.metric)
        candidates = {
            cell.cell_id: _cell_metric(cell, self.metric)
            for cell in record.visible_cells
            if cell.cell_id != record.serving_cell
        }
        available = {
            cell_id: value for cell_id, value in candidates.items() if value is not None
        }
        complexity = candidate_complexity_for_record(record)
        if serving_value is None or not available:
            target = None
            decision_type = "stay"
            reason = f"strongest_{self.metric}_measurement_unavailable"
            trigger = False
        else:
            target, target_value = max(
                available.items(),
                key=lambda item: (item[1], item[0]),
            )
            trigger = target_value - serving_value > self.min_margin
            decision_type = "handover" if trigger else "stay"
            reason = (
                f"strongest_{self.metric}_selected"
                if trigger
                else f"strongest_{self.metric}_margin_not_met"
            )

        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=target if decision_type == "handover" else None,
            decision_type=decision_type,  # type: ignore[arg-type]
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=float(serving.rsrp_dbm),
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm
                for cell in record.visible_cells
                if cell.cell_id != record.serving_cell
            },
            trigger_condition_result=trigger,
            time_to_trigger_state={},
            cooldown_state={},
            reason=reason,
            debug={
                "decision_source": self.name,
                "selection_metric": self.metric,
                "serving_metric_value": serving_value,
                "candidate_metric_values": available,
                "candidate_complexity": complexity.to_dict(),
                **_trace_debug_context(record),
            },
            decision_latency_ms=(time.perf_counter() - started) * 1000.0,
            confidence=None,
        )


class NoHandoverPolicyAdapter:
    """Explicit stay baseline used to detect policies that win by doing nothing."""

    @property
    def name(self) -> str:
        return "no_handover_baseline"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"action": "always_stay"}

    def reset(self, ue_id: Optional[str] = None) -> None:
        return None

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        started = time.perf_counter()
        serving = record.visible_cell_map[record.serving_cell]
        complexity = candidate_complexity_for_record(record)
        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=None,
            decision_type="stay",
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm
                for cell in record.visible_cells
                if cell.cell_id != record.serving_cell
            },
            trigger_condition_result=False,
            time_to_trigger_state={},
            cooldown_state={},
            reason="no_handover_baseline_stay",
            debug={
                "decision_source": self.name,
                "candidate_complexity": complexity.to_dict(),
                **_trace_debug_context(record),
            },
            decision_latency_ms=(time.perf_counter() - started) * 1000.0,
            confidence=None,
        )


class ConditionalHandoverPolicyAdapter:
    """Measurement-only prepare/execute conditional handover baseline."""

    def __init__(
        self,
        *,
        preparation_margin_db: float = 1.0,
        execution_margin_db: float = 3.0,
        consecutive_execution_votes: int = 2,
    ) -> None:
        self.preparation_margin_db = float(preparation_margin_db)
        self.execution_margin_db = float(execution_margin_db)
        self.consecutive_execution_votes = int(consecutive_execution_votes)
        self._state: Dict[str, Dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "conditional_handover_baseline"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "preparation_margin_db": self.preparation_margin_db,
            "execution_margin_db": self.execution_margin_db,
            "consecutive_execution_votes": self.consecutive_execution_votes,
        }

    def reset(self, ue_id: Optional[str] = None) -> None:
        if ue_id is None:
            self._state.clear()
        else:
            self._state.pop(ue_id, None)

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        started = time.perf_counter()
        serving = record.visible_cell_map[record.serving_cell]
        viable = [
            cell
            for cell in record.visible_cells
            if cell.cell_id != record.serving_cell
            and cell.rsrp_dbm >= DEFAULT_MIN_VIABLE_RSRP_DBM
            and (cell.sinr_db is None or cell.sinr_db >= DEFAULT_MIN_VIABLE_SINR_DB)
        ]
        best = max(viable, key=lambda cell: (cell.rsrp_dbm, cell.cell_id)) if viable else None
        margin = None if best is None else best.rsrp_dbm - serving.rsrp_dbm
        state = self._state.setdefault(record.ue_id, {"prepared": None, "votes": 0})
        if best is None or margin is None or margin < self.preparation_margin_db:
            state.update({"prepared": None, "votes": 0})
        elif state.get("prepared") != best.cell_id:
            state.update({"prepared": best.cell_id, "votes": 0})

        if (
            best is not None
            and state.get("prepared") == best.cell_id
            and margin is not None
            and margin >= self.execution_margin_db
        ):
            state["votes"] = int(state.get("votes", 0)) + 1
        else:
            state["votes"] = 0
        trigger = bool(
            best is not None
            and state.get("prepared") == best.cell_id
            and int(state.get("votes", 0)) >= self.consecutive_execution_votes
        )
        target = best.cell_id if trigger and best is not None else None
        if trigger:
            state.update({"prepared": None, "votes": 0})
        complexity = candidate_complexity_for_record(record)
        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=target,
            decision_type="handover" if trigger else "stay",
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm
                for cell in record.visible_cells
                if cell.cell_id != record.serving_cell
            },
            trigger_condition_result=trigger,
            time_to_trigger_state={"prepared_target": state.get("prepared"), "votes": state.get("votes", 0)},
            cooldown_state={},
            reason="conditional_handover_execute" if trigger else "conditional_handover_wait",
            debug={
                "decision_source": self.name,
                "prepared_target": state.get("prepared"),
                "execution_votes": state.get("votes", 0),
                "best_margin_db": margin,
                "candidate_complexity": complexity.to_dict(),
                **_trace_debug_context(record),
            },
            decision_latency_ms=(time.perf_counter() - started) * 1000.0,
            confidence=None,
        )


class LoadAwareA3PolicyAdapter:
    """Classic A3-like baseline with a load penalty on RF margins."""

    def __init__(
        self,
        *,
        hysteresis_db: float = 2.0,
        a3_offset_db: float = 0.0,
        load_penalty_db: float = 4.0,
    ) -> None:
        self.hysteresis_db = float(hysteresis_db)
        self.a3_offset_db = float(a3_offset_db)
        self.load_penalty_db = float(load_penalty_db)

    @property
    def name(self) -> str:
        return "load_aware_a3_baseline"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "hysteresis_db": self.hysteresis_db,
            "a3_offset_db": self.a3_offset_db,
            "load_penalty_db": self.load_penalty_db,
        }

    def reset(self, ue_id: Optional[str] = None) -> None:
        return None

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        started = time.perf_counter()
        serving = record.visible_cell_map[record.serving_cell]
        serving_score = _load_adjusted_rsrp(serving, self.load_penalty_db)
        margins: Dict[str, float] = {}
        for cell in record.visible_cells:
            if cell.cell_id == record.serving_cell:
                continue
            margins[cell.cell_id] = (
                _load_adjusted_rsrp(cell, self.load_penalty_db)
                + self.a3_offset_db
                - serving_score
            )

        target = None
        trigger = False
        if margins:
            target, margin = max(margins.items(), key=lambda item: (item[1], item[0]))
            trigger = margin > self.hysteresis_db
        complexity = candidate_complexity_for_record(record)
        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=target if trigger else None,
            decision_type="handover" if trigger else "stay",
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm
                for cell in record.visible_cells
                if cell.cell_id != record.serving_cell
            },
            trigger_condition_result=trigger,
            time_to_trigger_state={},
            cooldown_state={},
            reason="load_aware_a3_triggered" if trigger else "load_aware_a3_condition_not_met",
            debug={
                "decision_source": self.name,
                "serving_load_adjusted_rsrp": serving_score,
                "load_adjusted_margins": margins,
                "candidate_complexity": complexity.to_dict(),
                **_trace_debug_context(record),
            },
            decision_latency_ms=(time.perf_counter() - started) * 1000.0,
            confidence=None,
        )


class VelocityAdaptiveA3PolicyAdapter(FixedA3PolicyAdapter):
    """A3 baseline whose selected parameters depend on UE speed."""

    def __init__(self) -> None:
        ensure_baseline_service_importable()
        from handover_baseline import A3Parameters, FixedA3Policy  # type: ignore[import-not-found]

        self._tiers = {
            "low": FixedA3Policy(
                A3Parameters(
                    a3_offset_db=0.0,
                    hysteresis_db=2.5,
                    time_to_trigger_s=1.0,
                    cooldown_s=5.0,
                    minimum_neighbour_rsrp_dbm=-115.0,
                ),
                name="velocity_adaptive_a3_baseline",
            ),
            "medium": FixedA3Policy(
                A3Parameters(
                    a3_offset_db=0.0,
                    hysteresis_db=2.0,
                    time_to_trigger_s=0.5,
                    cooldown_s=3.0,
                    minimum_neighbour_rsrp_dbm=-115.0,
                ),
                name="velocity_adaptive_a3_baseline",
            ),
            "high": FixedA3Policy(
                A3Parameters(
                    a3_offset_db=-1.0,
                    hysteresis_db=1.0,
                    time_to_trigger_s=0.0,
                    cooldown_s=1.0,
                    minimum_neighbour_rsrp_dbm=-115.0,
                ),
                name="velocity_adaptive_a3_baseline",
            ),
        }

    @property
    def name(self) -> str:
        return "velocity_adaptive_a3_baseline"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "speed_tiers_mps": {"low_max": 5.0, "medium_max": 25.0},
            "tier_parameters": {
                tier: policy.parameters for tier, policy in self._tiers.items()
            },
        }

    def reset(self, ue_id: Optional[str] = None) -> None:
        for policy in self._tiers.values():
            policy.reset(ue_id)

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        tier = _speed_tier(record.speed_mps)
        started = time.perf_counter()
        baseline_decision = self._tiers[tier].decide(trace_record_to_baseline_snapshot(record))
        decision = _from_baseline_decision(
            baseline_decision,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            source_record=record,
        )
        debug = dict(decision.debug)
        debug["decision_source"] = self.name
        debug["speed_tier"] = tier
        debug["candidate_complexity"] = candidate_complexity_for_record(record).to_dict()
        return replace(
            decision,
            policy_name=self.name,
            policy_parameters=self.parameters,
            debug=debug,
        )


class MLPolicyAdapter:
    """Strict ML-service adapter for offline replay.

    The adapter calls the existing ML `/api/predict-with-qos` endpoint. If the
    ML service is unreachable or returns an error, this adapter raises instead
    of silently falling back to A3.
    """

    def __init__(
        self,
        *,
        ml_base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout_s: float = 5.0,
        max_retries: int = 3,
        retry_sleep_s: float = 0.25,
        session: Any = None,
    ) -> None:
        if not ml_base_url:
            raise PolicyAdapterError("ml_base_url is required")
        self.ml_base_url = ml_base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.retry_sleep_s = retry_sleep_s
        self.session = session or requests.Session()
        self._access_token: Optional[str] = None

    @property
    def name(self) -> str:
        return "ml_policy"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "ml_base_url": self.ml_base_url,
            "endpoint": "/api/predict-with-qos",
            "auth_configured": bool(self.username and self.password),
            "transport_max_retries": self.max_retries,
        }

    def reset(self, ue_id: Optional[str] = None) -> None:
        return None

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        payload = trace_record_to_ml_payload(record)
        started = time.perf_counter()
        response_data = self._post_prediction(payload)
        latency_ms = (time.perf_counter() - started) * 1000.0

        _raise_on_hidden_ml_fallback(response_data)
        raw_target = response_data.get("predicted_antenna") or response_data.get("antenna_id")
        target, target_resolution = _resolve_ml_target_to_visible(raw_target, record)
        confidence = _optional_float(response_data.get("confidence"))
        if target is None or target == record.serving_cell:
            decision_type = "stay"
            selected_target = None
            reason = "ml_returned_no_handover_target"
        else:
            decision_type = "handover"
            selected_target = target
            reason = "ml_selected_handover_target"

        visible = record.visible_cell_map
        serving = visible[record.serving_cell]
        neighbours = {
            cell.cell_id: cell.rsrp_dbm
            for cell in record.visible_cells
            if cell.cell_id != record.serving_cell
        }

        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=selected_target,
            decision_type=decision_type,  # type: ignore[arg-type]
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered=neighbours,
            trigger_condition_result=decision_type == "handover",
            time_to_trigger_state={},
            cooldown_state={},
            reason=reason,
            debug={
                "decision_source": "ml",
                "ml_response_keys": sorted(str(key) for key in response_data.keys()),
                "qos_compliance": response_data.get("qos_compliance"),
                "ml_target_resolution": target_resolution,
                "raw_ml_response_metadata": _safe_ml_response_metadata(response_data),
                "candidate_complexity": candidate_complexity_for_record(record).to_dict(),
                **_trace_debug_context(record),
            },
            decision_latency_ms=latency_ms,
            confidence=confidence,
        )

    def _post_prediction(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        url = f"{self.ml_base_url}/api/predict-with-qos"
        response = self._post_prediction_with_transport_retry(url, payload)
        if response.status_code == 401 and self.username and self.password:
            self._login()
            response = self._post_prediction_with_transport_retry(url, payload)
        if response.status_code >= 400:
            body = getattr(response, "text", "")
            raise PolicyAdapterError(
                f"ML service returned HTTP {response.status_code} for prediction: "
                f"{str(body)[:300]}"
            )
        data = response.json()
        if not isinstance(data, Mapping):
            raise PolicyAdapterError("ML prediction response must be a JSON object")
        return data

    def _post_prediction_with_transport_retry(
        self,
        url: str,
        payload: Mapping[str, Any],
    ):
        last_error: Optional[BaseException] = None
        attempts = max(1, self.max_retries + 1)
        for attempt in range(attempts):
            try:
                return self.session.post(
                    url,
                    json=dict(payload),
                    headers=self._headers(),
                    timeout=self.timeout_s,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(self.retry_sleep_s)
                    continue
                break
        raise PolicyAdapterError(
            "ML prediction request failed after transport retries: "
            f"{last_error}"
        )

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def _login(self) -> None:
        response = self.session.post(
            f"{self.ml_base_url}/api/login",
            json={"username": self.username, "password": self.password},
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            raise PolicyAdapterError(
                f"ML service login failed with HTTP {response.status_code}"
            )
        data = response.json()
        token = data.get("access_token") if isinstance(data, Mapping) else None
        if not token:
            raise PolicyAdapterError("ML service login response missing access_token")
        self._access_token = str(token)


class CandidateRankerPolicyAdapter:
    """Offline-only ML adapter backed by a local candidate-ranker artifact."""

    def __init__(
        self,
        artifact: CandidateRankerArtifact | Path,
        *,
        min_margin: Optional[float] = None,
        min_ml_dwell_s: Optional[float] = None,
        emergency_rsrp_floor_dbm: float = -110.0,
    ) -> None:
        self.artifact = (
            load_candidate_ranker_artifact(artifact)
            if isinstance(artifact, Path)
            else artifact
        )
        params = (
            self.artifact.decision_parameters
            if hasattr(self.artifact, "decision_parameters")
            else {}
        )
        self.min_margin = float(
            min_margin
            if min_margin is not None
            else params.get("selected_min_margin", DEFAULT_RANKER_MIN_MARGIN)
        )
        self.min_ml_dwell_s = float(
            min_ml_dwell_s
            if min_ml_dwell_s is not None
            else params.get("min_ml_dwell_s", DEFAULT_RANKER_MIN_ML_DWELL_S)
        )
        self.emergency_rsrp_floor_dbm = float(emergency_rsrp_floor_dbm)
        self._replay_state_by_ue: Dict[str, Dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "ml_policy"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "ml_backend": "candidate_ranker",
            "ranker_artifact": str(self.artifact.path),
            "ranker_artifact_sha256": self.artifact.artifact_sha256,
            "model_family": self.artifact.model_family,
            "score_threshold": self.artifact.selected_threshold,
            "min_margin": self.min_margin,
            "min_ml_dwell_s": self.min_ml_dwell_s,
            "emergency_rsrp_floor_dbm": self.emergency_rsrp_floor_dbm,
        }

    def reset(self, ue_id: Optional[str] = None) -> None:
        if ue_id is None:
            self._replay_state_by_ue.clear()
        else:
            self._replay_state_by_ue.pop(ue_id, None)
        return None

    def set_replay_state(self, ue_id: str, state: Mapping[str, Any]) -> None:
        self._replay_state_by_ue[str(ue_id)] = dict(state)

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        started = time.perf_counter()
        state = self._replay_state_by_ue.get(record.ue_id, {})
        rows = build_candidate_ranker_features(
            record,
            recent_handover_count=_optional_int(
                state.get("recent_handover_count"),
                default=None,
            ),
            time_since_last_handover_s=_optional_float(
                state.get("time_since_last_handover_s"),
                default=None,
            ),
            current_dwell_time_s=_optional_float(
                state.get("current_dwell_time_s"),
                default=None,
            ),
            last_handover_source=(
                None
                if state.get("last_handover_source") is None
                else str(state.get("last_handover_source"))
            ),
            previous_serving_cell=(
                None
                if state.get("previous_serving_cell") is None
                else str(state.get("previous_serving_cell"))
            ),
            previous_target_cell=(
                None
                if state.get("previous_target_cell") is None
                else str(state.get("previous_target_cell"))
            ),
        )
        complexity = candidate_complexity_for_record(record)
        visible = record.visible_cell_map
        serving = visible[record.serving_cell]
        neighbours = {
            cell.cell_id: cell.rsrp_dbm
            for cell in record.visible_cells
            if cell.cell_id != record.serving_cell
        }
        candidate_scores = self.artifact.score_rows(rows)
        selected_target = None
        selected_score = None
        best_candidate = None
        best_score = None
        stay_score = 0.0
        margin_vs_stay = None
        dwell_guard_applied = False
        if candidate_scores:
            best_candidate, best_score = max(
                candidate_scores.items(),
                key=lambda item: (item[1], item[0]),
            )
            selected_score = best_score
            margin_vs_stay = float(best_score - stay_score)
            time_since_handover = _optional_float(
                state.get("time_since_last_handover_s"),
                default=None,
            )
            last_source = str(state.get("last_handover_source") or "")
            dwell_guard_applied = (
                last_source in {"ml_high_complexity", "candidate_ranker", "ml_policy"}
                and time_since_handover is not None
                and time_since_handover < self.min_ml_dwell_s
                and serving.rsrp_dbm > self.emergency_rsrp_floor_dbm
            )
            if not dwell_guard_applied and margin_vs_stay >= self.min_margin:
                selected_target = best_candidate

        if selected_target is not None and selected_target not in neighbours:
            raise PolicyAdapterError(
                f"ranker selected invalid target {selected_target!r} at "
                f"step {record.step_index}"
            )

        decision_type = "handover" if selected_target is not None else "stay"
        target_resolution = {
            "raw_target": selected_target,
            "resolved_target": selected_target,
            "method": "candidate_ranker_score",
        }
        debug = {
            "decision_source": "candidate_ranker",
            "ml_backend": "candidate_ranker",
            "ranker_candidate_scores": candidate_scores,
            "ranker_best_candidate": best_candidate,
            "ranker_best_candidate_score": best_score,
            "ranker_selected_candidate": selected_target,
            "ranker_selected_score": selected_score,
            "ranker_score_threshold": self.artifact.selected_threshold,
            "ranker_stay_score": stay_score,
            "ranker_margin_vs_stay": margin_vs_stay,
            "ranker_min_margin": self.min_margin,
            "dwell_guard_applied": dwell_guard_applied,
            "ranker_min_ml_dwell_s": self.min_ml_dwell_s,
            "ranker_artifact_sha256": self.artifact.artifact_sha256,
            "ranker_model_family": self.artifact.model_family,
            "ranker_metadata": self.artifact.safe_metadata(),
            "candidate_complexity": complexity.to_dict(),
            "ml_target_resolution": target_resolution,
            "qos_compliance": _offline_qos_compliance(record),
            "raw_ml_response_metadata": {
                "ml_backend": "candidate_ranker",
                "ranker_artifact_sha256": self.artifact.artifact_sha256,
            },
            **_trace_debug_context(record),
        }
        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=selected_target,
            decision_type=decision_type,  # type: ignore[arg-type]
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered=neighbours,
            trigger_condition_result=decision_type == "handover",
            time_to_trigger_state={},
            cooldown_state={},
            reason=(
                "ranker_selected_handover_target"
                if decision_type == "handover"
                else (
                    "ranker_dwell_guard"
                    if dwell_guard_applied
                    else "ranker_margin_below_threshold"
                )
            ),
            debug=debug,
            decision_latency_ms=(time.perf_counter() - started) * 1000.0,
            confidence=None,
        )


class OracleRankerPolicyAdapter:
    """Explicit-stay cost-to-go ranker selected by the model ladder."""

    def __init__(
        self,
        artifact: OracleRankerArtifact | Path,
        *,
        min_utility_margin: Optional[float] = None,
    ) -> None:
        self.artifact = (
            load_oracle_ranker_artifact(artifact)
            if isinstance(artifact, Path)
            else artifact
        )
        configured = self.artifact.metadata.get("selected_min_utility_margin", 0.0)
        self.min_utility_margin = float(
            configured if min_utility_margin is None else min_utility_margin
        )
        self._replay_state_by_ue: Dict[str, Dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "ml_policy"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "ml_backend": "oracle_ranker",
            "artifact_sha256": self.artifact.artifact_sha256,
            "model_family": self.artifact.model_family,
            "selected_model_family": self.artifact.metadata.get(
                "selected_model_family"
            ),
            "min_utility_margin": self.min_utility_margin,
        }

    def reset(self, ue_id: Optional[str] = None) -> None:
        if ue_id is None:
            self._replay_state_by_ue.clear()
        else:
            self._replay_state_by_ue.pop(ue_id, None)

    def set_replay_state(self, ue_id: str, state: Mapping[str, Any]) -> None:
        self._replay_state_by_ue[str(ue_id)] = dict(state)

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        started = time.perf_counter()
        state = self._replay_state_by_ue.get(record.ue_id, {})
        actions = [record.serving_cell] + [
            cell.cell_id
            for cell in record.visible_cells
            if cell.cell_id != record.serving_cell and is_viable_cell(cell)
        ]
        rows = [
            action_features(
                record,
                serving_cell=record.serving_cell,
                action_cell=action,
                recent_handover_count=int(state.get("recent_handover_count") or 0),
                dwell_time_s=float(state.get("current_dwell_time_s") or 0.0),
            )
            for action in actions
        ]
        scores = self.artifact.score_rows(rows)
        score_by_action = dict(zip(actions, scores))
        stay_score = score_by_action[record.serving_cell]
        candidates = {
            action: score
            for action, score in score_by_action.items()
            if action != record.serving_cell
        }
        best_candidate, best_score = (
            max(candidates.items(), key=lambda item: (item[1], item[0]))
            if candidates
            else (None, None)
        )
        margin = None if best_score is None else float(best_score - stay_score)
        target = (
            best_candidate
            if best_candidate is not None
            and margin is not None
            and margin >= self.min_utility_margin
            and best_score > stay_score
            else None
        )
        serving = record.visible_cell_map[record.serving_cell]
        complexity = candidate_complexity_for_record(record)
        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=target,
            decision_type="handover" if target is not None else "stay",
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm
                for cell in record.visible_cells
                if cell.cell_id != record.serving_cell
            },
            trigger_condition_result=target is not None,
            time_to_trigger_state={},
            cooldown_state={},
            reason="oracle_ranker_handover" if target else "oracle_ranker_stay",
            debug={
                "decision_source": "oracle_ranker",
                "ml_backend": "oracle_ranker",
                "raw_action_scores": score_by_action,
                "stay_score": stay_score,
                "best_candidate": best_candidate,
                "best_candidate_score": best_score,
                "utility_margin_vs_stay": margin,
                "minimum_utility_margin": self.min_utility_margin,
                "artifact_hash": self.artifact.artifact_sha256,
                "model_family": self.artifact.model_family,
                "oracle_ranker_metadata": {
                    "model_sha256": self.artifact.artifact_sha256,
                    "selected_model_family": self.artifact.metadata.get(
                        "selected_model_family"
                    ),
                    "feature_columns": list(self.artifact.feature_columns),
                    "aggregate_validation_metrics": self.artifact.metadata.get(
                        "aggregate_validation_metrics", {}
                    ),
                    "validation_split": self.artifact.metadata.get(
                        "validation_split"
                    ),
                    "training_seeds": self.artifact.metadata.get(
                        "training_seeds", []
                    ),
                },
                "ml_target_resolution": {
                    "raw_target": target,
                    "resolved_target": target,
                    "method": "explicit_stay_oracle_ranker",
                },
                "raw_ml_response_metadata": {
                    "ml_backend": "oracle_ranker",
                    "model_ready": True,
                    "artifact_sha256": self.artifact.artifact_sha256,
                },
                "fallback": False,
                "synthetic_bootstrap": False,
                "geographic_override": False,
                "candidate_complexity": complexity.to_dict(),
                **_trace_debug_context(record),
            },
            decision_latency_ms=(time.perf_counter() - started) * 1000.0,
            confidence=None,
        )


class SegmentControllerPolicyAdapter:
    """Offline two-stage segment controller.

    With ``sparse_policy=None`` this behaves as ML-only: outside active ML
    segments it stays. With a sparse policy it becomes the thesis adaptive
    controller: sparse/moderate inactive snapshots use tuned A3, high-complexity
    inactive snapshots use the segment entry decision, and active ML segments
    hold until an explicit exit.
    """

    def __init__(
        self,
        artifact: SegmentControllerArtifact | Path,
        *,
        policy_name: str = "ml_policy",
        sparse_policy: Optional[ComparisonPolicyAdapter] = None,
        high_complexity_threshold: Optional[int] = None,
        entry_threshold: Optional[float] = None,
        candidate_margin_min: Optional[float] = None,
        exit_threshold: Optional[float] = None,
        consecutive_exit_votes: Optional[int] = None,
        min_segment_duration_s: Optional[float] = None,
        max_segment_duration_s: Optional[float] = None,
        emergency_rsrp_floor_dbm: Optional[float] = None,
        post_exit_a3_guard_s: Optional[float] = None,
        post_exit_a3_extra_margin_db: Optional[float] = None,
        high_reject_hold_s: Optional[float] = None,
        sparse_authority_mode: Optional[str] = None,
        sparse_serving_rsrp_floor_dbm: Optional[float] = None,
        sparse_serving_sinr_floor_db: Optional[float] = None,
        sparse_a3_extra_margin_db: Optional[float] = None,
    ) -> None:
        self.artifact = (
            load_segment_controller_artifact(artifact)
            if isinstance(artifact, Path)
            else artifact
        )
        if self.artifact.model_family != SEGMENT_CONTROLLER_MODEL_FAMILY:
            raise PolicyAdapterError("segment controller artifact has wrong model family")
        params = self.artifact.decision_parameters
        self._name = policy_name
        self.sparse_policy = sparse_policy
        self.high_complexity_threshold = int(
            high_complexity_threshold
            if high_complexity_threshold is not None
            else params.get("high_complexity_threshold", DEFAULT_HIGH_COMPLEXITY_THRESHOLD)
        )
        self.entry_threshold = float(
            entry_threshold
            if entry_threshold is not None
            else params.get("entry_threshold", 0.5)
        )
        self.candidate_margin_min = float(
            candidate_margin_min
            if candidate_margin_min is not None
            else params.get("candidate_margin_min", 20.0)
        )
        self.exit_threshold = float(
            exit_threshold
            if exit_threshold is not None
            else params.get("exit_threshold", 0.7)
        )
        self.consecutive_exit_votes = max(
            1,
            int(
                consecutive_exit_votes
                if consecutive_exit_votes is not None
                else params.get("consecutive_exit_votes", 3)
            ),
        )
        self.min_segment_duration_s = float(
            min_segment_duration_s
            if min_segment_duration_s is not None
            else params.get("min_segment_duration_s", 6.0)
        )
        self.max_segment_duration_s = float(
            max_segment_duration_s
            if max_segment_duration_s is not None
            else params.get("max_segment_duration_s", 45.0)
        )
        self.emergency_rsrp_floor_dbm = float(
            emergency_rsrp_floor_dbm
            if emergency_rsrp_floor_dbm is not None
            else params.get("emergency_rsrp_floor_dbm", -112.0)
        )
        self.post_exit_a3_guard_s = max(
            0.0,
            float(
                post_exit_a3_guard_s
                if post_exit_a3_guard_s is not None
                else params.get("post_exit_a3_guard_s", 0.0)
            ),
        )
        self.post_exit_a3_extra_margin_db = max(
            0.0,
            float(
                post_exit_a3_extra_margin_db
                if post_exit_a3_extra_margin_db is not None
                else params.get("post_exit_a3_extra_margin_db", 0.0)
            ),
        )
        self.high_reject_hold_s = max(
            0.0,
            float(
                high_reject_hold_s
                if high_reject_hold_s is not None
                else params.get("high_reject_hold_s", 0.0)
            ),
        )
        self.sparse_authority_mode = str(
            sparse_authority_mode
            if sparse_authority_mode is not None
            else params.get("sparse_authority_mode", "tuned_a3")
        )
        if self.sparse_authority_mode not in SEGMENT_SPARSE_AUTHORITY_MODES:
            raise PolicyAdapterError(
                "unsupported segment sparse authority mode: "
                f"{self.sparse_authority_mode!r}"
            )
        self.sparse_serving_rsrp_floor_dbm = float(
            sparse_serving_rsrp_floor_dbm
            if sparse_serving_rsrp_floor_dbm is not None
            else params.get("sparse_serving_rsrp_floor_dbm", -105.0)
        )
        self.sparse_serving_sinr_floor_db = float(
            sparse_serving_sinr_floor_db
            if sparse_serving_sinr_floor_db is not None
            else params.get("sparse_serving_sinr_floor_db", -5.0)
        )
        self.sparse_a3_extra_margin_db = max(
            0.0,
            float(
                sparse_a3_extra_margin_db
                if sparse_a3_extra_margin_db is not None
                else params.get("sparse_a3_extra_margin_db", 3.0)
            ),
        )
        self._replay_state_by_ue: Dict[str, Dict[str, Any]] = {}
        self._segment_state_by_ue: Dict[str, Dict[str, Any]] = {}
        self._guard_state_by_ue: Dict[str, Dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "ml_backend": "segment_controller",
            "segment_artifact": str(self.artifact.path),
            "segment_artifact_sha256": self.artifact.artifact_sha256,
            "model_family": self.artifact.model_family,
            "sparse_policy": None if self.sparse_policy is None else self.sparse_policy.name,
            "high_complexity_threshold": self.high_complexity_threshold,
            "entry_threshold": self.entry_threshold,
            "candidate_margin_min": self.candidate_margin_min,
            "exit_threshold": self.exit_threshold,
            "consecutive_exit_votes": self.consecutive_exit_votes,
            "min_segment_duration_s": self.min_segment_duration_s,
            "max_segment_duration_s": self.max_segment_duration_s,
            "emergency_rsrp_floor_dbm": self.emergency_rsrp_floor_dbm,
            "post_exit_a3_guard_s": self.post_exit_a3_guard_s,
            "post_exit_a3_extra_margin_db": self.post_exit_a3_extra_margin_db,
            "high_reject_hold_s": self.high_reject_hold_s,
            "sparse_authority_mode": self.sparse_authority_mode,
            "sparse_serving_rsrp_floor_dbm": self.sparse_serving_rsrp_floor_dbm,
            "sparse_serving_sinr_floor_db": self.sparse_serving_sinr_floor_db,
            "sparse_a3_extra_margin_db": self.sparse_a3_extra_margin_db,
        }

    def reset(self, ue_id: Optional[str] = None) -> None:
        if self.sparse_policy is not None:
            self.sparse_policy.reset(ue_id)
        if ue_id is None:
            self._replay_state_by_ue.clear()
            self._segment_state_by_ue.clear()
            self._guard_state_by_ue.clear()
        else:
            self._replay_state_by_ue.pop(ue_id, None)
            self._segment_state_by_ue.pop(ue_id, None)
            self._guard_state_by_ue.pop(ue_id, None)

    def set_replay_state(self, ue_id: str, state: Mapping[str, Any]) -> None:
        clean_state = dict(state)
        self._replay_state_by_ue[str(ue_id)] = clean_state
        if self.sparse_policy is not None:
            setter = getattr(self.sparse_policy, "set_replay_state", None)
            if callable(setter):
                setter(ue_id, clean_state)

    def warmup(self, record: MeasurementTraceRecord) -> None:
        """Prime local model inference without retaining replay state or latency."""
        candidate_rows = self._candidate_rows(record)
        candidate_scores = self.artifact.score_candidates(candidate_rows)
        selected_candidate = None
        best_score = None
        if candidate_scores:
            selected_candidate, best_score = max(
                candidate_scores.items(),
                key=lambda item: (item[1], item[0]),
            )
        entry_row = self._entry_row(
            record,
            candidate_rows=candidate_rows,
            candidate_scores=candidate_scores,
            selected_candidate=selected_candidate,
            best_score=best_score,
        )
        self.artifact.score_entry(entry_row)
        self.artifact.score_exit(
            self._exit_row(
                record,
                segment_state={
                    "segment_cell": selected_candidate or record.serving_cell,
                    "entry_serving_cell": record.serving_cell,
                    "entry_step_index": record.step_index,
                },
                age_s=self.min_segment_duration_s,
            )
        )

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        started = time.perf_counter()
        complexity = candidate_complexity_for_record(
            record,
            high_complexity_threshold=self.high_complexity_threshold,
        )
        segment_state = self._segment_state_by_ue.get(record.ue_id)
        if segment_state and segment_state.get("active") is True:
            return self._decide_active_segment(
                record,
                complexity=complexity,
                segment_state=segment_state,
                started=started,
            )

        if complexity.complexity_bucket != "high":
            high_reject_hold_debug = self._high_reject_hold_debug(record)
            if high_reject_hold_debug["high_reject_hold_applied"]:
                return self._stay_decision(
                    record,
                    complexity=complexity,
                    started=started,
                    decision_source="ml_segment_rejected_stay_hold",
                    reason=str(high_reject_hold_debug["high_reject_hold_reason"]),
                    segment_debug={
                        **self._base_segment_debug(
                            complexity=complexity,
                            segment_state=None,
                            entry_score=None,
                            candidate_scores={},
                            selected_candidate=None,
                            exit_score=None,
                            exit_reason="high_reject_hold_active",
                        ),
                        **high_reject_hold_debug,
                    },
                )
            if self.sparse_policy is None:
                return self._stay_decision(
                    record,
                    complexity=complexity,
                    started=started,
                    decision_source="ml_segment_rejected_stay",
                    reason="ml_only_inactive_non_high_complexity",
                    segment_debug=self._base_segment_debug(
                        complexity=complexity,
                        segment_state=None,
                        entry_score=None,
                        candidate_scores={},
                        selected_candidate=None,
                        exit_score=None,
                        exit_reason="inactive_non_high_complexity",
                    ),
                )
            decision = self.sparse_policy.decide(record)
            return self._wrap_sparse_decision_with_guards(
                record,
                decision,
                started=started,
                complexity=complexity,
                decision_source="a3_complexity_gate",
                delegated_policy=self.sparse_policy.name,
                segment_debug=self._base_segment_debug(
                    complexity=complexity,
                    segment_state=None,
                    entry_score=None,
                    candidate_scores={},
                    selected_candidate=None,
                    exit_score=None,
                    exit_reason="inactive_sparse_or_moderate",
                ),
            )

        candidate_rows = self._candidate_rows(record)
        candidate_scores = self.artifact.score_candidates(candidate_rows)
        selected_candidate = None
        best_score = None
        if candidate_scores:
            selected_candidate, best_score = max(
                candidate_scores.items(),
                key=lambda item: (item[1], item[0]),
            )
        entry_row = self._entry_row(
            record,
            candidate_rows=candidate_rows,
            candidate_scores=candidate_scores,
            selected_candidate=selected_candidate,
            best_score=best_score,
        )
        entry_score = self.artifact.score_entry(entry_row) if selected_candidate else 0.0
        margin = float(best_score or 0.0)
        approved = (
            selected_candidate is not None
            and entry_score >= self.entry_threshold
            and margin >= self.candidate_margin_min
        )
        segment_debug = self._base_segment_debug(
            complexity=complexity,
            segment_state=None,
            entry_score=entry_score,
            candidate_scores=candidate_scores,
            selected_candidate=selected_candidate,
            exit_score=None,
            exit_reason=None if approved else "entry_rejected",
        )
        segment_debug.update(
            {
                "ranker_stay_score": 0.0,
                "ranker_best_candidate_score": best_score,
                "ranker_margin_vs_stay": margin,
                "ranker_min_margin": self.candidate_margin_min,
            }
        )
        if not approved:
            self._record_high_reject(record)
            return self._stay_decision(
                record,
                complexity=complexity,
                started=started,
                decision_source="ml_segment_rejected_stay",
                reason="segment_entry_rejected",
                segment_debug=segment_debug,
            )

        if selected_candidate not in record.visible_cell_map or selected_candidate == record.serving_cell:
            raise PolicyAdapterError(
                f"segment controller selected invalid target {selected_candidate!r} "
                f"at step {record.step_index}"
            )
        new_segment_state = {
            "active": True,
            "entry_time_s": float(record.timestamp_s),
            "entry_step_index": int(record.step_index),
            "entry_serving_cell": record.serving_cell,
            "segment_cell": selected_candidate,
            "consecutive_exit_votes": 0,
            "last_exit_score": None,
            "last_age_s": 0.0,
        }
        self._segment_state_by_ue[record.ue_id] = new_segment_state
        segment_debug = self._base_segment_debug(
            complexity=complexity,
            segment_state=new_segment_state,
            entry_score=entry_score,
            candidate_scores=candidate_scores,
            selected_candidate=selected_candidate,
            exit_score=None,
            exit_reason="entry_approved",
        )
        segment_debug.update(
            {
                "ranker_stay_score": 0.0,
                "ranker_best_candidate_score": best_score,
                "ranker_margin_vs_stay": margin,
                "ranker_min_margin": self.candidate_margin_min,
            }
        )
        return self._handover_decision(
            record,
            complexity=complexity,
            started=started,
            selected_target=selected_candidate,
            decision_source="ml_segment_entry",
            reason="segment_entry_approved",
            segment_debug=segment_debug,
        )

    def _decide_active_segment(
        self,
        record: MeasurementTraceRecord,
        *,
        complexity: Any,
        segment_state: Dict[str, Any],
        started: float,
    ) -> PolicyDecisionRecord:
        age_s = max(0.0, float(record.timestamp_s) - float(segment_state["entry_time_s"]))
        segment_state["last_age_s"] = age_s
        serving = record.visible_cell_map.get(record.serving_cell)
        segment_cell = str(segment_state.get("segment_cell") or record.serving_cell)
        emergency = (
            serving is None
            or serving.rsrp_dbm <= self.emergency_rsrp_floor_dbm
        )
        if emergency:
            self._segment_state_by_ue.pop(record.ue_id, None)
            return self._exit_to_sparse_policy(
                record,
                complexity=complexity,
                started=started,
                decision_source="ml_segment_emergency_exit",
                segment_state=segment_state,
                exit_score=None,
                exit_reason="emergency_rsrp_floor_or_missing_serving",
            )

        exit_score = None
        exit_reason = None
        if age_s < self.min_segment_duration_s:
            segment_state["consecutive_exit_votes"] = 0
            exit_reason = "min_segment_duration_not_met"
        else:
            exit_row = self._exit_row(record, segment_state=segment_state, age_s=age_s)
            exit_score = self.artifact.score_exit(exit_row)
            if exit_score >= self.exit_threshold:
                segment_state["consecutive_exit_votes"] = int(
                    segment_state.get("consecutive_exit_votes", 0)
                ) + 1
                exit_reason = "exit_vote"
            else:
                segment_state["consecutive_exit_votes"] = 0
                exit_reason = "exit_threshold_not_met"
        segment_state["last_exit_score"] = exit_score

        should_exit = (
            age_s >= self.max_segment_duration_s
            or int(segment_state.get("consecutive_exit_votes", 0)) >= self.consecutive_exit_votes
        )
        if should_exit:
            self._segment_state_by_ue.pop(record.ue_id, None)
            return self._exit_to_sparse_policy(
                record,
                complexity=complexity,
                started=started,
                decision_source="ml_segment_exit_to_a3",
                segment_state=segment_state,
                exit_score=exit_score,
                exit_reason=(
                    "max_segment_duration"
                    if age_s >= self.max_segment_duration_s
                    else "consecutive_exit_votes"
                ),
            )

        return self._stay_decision(
            record,
            complexity=complexity,
            started=started,
            decision_source="ml_segment_hold",
            reason=f"segment_hold:{exit_reason}",
            segment_debug=self._base_segment_debug(
                complexity=complexity,
                segment_state=segment_state,
                entry_score=None,
                candidate_scores={},
                selected_candidate=segment_cell,
                exit_score=exit_score,
                exit_reason=exit_reason,
            ),
        )

    def _exit_to_sparse_policy(
        self,
        record: MeasurementTraceRecord,
        *,
        complexity: Any,
        started: float,
        decision_source: str,
        segment_state: Mapping[str, Any],
        exit_score: Optional[float],
        exit_reason: str,
    ) -> PolicyDecisionRecord:
        segment_debug = self._base_segment_debug(
            complexity=complexity,
            segment_state=segment_state,
            entry_score=None,
            candidate_scores={},
            selected_candidate=str(segment_state.get("segment_cell") or record.serving_cell),
            exit_score=exit_score,
            exit_reason=exit_reason,
        )
        self._record_segment_exit(record, segment_state)
        if self.sparse_policy is None:
            return self._stay_decision(
                record,
                complexity=complexity,
                started=started,
                decision_source=decision_source,
                reason=exit_reason,
                segment_debug=segment_debug,
            )
        decision = self.sparse_policy.decide(record)
        return self._wrap_sparse_decision_with_guards(
            record,
            decision,
            started=started,
            complexity=complexity,
            decision_source=decision_source,
            delegated_policy=self.sparse_policy.name,
            segment_debug=segment_debug,
        )

    def _wrap_sparse_decision_with_guards(
        self,
        record: MeasurementTraceRecord,
        decision: PolicyDecisionRecord,
        *,
        started: float,
        complexity: Any,
        decision_source: str,
        delegated_policy: str,
        segment_debug: Mapping[str, Any],
    ) -> PolicyDecisionRecord:
        authority_debug = self._sparse_authority_debug(record, decision)
        if authority_debug["sparse_authority_applied"]:
            return self._stay_decision(
                record,
                complexity=complexity,
                started=started,
                decision_source="sparse_authority_stay",
                reason=str(authority_debug["sparse_authority_reason"]),
                segment_debug={
                    **dict(segment_debug),
                    **authority_debug,
                },
            )
        guard_debug = self._post_exit_a3_guard_debug(record, decision)
        if guard_debug["post_segment_a3_guard_applied"]:
            return self._stay_decision(
                record,
                complexity=complexity,
                started=started,
                decision_source="ml_segment_rejected_stay_hold",
                reason=str(guard_debug["post_segment_a3_guard_reason"]),
                segment_debug={
                    **dict(segment_debug),
                    **guard_debug,
                },
            )
        return self._wrap_delegate_decision(
            decision,
            complexity=complexity,
            decision_source=decision_source,
            delegated_policy=delegated_policy,
            segment_debug={
                **dict(segment_debug),
                **authority_debug,
                **guard_debug,
            },
        )

    def _sparse_authority_debug(
        self,
        record: MeasurementTraceRecord,
        decision: PolicyDecisionRecord,
    ) -> Dict[str, Any]:
        serving = record.visible_cell_map[record.serving_cell]
        target_rsrp = (
            None
            if decision.selected_target_cell is None
            else decision.neighbour_measurements_considered.get(
                decision.selected_target_cell
            )
        )
        margin = (
            None
            if target_rsrp is None
            else float(target_rsrp - decision.serving_measurement_value)
        )
        rsrp_weak = serving.rsrp_dbm <= self.sparse_serving_rsrp_floor_dbm
        sinr_weak = (
            serving.sinr_db is not None
            and serving.sinr_db <= self.sparse_serving_sinr_floor_db
        )
        serving_weak = bool(rsrp_weak or sinr_weak)
        strong_gain = bool(
            margin is not None and margin >= self.sparse_a3_extra_margin_db
        )
        debug: Dict[str, Any] = {
            "sparse_authority_mode": self.sparse_authority_mode,
            "sparse_authority_applied": False,
            "sparse_authority_reason": None,
            "sparse_authority_handover_allowed": (
                decision.decision_type == "handover"
            ),
            "sparse_serving_rsrp_dbm": float(serving.rsrp_dbm),
            "sparse_serving_sinr_db": (
                None if serving.sinr_db is None else float(serving.sinr_db)
            ),
            "sparse_serving_rsrp_floor_dbm": self.sparse_serving_rsrp_floor_dbm,
            "sparse_serving_sinr_floor_db": self.sparse_serving_sinr_floor_db,
            "sparse_serving_weak": serving_weak,
            "sparse_a3_margin_db": margin,
            "sparse_a3_extra_margin_db": self.sparse_a3_extra_margin_db,
            "sparse_a3_strong_gain": strong_gain,
        }
        if decision.decision_type != "handover":
            debug["sparse_authority_reason"] = "a3_did_not_request_handover"
            debug["sparse_authority_handover_allowed"] = False
            return debug
        if self.sparse_authority_mode == "tuned_a3":
            debug["sparse_authority_reason"] = "tuned_a3_unrestricted"
            return debug
        if self.sparse_authority_mode == "quality_gated_a3":
            allowed = serving_weak or strong_gain
            reason = (
                "weak_serving_recovery"
                if serving_weak
                else "strong_a3_gain"
                if strong_gain
                else "healthy_serving_without_strong_gain"
            )
        else:
            allowed = serving_weak and strong_gain
            reason = (
                "weak_serving_with_strong_gain"
                if allowed
                else "serving_not_weak"
                if not serving_weak
                else "weak_serving_without_required_gain"
            )
        debug["sparse_authority_handover_allowed"] = bool(allowed)
        debug["sparse_authority_reason"] = reason
        debug["sparse_authority_applied"] = not allowed
        return debug

    def _record_segment_exit(
        self,
        record: MeasurementTraceRecord,
        segment_state: Mapping[str, Any],
    ) -> None:
        guard_state = self._guard_state_by_ue.setdefault(record.ue_id, {})
        guard_state["last_segment_exit_time_s"] = float(record.timestamp_s)
        guard_state["last_segment_cell"] = str(
            segment_state.get("segment_cell") or record.serving_cell
        )
        guard_state["last_segment_entry_serving_cell"] = str(
            segment_state.get("entry_serving_cell") or ""
        )

    def _record_high_reject(self, record: MeasurementTraceRecord) -> None:
        self._guard_state_by_ue.setdefault(record.ue_id, {})[
            "last_high_reject_time_s"
        ] = float(record.timestamp_s)

    def _guard_debug_base(self, ue_id: str) -> Dict[str, Any]:
        state = self._guard_state_by_ue.get(ue_id, {})
        return {
            "post_segment_a3_guard_applied": False,
            "post_segment_a3_guard_reason": None,
            "post_segment_a3_guard_s": self.post_exit_a3_guard_s,
            "post_segment_a3_extra_margin_db": self.post_exit_a3_extra_margin_db,
            "high_reject_hold_applied": False,
            "high_reject_hold_reason": None,
            "high_reject_hold_s": self.high_reject_hold_s,
            "last_segment_exit_time_s": state.get("last_segment_exit_time_s"),
            "last_high_reject_time_s": state.get("last_high_reject_time_s"),
        }

    def _high_reject_hold_debug(self, record: MeasurementTraceRecord) -> Dict[str, Any]:
        debug = self._guard_debug_base(record.ue_id)
        state = self._guard_state_by_ue.get(record.ue_id, {})
        last_reject = state.get("last_high_reject_time_s")
        if self.high_reject_hold_s <= 0.0 or last_reject is None:
            return debug
        elapsed = max(0.0, float(record.timestamp_s) - float(last_reject))
        if elapsed <= self.high_reject_hold_s:
            debug.update(
                {
                    "high_reject_hold_applied": True,
                    "high_reject_hold_reason": "recent_high_complexity_reject",
                    "high_reject_hold_elapsed_s": elapsed,
                }
            )
        return debug

    def _post_exit_a3_guard_debug(
        self,
        record: MeasurementTraceRecord,
        decision: PolicyDecisionRecord,
    ) -> Dict[str, Any]:
        debug = self._guard_debug_base(record.ue_id)
        state = self._guard_state_by_ue.get(record.ue_id, {})
        last_exit = state.get("last_segment_exit_time_s")
        if (
            self.post_exit_a3_guard_s <= 0.0
            or last_exit is None
            or decision.decision_type != "handover"
            or decision.selected_target_cell is None
        ):
            return debug
        elapsed = max(0.0, float(record.timestamp_s) - float(last_exit))
        if elapsed > self.post_exit_a3_guard_s:
            return debug
        target = decision.selected_target_cell
        target_rsrp = decision.neighbour_measurements_considered.get(target)
        margin = (
            None
            if target_rsrp is None
            else float(target_rsrp - decision.serving_measurement_value)
        )
        segment_cell = state.get("last_segment_cell")
        entry_serving = state.get("last_segment_entry_serving_cell")
        risky = (
            target == segment_cell
            or target == entry_serving
            or _same_site_sector(target, segment_cell)
            or _same_site_sector(target, entry_serving)
        )
        strong_enough = (
            margin is not None
            and margin >= self.post_exit_a3_extra_margin_db
        )
        if risky and not strong_enough:
            debug.update(
                {
                    "post_segment_a3_guard_applied": True,
                    "post_segment_a3_guard_reason": "risky_post_segment_a3_handover",
                    "post_segment_a3_guard_elapsed_s": elapsed,
                    "post_segment_a3_margin_db": margin,
                    "post_segment_a3_guard_target": target,
                }
            )
        return debug

    def _candidate_rows(self, record: MeasurementTraceRecord) -> list[dict[str, Any]]:
        state = self._replay_state_by_ue.get(record.ue_id, {})
        rows = build_candidate_ranker_features(
            record,
            recent_handover_count=_optional_int(
                state.get("recent_handover_count"),
                default=None,
            ),
            time_since_last_handover_s=_optional_float(
                state.get("time_since_last_handover_s"),
                default=None,
            ),
            current_dwell_time_s=_optional_float(
                state.get("current_dwell_time_s"),
                default=None,
            ),
            last_handover_source=(
                None
                if state.get("last_handover_source") is None
                else str(state.get("last_handover_source"))
            ),
            previous_serving_cell=(
                None
                if state.get("previous_serving_cell") is None
                else str(state.get("previous_serving_cell"))
            ),
            previous_target_cell=(
                None
                if state.get("previous_target_cell") is None
                else str(state.get("previous_target_cell"))
            ),
        )
        for row in rows:
            row["row_type"] = "candidate"
            row["snapshot_group"] = (
                f"{record.scenario}:{record.seed}:{record.ue_id}:{record.step_index}"
            )
            row["segment_group"] = f"{row['snapshot_group']}:candidate"
        return rows

    def _entry_row(
        self,
        record: MeasurementTraceRecord,
        *,
        candidate_rows: Sequence[Mapping[str, Any]],
        candidate_scores: Mapping[str, float],
        selected_candidate: Optional[str],
        best_score: Optional[float],
    ) -> dict[str, Any]:
        common = self._common_snapshot_features(record)
        selected_row: Mapping[str, Any] = {}
        if selected_candidate is not None:
            for row in candidate_rows:
                if str(row.get("candidate_cell")) == selected_candidate:
                    selected_row = row
                    break
        snapshot_group = f"{record.scenario}:{record.seed}:{record.ue_id}:{record.step_index}"
        return {
            **common,
            "row_type": "entry",
            "snapshot_group": snapshot_group,
            "segment_group": f"{snapshot_group}:entry",
            "best_candidate": selected_candidate,
            "best_candidate_margin": float(best_score or 0.0),
            "best_candidate_score": float(best_score or 0.0),
            "stay_score": 0.0,
            "best_candidate_delta_rsrp_db": _optional_float(
                selected_row.get("delta_rsrp_db"),
                default=0.0,
            ),
            "best_candidate_delta_sinr_db": _optional_float(
                selected_row.get("delta_sinr_db"),
                default=0.0,
            ),
            "best_candidate_load": _optional_float(
                selected_row.get("candidate_load"),
                default=0.0,
            ),
            "best_candidate_distance_m": _optional_float(
                selected_row.get("distance_to_candidate_m"),
                default=0.0,
            ),
            "best_candidate_moving_toward": _optional_float(
                selected_row.get("moving_toward_candidate"),
                default=0.0,
            ),
            "segment_horizon_steps": 20.0,
            "min_segment_duration_s": self.min_segment_duration_s,
            "max_segment_duration_s": self.max_segment_duration_s,
            "candidate_score_count": len(candidate_scores),
        }

    def _exit_row(
        self,
        record: MeasurementTraceRecord,
        *,
        segment_state: Mapping[str, Any],
        age_s: float,
    ) -> dict[str, Any]:
        selected_candidate = str(segment_state.get("segment_cell") or record.serving_cell)
        visible = record.visible_cell_map
        segment_cell = visible.get(selected_candidate)
        entry_serving = str(segment_state.get("entry_serving_cell") or "")
        original_serving = visible.get(entry_serving)
        best = max(
            [
                cell
                for cell in record.visible_cells
                if cell.cell_id not in {selected_candidate, record.serving_cell}
            ],
            key=lambda cell: (cell.rsrp_dbm, cell.cell_id),
            default=None,
        )
        segment_rsrp = segment_cell.rsrp_dbm if segment_cell is not None else -160.0
        best_rsrp = best.rsrp_dbm if best is not None else -160.0
        common = self._common_snapshot_features(record)
        snapshot_group = f"{record.scenario}:{record.seed}:{record.ue_id}:{record.step_index}"
        return {
            **common,
            "row_type": "exit",
            "snapshot_group": snapshot_group,
            "segment_group": (
                f"{record.scenario}:{record.seed}:{record.ue_id}:"
                f"{segment_state.get('entry_step_index', record.step_index)}:segment"
            ),
            "candidate_cell": selected_candidate,
            "segment_age_s": float(age_s),
            "segment_current_rsrp_dbm": float(segment_rsrp),
            "entry_serving_visible": float(original_serving is not None),
            "entry_serving_rsrp_dbm": (
                float(original_serving.rsrp_dbm) if original_serving is not None else -160.0
            ),
            "best_non_segment_rsrp_dbm": float(best_rsrp),
            "best_non_segment_margin_db": float(best_rsrp - segment_rsrp),
            "reverse_or_same_sector_risk": float(
                best is not None
                and (
                    best.cell_id == entry_serving
                    or _same_site_sector(best.cell_id, selected_candidate)
                )
            ),
            "sparse_reentry_penalty": 0.0,
        }

    def _common_snapshot_features(self, record: MeasurementTraceRecord) -> dict[str, Any]:
        visible = record.visible_cell_map
        serving = visible[record.serving_cell]
        complexity = candidate_complexity_for_record(
            record,
            high_complexity_threshold=self.high_complexity_threshold,
        )
        observed = record.observed_qos or {}
        state = self._replay_state_by_ue.get(record.ue_id, {})
        return {
            "scenario": record.scenario,
            "seed": record.seed,
            "topology_hash": record.topology_hash,
            "ue_id": record.ue_id,
            "step_index": record.step_index,
            "timestamp_s": record.timestamp_s,
            "serving_cell": record.serving_cell,
            "candidate_count": complexity.viable_candidate_count,
            "complexity_bucket": complexity.complexity_bucket,
            "serving_rsrp_dbm": float(serving.rsrp_dbm),
            "serving_sinr_db": 0.0 if serving.sinr_db is None else float(serving.sinr_db),
            "serving_rsrq_db": 0.0 if serving.rsrq_db is None else float(serving.rsrq_db),
            "serving_load": float(serving.load or 0.0),
            "speed_mps": float(record.speed_mps or 0.0),
            "signal_trend": 0.0,
            "recent_handover_count": _optional_int(
                state.get("recent_handover_count"),
                default=0,
            ),
            "time_since_last_handover_s": _optional_float(
                state.get("time_since_last_handover_s"),
                default=0.0,
            ),
            "latency_ms": _optional_float(observed.get("latency_ms"), default=0.0),
            "throughput_mbps": _optional_float(
                observed.get("throughput_mbps"),
                default=0.0,
            ),
            "packet_loss_rate": _optional_float(
                observed.get("packet_loss_rate"),
                default=0.0,
            ),
        }

    def _base_segment_debug(
        self,
        *,
        complexity: Any,
        segment_state: Optional[Mapping[str, Any]],
        entry_score: Optional[float],
        candidate_scores: Mapping[str, float],
        selected_candidate: Optional[str],
        exit_score: Optional[float],
        exit_reason: Optional[str],
    ) -> Dict[str, Any]:
        age = None
        if segment_state is not None and segment_state.get("entry_time_s") is not None:
            age = segment_state.get("last_age_s")
        return {
            "ml_backend": "segment_controller",
            "segment_state": (
                "active"
                if segment_state is not None and segment_state.get("active") is True
                else "inactive"
            ),
            "entry_score": entry_score,
            "entry_threshold": self.entry_threshold,
            "exit_score": exit_score,
            "exit_threshold": self.exit_threshold,
            "consecutive_exit_votes": int(
                0 if segment_state is None else segment_state.get("consecutive_exit_votes", 0)
            ),
            "required_consecutive_exit_votes": self.consecutive_exit_votes,
            "selected_candidate": selected_candidate,
            "candidate_scores": dict(candidate_scores),
            "segment_age_s": age,
            "segment_entry_serving_cell": (
                None if segment_state is None else segment_state.get("entry_serving_cell")
            ),
            "segment_current_serving_cell": (
                None if segment_state is None else segment_state.get("segment_cell")
            ),
            "segment_exit_reason": exit_reason,
            "segment_min_duration_s": self.min_segment_duration_s,
            "segment_max_duration_s": self.max_segment_duration_s,
            "sparse_authority_mode": self.sparse_authority_mode,
            "sparse_authority_applied": False,
            "sparse_authority_reason": None,
            "sparse_authority_handover_allowed": False,
            "sparse_serving_rsrp_dbm": None,
            "sparse_serving_sinr_db": None,
            "sparse_serving_rsrp_floor_dbm": self.sparse_serving_rsrp_floor_dbm,
            "sparse_serving_sinr_floor_db": self.sparse_serving_sinr_floor_db,
            "sparse_serving_weak": False,
            "sparse_a3_margin_db": None,
            "sparse_a3_extra_margin_db": self.sparse_a3_extra_margin_db,
            "sparse_a3_strong_gain": False,
            "segment_artifact_sha256": self.artifact.artifact_sha256,
            "segment_model_family": self.artifact.model_family,
            "segment_metadata": self.artifact.safe_metadata(),
            "candidate_complexity": complexity.to_dict(),
            "fallback_reason": None,
            "fallback_to_a3": False,
            "geographic_override": False,
            "synthetic_bootstrap": False,
            "model_not_ready": False,
            "model_ready": True,
            "qos_compliance": {},
            "raw_ml_response_metadata": {
                "ml_backend": "segment_controller",
                "segment_artifact_sha256": self.artifact.artifact_sha256,
                "model_ready": True,
            },
        }

    def _stay_decision(
        self,
        record: MeasurementTraceRecord,
        *,
        complexity: Any,
        started: float,
        decision_source: str,
        reason: str,
        segment_debug: Mapping[str, Any],
    ) -> PolicyDecisionRecord:
        serving = record.visible_cell_map[record.serving_cell]
        debug = {
            "decision_source": decision_source,
            "delegated_policy": "segment_controller",
            **self._guard_debug_base(record.ue_id),
            **dict(segment_debug),
            "candidate_complexity": complexity.to_dict(),
            "qos_compliance": _offline_qos_compliance(record),
            **_trace_debug_context(record),
        }
        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=None,
            decision_type="stay",
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm
                for cell in record.visible_cells
                if cell.cell_id != record.serving_cell
            },
            trigger_condition_result=False,
            time_to_trigger_state={},
            cooldown_state={},
            reason=f"{decision_source}:{reason}",
            debug=debug,
            decision_latency_ms=(time.perf_counter() - started) * 1000.0,
            confidence=None,
        )

    def _handover_decision(
        self,
        record: MeasurementTraceRecord,
        *,
        complexity: Any,
        started: float,
        selected_target: str,
        decision_source: str,
        reason: str,
        segment_debug: Mapping[str, Any],
    ) -> PolicyDecisionRecord:
        serving = record.visible_cell_map[record.serving_cell]
        debug = {
            "decision_source": decision_source,
            "delegated_policy": "segment_controller",
            **self._guard_debug_base(record.ue_id),
            **dict(segment_debug),
            "candidate_complexity": complexity.to_dict(),
            "qos_compliance": _offline_qos_compliance(record),
            **_trace_debug_context(record),
        }
        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=selected_target,
            decision_type="handover",
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm
                for cell in record.visible_cells
                if cell.cell_id != record.serving_cell
            },
            trigger_condition_result=True,
            time_to_trigger_state={},
            cooldown_state={},
            reason=f"{decision_source}:{reason}",
            debug=debug,
            decision_latency_ms=(time.perf_counter() - started) * 1000.0,
            confidence=None,
        )

    def _wrap_delegate_decision(
        self,
        decision: PolicyDecisionRecord,
        *,
        complexity: Any,
        decision_source: str,
        delegated_policy: str,
        segment_debug: Mapping[str, Any],
    ) -> PolicyDecisionRecord:
        debug = dict(decision.debug)
        debug.update(
            {
                "decision_source": decision_source,
                "delegated_policy": delegated_policy,
                "candidate_complexity": complexity.to_dict(),
                **self._guard_debug_base(decision.ue_id),
                **dict(segment_debug),
                "qos_compliance": _offline_qos_compliance_from_decision(decision),
            }
        )
        return replace(
            decision,
            policy_name=self.name,
            policy_parameters=self.parameters,
            reason=f"{decision_source}:{decision.reason}",
            debug=debug,
        )


class ComplexityAwarePolicyAdapter:
    """Route decisions by complexity, with explicit ML segment authority."""

    def __init__(
        self,
        *,
        sparse_policy: ComparisonPolicyAdapter,
        ml_policy: ComparisonPolicyAdapter,
        high_complexity_threshold: int = DEFAULT_HIGH_COMPLEXITY_THRESHOLD,
        min_rsrp_dbm: float = DEFAULT_MIN_VIABLE_RSRP_DBM,
        min_sinr_db: float = DEFAULT_MIN_VIABLE_SINR_DB,
        a3_reentry_extra_margin_db: float = DEFAULT_A3_REENTRY_EXTRA_MARGIN_DB,
        ml_segment_hold_s: float = DEFAULT_ML_SEGMENT_HOLD_S,
        ml_segment_emergency_rsrp_floor_dbm: float = -112.0,
    ) -> None:
        self.sparse_policy = sparse_policy
        self.ml_policy = ml_policy
        self.high_complexity_threshold = int(high_complexity_threshold)
        self.min_rsrp_dbm = float(min_rsrp_dbm)
        self.min_sinr_db = float(min_sinr_db)
        self.a3_reentry_extra_margin_db = float(a3_reentry_extra_margin_db)
        self.ml_segment_hold_s = max(0.0, float(ml_segment_hold_s))
        self.ml_segment_emergency_rsrp_floor_dbm = float(
            ml_segment_emergency_rsrp_floor_dbm
        )
        self._replay_state_by_ue: Dict[str, Dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "complexity_aware_ml_a3"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "sparse_policy": self.sparse_policy.name,
            "high_complexity_policy": self.ml_policy.name,
            "min_rsrp_dbm": self.min_rsrp_dbm,
            "min_sinr_db": self.min_sinr_db,
            "high_complexity_threshold": self.high_complexity_threshold,
            "a3_reentry_extra_margin_db": self.a3_reentry_extra_margin_db,
            "ml_segment_hold_s": self.ml_segment_hold_s,
            "ml_segment_emergency_rsrp_floor_dbm": self.ml_segment_emergency_rsrp_floor_dbm,
        }

    def reset(self, ue_id: Optional[str] = None) -> None:
        self.sparse_policy.reset(ue_id)
        self.ml_policy.reset(ue_id)
        if ue_id is None:
            self._replay_state_by_ue.clear()
        else:
            self._replay_state_by_ue.pop(ue_id, None)

    def set_replay_state(self, ue_id: str, state: Mapping[str, Any]) -> None:
        clean_state = dict(state)
        self._replay_state_by_ue[str(ue_id)] = clean_state
        for policy in (self.sparse_policy, self.ml_policy):
            setter = getattr(policy, "set_replay_state", None)
            if callable(setter):
                setter(ue_id, clean_state)

    def decide(self, record: MeasurementTraceRecord) -> PolicyDecisionRecord:
        started = time.perf_counter()
        complexity = candidate_complexity_for_record(
            record,
            min_rsrp_dbm=self.min_rsrp_dbm,
            min_sinr_db=self.min_sinr_db,
            high_complexity_threshold=self.high_complexity_threshold,
        )
        source, delegate, segment_debug = self._select_delegate(record, complexity)
        if delegate is None:
            return self._segment_stay_decision(
                record=record,
                complexity=complexity,
                source=source,
                segment_debug=segment_debug,
                started=started,
            )
        decision = delegate.decide(record)
        debug = dict(decision.debug)
        a3_reentry_guard = (
            delegate is self.sparse_policy
            and decision.decision_type == "handover"
            and decision.selected_target_cell is not None
            and self._should_apply_a3_reentry_guard(record, decision)
        )
        if a3_reentry_guard:
            decision = replace(
                decision,
                selected_target_cell=None,
                decision_type="stay",
                trigger_condition_result=False,
                reason=f"a3_reentry_guard:{decision.reason}",
            )
            debug = dict(decision.debug)
        debug.update(
            {
                "decision_source": source,
                "delegated_policy": delegate.name,
                "candidate_complexity": complexity.to_dict(),
                "a3_reentry_guard_applied": a3_reentry_guard,
                "a3_reentry_extra_margin_db": self.a3_reentry_extra_margin_db,
                **segment_debug,
            }
        )
        return replace(
            decision,
            policy_name=self.name,
            policy_parameters=self.parameters,
            reason=f"{debug['decision_source']}:{decision.reason}",
            debug=debug,
        )

    def _select_delegate(
        self,
        record: MeasurementTraceRecord,
        complexity: Any,
        ) -> tuple[str, Optional[ComparisonPolicyAdapter], Dict[str, Any]]:
        state = self._replay_state_by_ue.get(record.ue_id, {})
        time_since = _optional_float(
            state.get("time_since_last_handover_s"),
            default=None,
        )
        last_source = str(state.get("last_handover_source") or "")
        serving = record.visible_cell_map[record.serving_cell]
        last_was_ml = last_source in {
            "ml_high_complexity",
            "ml_segment_hold",
            "ml_segment_stay_hold",
            "candidate_ranker",
            "ml_policy",
        }
        within_hold = (
            self.ml_segment_hold_s > 0.0
            and last_was_ml
            and time_since is not None
            and time_since < self.ml_segment_hold_s
        )
        emergency_exit = (
            within_hold
            and serving.rsrp_dbm <= self.ml_segment_emergency_rsrp_floor_dbm
            and complexity.complexity_bucket != "high"
        )
        if complexity.complexity_bucket == "high":
            source = "ml_high_complexity"
            delegate = self.ml_policy
            active = True
            exit_reason = None
        elif within_hold and not emergency_exit:
            source = "ml_segment_stay_hold"
            delegate = None
            active = True
            exit_reason = None
        else:
            source = "a3_complexity_gate"
            delegate = self.sparse_policy
            active = False
            if emergency_exit:
                exit_reason = "emergency_rsrp_floor"
            elif last_was_ml and time_since is not None and self.ml_segment_hold_s > 0.0:
                exit_reason = "hold_elapsed"
            elif not last_was_ml:
                exit_reason = "no_recent_ml_handover"
            else:
                exit_reason = "inactive"
        segment_debug = {
            "ml_segment_active": active,
            "ml_segment_decision_source": source,
            "ml_segment_hold_s": self.ml_segment_hold_s,
            "ml_segment_emergency_rsrp_floor_dbm": self.ml_segment_emergency_rsrp_floor_dbm,
            "ml_segment_last_handover_source": last_source or None,
            "ml_segment_time_since_last_ml_handover_s": (
                time_since if last_was_ml else None
            ),
            "ml_segment_exit_reason": exit_reason,
        }
        return source, delegate, segment_debug

    def _segment_stay_decision(
        self,
        *,
        record: MeasurementTraceRecord,
        complexity: Any,
        source: str,
        segment_debug: Mapping[str, Any],
        started: float,
    ) -> PolicyDecisionRecord:
        serving = record.visible_cell_map[record.serving_cell]
        neighbours = {
            cell.cell_id: cell.rsrp_dbm
            for cell in record.visible_cells
            if cell.cell_id != record.serving_cell
        }
        debug = {
            "decision_source": source,
            "delegated_policy": "controller_segment_hold",
            "candidate_complexity": complexity.to_dict(),
            "a3_reentry_guard_applied": False,
            "a3_reentry_extra_margin_db": self.a3_reentry_extra_margin_db,
            **dict(segment_debug),
            **_trace_debug_context(record),
        }
        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=None,
            decision_type="stay",
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered=neighbours,
            trigger_condition_result=False,
            time_to_trigger_state={},
            cooldown_state={},
            reason=f"{source}:hold_current_ml_segment",
            debug=debug,
            decision_latency_ms=(time.perf_counter() - started) * 1000.0,
            confidence=None,
        )

    def _should_apply_a3_reentry_guard(
        self,
        record: MeasurementTraceRecord,
        decision: PolicyDecisionRecord,
    ) -> bool:
        state = self._replay_state_by_ue.get(record.ue_id, {})
        last_source = str(state.get("last_handover_source") or "")
        if last_source not in {"ml_high_complexity", "candidate_ranker", "ml_policy"}:
            return False
        target = decision.selected_target_cell
        if target is None:
            return False
        previous_serving = (
            None
            if state.get("previous_serving_cell") is None
            else str(state.get("previous_serving_cell"))
        )
        previous_target = (
            None
            if state.get("previous_target_cell") is None
            else str(state.get("previous_target_cell"))
        )
        reverse_or_near = (
            target == previous_serving
            or _same_site_sector(target, previous_target)
            or _same_site_sector(target, record.serving_cell)
        )
        if not reverse_or_near:
            return False
        target_rsrp = decision.neighbour_measurements_considered.get(target)
        if target_rsrp is None:
            return True
        margin = float(target_rsrp - decision.serving_measurement_value)
        return margin < self.a3_reentry_extra_margin_db


def trace_record_to_ml_payload(record: MeasurementTraceRecord) -> Dict[str, Any]:
    """Build the payload shape accepted by the existing ML service."""
    rf_metrics = {}
    for cell in record.visible_cells:
        metrics: Dict[str, float] = {"rsrp": cell.rsrp_dbm}
        if cell.sinr_db is not None:
            metrics["sinr"] = cell.sinr_db
        if cell.rsrq_db is not None:
            metrics["rsrq"] = cell.rsrq_db
        if cell.load is not None:
            metrics["cell_load"] = cell.load
        rf_metrics[cell.cell_id] = metrics

    payload: Dict[str, Any] = {
        "ue_id": record.ue_id,
        "latitude": record.ue_position["latitude"],
        "longitude": record.ue_position["longitude"],
        "speed": record.speed_mps,
        "direction": [0.0, 0.0, 0.0],
        "connected_to": record.serving_cell,
        "rf_metrics": rf_metrics,
        "service_type": record.service_type or "default",
        "service_priority": _service_priority(record.service_type),
    }
    if "altitude" in record.ue_position:
        payload["altitude"] = record.ue_position["altitude"]
    ml_features = record.metadata.get("ml_features")
    if isinstance(ml_features, Mapping):
        for key in ML_TRACE_PASSTHROUGH_FIELDS:
            if ml_features.get(key) is not None:
                payload[key] = ml_features[key]
    if record.qos_requirements is not None:
        payload["qos_requirements"] = record.qos_requirements
    if record.observed_qos is not None:
        observed_qos = {
            key: record.observed_qos[key]
            for key in (
                "latency_ms",
                "jitter_ms",
                "throughput_mbps",
                "packet_loss_rate",
            )
            if key in record.observed_qos
        }
        if observed_qos:
            payload["observed_qos"] = observed_qos
    return {key: value for key, value in payload.items() if value is not None}


def _resolve_ml_target_to_visible(
    raw_target: Any,
    record: MeasurementTraceRecord,
) -> tuple[Optional[str], Dict[str, Any]]:
    if raw_target is None:
        return None, {"raw_target": None, "resolved_target": None, "method": "none"}

    target = str(raw_target)
    visible = record.visible_cell_map
    if target in visible:
        return target, {
            "raw_target": target,
            "resolved_target": target,
            "method": "direct",
        }

    lowered = target.lower()
    if lowered.startswith("antenna"):
        digits = "".join(ch for ch in target if ch.isdigit())
        if digits and digits in visible:
            return digits, {
                "raw_target": target,
                "resolved_target": digits,
                "method": "nef_antenna_digit_alias",
            }

    raise PolicyAdapterError(
        f"ML selected target {target!r}, but it is not visible in trace step "
        f"{record.step_index} for UE {record.ue_id}"
    )


def _trace_debug_context(record: MeasurementTraceRecord) -> Dict[str, Any]:
    visible_loads = {
        cell.cell_id: cell.load
        for cell in record.visible_cells
        if cell.load is not None
    }
    visible_sinrs = {
        cell.cell_id: cell.sinr_db
        for cell in record.visible_cells
        if cell.sinr_db is not None
    }
    context: Dict[str, Any] = {}
    if visible_loads:
        context["cell_loads"] = visible_loads
        context["serving_cell_load"] = visible_loads.get(record.serving_cell)
    if visible_sinrs:
        context["cell_sinrs"] = visible_sinrs
        context["serving_cell_sinr_db"] = visible_sinrs.get(record.serving_cell)
    if record.service_type is not None:
        context["service_type"] = record.service_type
    if record.qos_requirements is not None:
        context["qos_requirements"] = record.qos_requirements
    if record.observed_qos is not None:
        context["observed_qos"] = record.observed_qos
    return context


def _cell_metric(cell: Any, metric: str) -> Optional[float]:
    if metric == "rsrp":
        return float(cell.rsrp_dbm)
    if metric == "sinr":
        return None if cell.sinr_db is None else float(cell.sinr_db)
    if metric == "rsrq":
        return None if cell.rsrq_db is None else float(cell.rsrq_db)
    raise PolicyAdapterError(f"unsupported metric: {metric}")


def _load_adjusted_rsrp(cell: Any, load_penalty_db: float) -> float:
    load = 0.0 if cell.load is None else max(0.0, float(cell.load))
    return float(cell.rsrp_dbm) - load_penalty_db * load


def _speed_tier(speed_mps: Optional[float]) -> str:
    speed = float(speed_mps or 0.0)
    if speed <= 5.0:
        return "low"
    if speed <= 25.0:
        return "medium"
    return "high"


def _safe_ml_response_metadata(response_data: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = {
        "fallback_reason",
        "fallback_to_a3",
        "ml_prediction",
        "raw_ml_prediction",
        "distance_to_ml_prediction",
        "distance_to_fallback",
        "geographic_override",
        "anti_pingpong_applied",
        "suppression_reason",
        "original_prediction",
        "qos_bias_applied",
        "qos_bias_service_type",
        "qos_bias_scores",
        "confidence_calibrated",
        "warnings",
        "handover_count_1min",
        "time_since_last_handover",
    }
    return {key: response_data[key] for key in allowed if key in response_data}


def _offline_qos_compliance(record: MeasurementTraceRecord) -> Dict[str, Any]:
    requirements = record.qos_requirements or {}
    observed = record.observed_qos or {}
    violations: list[str] = []
    if not requirements and not observed:
        return {
            "evaluated": False,
            "service_priority_ok": True,
            "violations": [],
        }

    latency_requirement = requirements.get("latency_requirement_ms")
    observed_latency = observed.get("latency_ms")
    if (
        latency_requirement is not None
        and observed_latency is not None
        and float(observed_latency) > float(latency_requirement)
    ):
        violations.append("latency_ms")

    throughput_requirement = requirements.get("throughput_requirement_mbps")
    observed_throughput = observed.get("throughput_mbps")
    if (
        throughput_requirement is not None
        and observed_throughput is not None
        and float(observed_throughput) < float(throughput_requirement)
    ):
        violations.append("throughput_mbps")

    jitter_requirement = requirements.get("jitter_ms")
    observed_jitter = observed.get("jitter_ms")
    if (
        jitter_requirement is not None
        and observed_jitter is not None
        and float(observed_jitter) > float(jitter_requirement)
    ):
        violations.append("jitter_ms")

    reliability_requirement = requirements.get("reliability_pct")
    observed_loss = observed.get("packet_loss_rate")
    if reliability_requirement is not None and observed_loss is not None:
        observed_reliability = max(0.0, 100.0 - float(observed_loss))
        if observed_reliability < float(reliability_requirement):
            violations.append("reliability_pct")

    return {
        "evaluated": True,
        "service_priority_ok": not violations,
        "violations": violations,
    }


def _offline_qos_compliance_from_decision(
    decision: PolicyDecisionRecord,
) -> Dict[str, Any]:
    raw = decision.debug.get("qos_compliance")
    if isinstance(raw, Mapping):
        return dict(raw)
    return {
        "evaluated": False,
        "service_priority_ok": True,
        "violations": [],
    }


def _raise_on_hidden_ml_fallback(response_data: Mapping[str, Any]) -> None:
    fallback_reason = response_data.get("fallback_reason")
    if fallback_reason:
        raise PolicyAdapterError(
            "ML response contained fallback/override metadata in strict replay: "
            f"{fallback_reason}"
        )
    if response_data.get("fallback_to_a3") is True:
        raise PolicyAdapterError("ML response indicated fallback_to_a3 in strict replay")
    if response_data.get("geographic_override") is True:
        raise PolicyAdapterError("ML response indicated geographic_override in strict replay")
    if response_data.get("synthetic_bootstrap") is True:
        raise PolicyAdapterError("ML response indicated synthetic_bootstrap in strict replay")
    if response_data.get("model_not_ready") is True or response_data.get("model_ready") is False:
        raise PolicyAdapterError("ML response indicated model-not-ready behavior in strict replay")


def _from_baseline_decision(
    decision: Any,
    *,
    latency_ms: float,
    source_record: Optional[MeasurementTraceRecord] = None,
) -> PolicyDecisionRecord:
    payload = decision.to_dict()
    debug = dict(payload.get("debug") or {})
    if source_record is not None:
        debug.update(_trace_debug_context(source_record))
        debug["candidate_complexity"] = candidate_complexity_for_record(source_record).to_dict()
    return PolicyDecisionRecord(
        ue_id=str(payload["ue_id"]),
        timestamp_s=float(payload["timestamp_s"]),
        step_index=int(payload["step_index"] if payload["step_index"] is not None else 0),
        current_serving_cell=str(payload["current_serving_cell"]),
        selected_target_cell=payload["selected_target_cell"],
        decision_type=payload["decision_type"],
        policy_name=str(payload["policy_name"]),
        policy_parameters=dict(payload["policy_parameters"]),
        serving_measurement_value=float(payload["serving_measurement_value"]),
        neighbour_measurements_considered={
            str(k): float(v)
            for k, v in payload["neighbour_measurements_considered"].items()
        },
        trigger_condition_result=bool(payload["trigger_condition_result"]),
        time_to_trigger_state=dict(payload["time_to_trigger_state"]),
        cooldown_state=dict(payload["cooldown_state"]),
        reason=str(payload["reason"]),
        debug=debug,
        decision_latency_ms=latency_ms,
        confidence=payload.get("confidence"),
    )


def _optional_float(value: Any, *, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any, *, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _same_site_sector(
    cell_a: Optional[str],
    cell_b: Optional[str],
    *,
    sectors_per_site: int = 4,
) -> bool:
    if cell_a is None or cell_b is None:
        return False
    try:
        a = int(str(cell_a))
        b = int(str(cell_b))
    except (TypeError, ValueError):
        return False
    if a == b or a <= 0 or b <= 0:
        return False
    return (a - 1) // sectors_per_site == (b - 1) // sectors_per_site


def _service_priority(service_type: Optional[str]) -> int:
    normalized = (service_type or "default").lower()
    if normalized == "urllc":
        return 9
    if normalized == "embb":
        return 5
    if normalized == "mmtc":
        return 3
    return 5
