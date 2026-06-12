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
)
from .candidate_ranker import build_candidate_ranker_features
from .candidate_ranker_artifact import (
    CandidateRankerArtifact,
    DEFAULT_A3_REENTRY_EXTRA_MARGIN_DB,
    DEFAULT_RANKER_MIN_MARGIN,
    DEFAULT_RANKER_MIN_ML_DWELL_S,
    load_candidate_ranker_artifact,
)
from .nef_trace import ML_TRACE_PASSTHROUGH_FIELDS
from .schemas import MeasurementTraceRecord, PolicyDecisionRecord, TraceSchemaError


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


class ComplexityAwarePolicyAdapter:
    """Route sparse/moderate decisions to A3 and high-complexity decisions to ML."""

    def __init__(
        self,
        *,
        sparse_policy: ComparisonPolicyAdapter,
        ml_policy: ComparisonPolicyAdapter,
        high_complexity_threshold: int = DEFAULT_HIGH_COMPLEXITY_THRESHOLD,
        min_rsrp_dbm: float = DEFAULT_MIN_VIABLE_RSRP_DBM,
        min_sinr_db: float = DEFAULT_MIN_VIABLE_SINR_DB,
        a3_reentry_extra_margin_db: float = DEFAULT_A3_REENTRY_EXTRA_MARGIN_DB,
    ) -> None:
        self.sparse_policy = sparse_policy
        self.ml_policy = ml_policy
        self.high_complexity_threshold = int(high_complexity_threshold)
        self.min_rsrp_dbm = float(min_rsrp_dbm)
        self.min_sinr_db = float(min_sinr_db)
        self.a3_reentry_extra_margin_db = float(a3_reentry_extra_margin_db)
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
        complexity = candidate_complexity_for_record(
            record,
            min_rsrp_dbm=self.min_rsrp_dbm,
            min_sinr_db=self.min_sinr_db,
            high_complexity_threshold=self.high_complexity_threshold,
        )
        delegate = (
            self.ml_policy
            if complexity.complexity_bucket == "high"
            else self.sparse_policy
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
                "decision_source": (
                    "ml_high_complexity"
                    if delegate is self.ml_policy
                    else "a3_complexity_gate"
                ),
                "delegated_policy": delegate.name,
                "candidate_complexity": complexity.to_dict(),
                "a3_reentry_guard_applied": a3_reentry_guard,
                "a3_reentry_extra_margin_db": self.a3_reentry_extra_margin_db,
            }
        )
        return replace(
            decision,
            policy_name=self.name,
            policy_parameters=self.parameters,
            reason=f"{debug['decision_source']}:{decision.reason}",
            debug=debug,
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
    context: Dict[str, Any] = {}
    if visible_loads:
        context["cell_loads"] = visible_loads
        context["serving_cell_load"] = visible_loads.get(record.serving_cell)
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
