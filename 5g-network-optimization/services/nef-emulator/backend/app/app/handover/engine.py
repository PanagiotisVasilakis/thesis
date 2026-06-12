from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import logging
import requests
from jose import jwt
from requests import RequestException

from ..core.env_utils import parse_env_float, parse_env_int, parse_env_bool
from ..monitoring import metrics

from ..network.state_manager import NetworkStateManager
from .a3_rule import A3EventRule
from .baseline_policy import BASELINE_HANDOVER_MODES, BaselinePolicyManager


TRACE_CAPTURE_MODE = "trace_capture"
COMPLEXITY_AWARE_MODE = "complexity_aware_ml_a3"
TUNED_A3_BASELINE_MODE = "tuned_a3_baseline"
DEFAULT_MIN_VIABLE_RSRP_DBM = -115.0
DEFAULT_MIN_VIABLE_SINR_DB = -5.0
DEFAULT_HIGH_COMPLEXITY_THRESHOLD = 3

_FALLBACK_CELL_CONFIGS = {
    "antenna_1": {"latitude": 0.0, "longitude": 0.0},
    "antenna_2": {"latitude": 1000.0, "longitude": 0.0},
    "antenna_3": {"latitude": 0.0, "longitude": 866.0},
    "antenna_4": {"latitude": 1000.0, "longitude": 866.0},
}

_ML_PAYLOAD_PASSTHROUGH_FIELDS = (
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
    "angle_to_target",
    "relative_distance_ratio",
    "moving_toward_target",
    "service_type",
    "service_priority",
    "qos_requirements",
    "latency_requirement_ms",
    "throughput_requirement_mbps",
    "reliability_pct",
    "jitter_ms",
)

_OBSERVED_QOS_KEYS = (
    "latency_ms",
    "jitter_ms",
    "throughput_mbps",
    "packet_loss_rate",
)

_ML_RESPONSE_METADATA_FIELDS = (
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
)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute distance in meters without depending on the ML service package."""
    radius_m = 6_371_000.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return radius_m * c


def _filtered_observed_qos(value: Any) -> dict[str, float]:
    """Return the latest QoS metrics in the shape accepted by ml-service."""
    if not isinstance(value, dict):
        return {}
    latest = value.get("latest") if isinstance(value.get("latest"), dict) else value
    if not isinstance(latest, dict):
        return {}
    return {
        key: latest[key]
        for key in _OBSERVED_QOS_KEYS
        if latest.get(key) is not None
    }


def _candidate_complexity_for_feature_vector(
    fv: dict,
    *,
    high_complexity_threshold: int = DEFAULT_HIGH_COMPLEXITY_THRESHOLD,
    min_rsrp_dbm: float = DEFAULT_MIN_VIABLE_RSRP_DBM,
    min_sinr_db: float = DEFAULT_MIN_VIABLE_SINR_DB,
) -> dict[str, Any]:
    rsrp_map = fv.get("neighbor_rsrp_dbm") or {}
    sinr_map = fv.get("neighbor_sinrs") or {}
    serving = str(fv.get("connected_to") or "")
    candidates: list[str] = []

    if not isinstance(rsrp_map, dict):
        rsrp_map = {}
    if not isinstance(sinr_map, dict):
        sinr_map = {}

    for raw_cell_id, raw_rsrp in rsrp_map.items():
        cell_id = str(raw_cell_id)
        if cell_id == serving:
            continue
        try:
            rsrp = float(raw_rsrp)
        except (TypeError, ValueError):
            continue
        raw_sinr = sinr_map.get(raw_cell_id, sinr_map.get(cell_id))
        try:
            sinr = None if raw_sinr is None else float(raw_sinr)
        except (TypeError, ValueError):
            sinr = None
        if rsrp >= min_rsrp_dbm and (sinr is None or sinr >= min_sinr_db):
            candidates.append(cell_id)

    count = len(candidates)
    if count <= 1:
        bucket = "sparse"
    elif count < high_complexity_threshold:
        bucket = "moderate"
    else:
        bucket = "high"
    return {
        "viable_candidate_count": count,
        "complexity_bucket": bucket,
        "viable_candidates": candidates,
        "thresholds": {
            "min_rsrp_dbm": float(min_rsrp_dbm),
            "min_sinr_db": float(min_sinr_db),
            "high_complexity_threshold": float(high_complexity_threshold),
        },
    }


def _ml_result_from_response(data: dict, *, source: str) -> dict[str, Any]:
    antenna_id = data.get("predicted_antenna") or data.get("antenna_id")
    result = {
        "antenna_id": antenna_id,
        "confidence": data.get("confidence"),
        "qos_compliance": data.get("qos_compliance"),
        "source": source,
        "raw_ml_prediction": data.get("ml_prediction") or antenna_id,
    }
    for field in _ML_RESPONSE_METADATA_FIELDS:
        if field in data:
            result[field] = data[field]
    return result


def _get_cell_configs() -> dict:
    try:
        from ml_service.app.config.cells import CELL_CONFIGS

        return CELL_CONFIGS
    except Exception:
        return _FALLBACK_CELL_CONFIGS


def _cell_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if max(abs(lat1), abs(lat2)) > 90.0 or max(abs(lon1), abs(lon2)) > 180.0:
        return math.hypot(lat2 - lat1, lon2 - lon1)
    return haversine_distance(lat1, lon1, lat2, lon2)


class HandoverEngine:
    """Decide and apply handovers using the A3 rule or an external
    ML service."""

    # HTTP request timeout (seconds) for ML service calls
    HTTP_TIMEOUT_SECONDS = 5
    # Shorter timeout for non-critical feedback calls
    HTTP_FEEDBACK_TIMEOUT_SECONDS = 3
    # Default token expiry fallback (seconds)
    DEFAULT_TOKEN_EXPIRY_SECONDS = 300
    # Coverage margin factor (1.5x = allow 50% beyond cell radius)
    COVERAGE_MARGIN_FACTOR = 1.5

    def __init__(
        self,
        state_mgr: NetworkStateManager,
        use_ml: Optional[bool] = None,
        ml_model_path: Optional[str] = None,
        *,
        use_local_ml: bool = False,
        ml_service_url: Optional[str] = None,
        min_antennas_ml: int = 3,
        a3_hysteresis_db: float = 2.0,
        a3_ttt_s: float = 0.0,
        confidence_threshold: float = 0.5,
        clock=None,
    ) -> None:
        self.state_mgr = state_mgr
        candidate_logger = getattr(state_mgr, "logger", None)
        self.logger = (
            candidate_logger
            if isinstance(candidate_logger, logging.Logger)
            else logging.getLogger("HandoverEngine")
        )
        self.ml_model_path = ml_model_path
        self.ml_service_url = ml_service_url or os.getenv(
            "ML_SERVICE_URL", "http://ml-service:5050"
        )
        
        # Parse env vars using helpers for consistent error handling
        self.min_antennas_ml = parse_env_int("MIN_ANTENNAS_ML", min_antennas_ml, min_value=1)
        default_complexity_threshold = parse_env_int(
            "MIN_COMPLEXITY_ML_CANDIDATES",
            DEFAULT_HIGH_COMPLEXITY_THRESHOLD,
            min_value=1,
        )
        self.high_complexity_threshold = parse_env_int(
            "COMPLEXITY_ML_CANDIDATE_THRESHOLD",
            default_complexity_threshold,
            min_value=1,
        )
        self.confidence_threshold = parse_env_float(
            "ML_CONFIDENCE_THRESHOLD", confidence_threshold, min_value=0.0, max_value=1.0
        )
        self.use_local_ml = parse_env_bool("ML_LOCAL", use_local_ml)
        
        self.model = None
        if self.use_local_ml:
            try:
                from ml_service.app.api_lib import load_model
                self.model = load_model(self.ml_model_path)
            except Exception:
                self.model = None
        
        a3_hysteresis_db = parse_env_float("A3_HYSTERESIS_DB", a3_hysteresis_db)
        a3_ttt_s = parse_env_float("A3_TTT_S", a3_ttt_s, min_value=0.0)

        self._a3_params = (a3_hysteresis_db, a3_ttt_s)
        # Per-UE, per-target TTT timers: {ue_id: {target_antenna_id: event_start_time}}
        # This ensures independent TTT tracking for each UE-target pair
        self._ttt_timers: dict[str, dict[str, datetime]] = {}
        # Always have an A3 rule available; it will only be used when
        # machine learning is disabled.
        self.rule = A3EventRule(
            hysteresis_db=self._a3_params[0], 
            ttt_seconds=self._a3_params[1],
            event_type="rsrp_based"  # Default to RSRP-based for backward compatibility
        )
        self._baseline_policy_manager = BaselinePolicyManager()

        env = os.getenv("ML_HANDOVER_ENABLED") if use_ml is None else None

        if use_ml is not None:
            self.use_ml = bool(use_ml)
            self._auto = False
        elif env is not None:
            self.use_ml = env.lower() in {"1", "true", "yes"}
            self._auto = False
        else:
            self._auto = True
            self.use_ml = len(state_mgr.antenna_list) >= self.min_antennas_ml

        # Handover mode: "ml" (pure), "a3" (pure), "hybrid" (ML with
        # A3 fallback), "complexity_aware_ml_a3", or explicit baseline-service
        # A3 policy modes.
        # Default to "hybrid" for backward compatibility with existing behavior
        self.handover_mode = "hybrid" if self.use_ml else "a3"

        # --- ML service authentication ---
        self._ml_username = (
            os.getenv("ML_SERVICE_USERNAME")
            or os.getenv("ML_AUTH_USERNAME")
            or os.getenv("ML_SERVICE_USER")
        )
        self._ml_password = (
            os.getenv("ML_SERVICE_PASSWORD")
            or os.getenv("ML_AUTH_PASSWORD")
            or os.getenv("ML_SERVICE_PASS")
        )
        self._ml_access_token: Optional[str] = None
        self._ml_refresh_token: Optional[str] = None
        self._ml_token_expiry: float = 0.0
        self._ml_auth_lock = threading.Lock()
        self._ml_credentials_warned = False
        
        # Timeouts and configuration - using env_utils for clean parsing
        self._token_refresh_skew = parse_env_float("ML_TOKEN_REFRESH_SKEW", 15.0)
        self.http_timeout = parse_env_float("ML_HTTP_TIMEOUT", float(self.HTTP_TIMEOUT_SECONDS))
        self.feedback_timeout = parse_env_float("ML_FEEDBACK_TIMEOUT", float(self.HTTP_FEEDBACK_TIMEOUT_SECONDS))
        self.token_expiry_fallback = parse_env_float("ML_TOKEN_EXPIRY_SECONDS", float(self.DEFAULT_TOKEN_EXPIRY_SECONDS))
        self.coverage_margin_factor = parse_env_float("COVERAGE_MARGIN_FACTOR", float(self.COVERAGE_MARGIN_FACTOR))
        self._last_ml_error_reason: Optional[str] = None
        self._last_ml_http_status: Optional[int] = None
        self._clock = clock

    def _now(self) -> datetime:
        if self._clock is not None:
            return self._clock()
        return datetime.now(timezone.utc)

    def _update_mode(self) -> None:
        """Update handover mode automatically based on antenna count."""
        if self._auto:
            want_ml = len(self.state_mgr.antenna_list) >= self.min_antennas_ml
            if want_ml != self.use_ml:
                self.use_ml = want_ml
                # Sync handover_mode to match the auto-detected state
                self.handover_mode = "hybrid" if want_ml else "a3"

    # ------------------------------------------------------------------

    def _select_ml(self, ue_id: str) -> Optional[dict]:
        """Make ML prediction for the given UE.
        
        This method fetches the feature vector from state_manager and delegates
        to _select_ml_with_features for the actual ML prediction logic.
        """
        fv = self.state_mgr.get_feature_vector(ue_id)
        return self._select_ml_with_features(ue_id, fv)

    def _select_rule(self, ue_id: str) -> Optional[str]:
        fv = self.state_mgr.get_feature_vector(ue_id)
        return self._select_rule_with_features(ue_id, fv)

    # ------------------------------------------------------------------
    # Lock-free decision methods (for use with pre-computed feature vectors)
    # ------------------------------------------------------------------
    
    def decide_with_features(self, ue_id: str, fv: dict) -> Optional[dict]:
        """Make ML/A3 decision using pre-computed feature vector.
        
        This method is designed to be called WITHOUT holding the runtime lock,
        as it makes HTTP calls to the ML service that can take 5+ seconds.
        
        Args:
            ue_id: UE identifier
            fv: Pre-computed feature vector from get_feature_vector()
            
        Returns:
            Decision dict with 'antenna_id' and metadata, or None
        """
        self._update_mode()
        current_mode = getattr(self, "handover_mode", "hybrid" if self.use_ml else "a3")

        if current_mode == TRACE_CAPTURE_MODE:
            return None

        if current_mode == COMPLEXITY_AWARE_MODE:
            complexity = _candidate_complexity_for_feature_vector(
                fv,
                high_complexity_threshold=self.high_complexity_threshold,
            )
            if complexity["complexity_bucket"] == "high":
                result = self._select_ml_with_features(ue_id, fv)
                if result is None:
                    return None
                result.setdefault("source", "ml_remote")
                result["fallback_to_a3"] = False
                result["decision_source"] = "ml_high_complexity"
                result["delegated_policy"] = "ml_policy"
                result["candidate_complexity"] = complexity
                return result

            decision = self._select_baseline_with_features(
                ue_id,
                fv,
                TUNED_A3_BASELINE_MODE,
                self._now(),
            )
            decision["decision_source"] = "a3_complexity_gate"
            decision["delegated_policy"] = TUNED_A3_BASELINE_MODE
            decision["candidate_complexity"] = complexity
            if decision.get("antenna_id"):
                return decision
            return None

        if current_mode in BASELINE_HANDOVER_MODES:
            decision = self._select_baseline_with_features(
                ue_id,
                fv,
                current_mode,
                self._now(),
            )
            if decision.get("antenna_id"):
                return decision
            return None

        if current_mode == "a3":
            target = self._select_rule_with_features(ue_id, fv)
            if target:
                return {
                    "antenna_id": target,
                    "source": "a3_rule",
                    "fallback_to_a3": False,
                }
            return None

        result = self._select_ml_with_features(ue_id, fv)
        if result is None:
            if current_mode == "ml":
                return None

            fallback_reason = self._last_ml_error_reason or "ml_service_unavailable"
            target = self._select_rule_with_features(ue_id, fv)
            self._record_fallback_metrics(None, fallback_reason)
            metrics.HANDOVER_FALLBACKS.inc()
            if target:
                return {
                    "antenna_id": target,
                    "source": "a3_fallback",
                    "fallback_to_a3": True,
                    "fallback_reason": fallback_reason,
                }
            return None

        result.setdefault("source", "ml_remote")
        result["fallback_to_a3"] = False

        if current_mode != "hybrid":
            return result

        confidence = result.get("confidence")
        if confidence is None:
            confidence = 0.0

        qos_comp = result.get("qos_compliance")
        fallback_reason = None
        service_type = None
        violations = None
        if isinstance(qos_comp, dict):
            service_type = (qos_comp.get("details") or {}).get("service_type")
            violations = qos_comp.get("violations")
            if not bool(qos_comp.get("service_priority_ok", True)):
                fallback_reason = "qos_compliance_failed"
        elif confidence < self.confidence_threshold:
            fallback_reason = "low_confidence"

        if not fallback_reason:
            return result

        target = self._select_rule_with_features(ue_id, fv)
        self._record_fallback_metrics(service_type, fallback_reason, violations)
        metrics.HANDOVER_FALLBACKS.inc()
        if target:
            return {
                "antenna_id": target,
                "source": "a3_fallback",
                "confidence": confidence,
                "fallback_to_a3": True,
                "fallback_reason": fallback_reason,
                "ml_prediction": result.get("antenna_id"),
            }
        return None
    
    def _select_ml_with_features(self, ue_id: str, fv: dict) -> Optional[dict]:
        """Make ML prediction using pre-computed features (no state_mgr access).
        
        This is a lock-free version of _select_ml that uses the provided
        feature vector instead of reading from state_manager.
        """
        # Build RF metrics from feature vector
        rf_metrics = {}
        load_map = fv.get("neighbor_cell_loads") or {}
        for aid in fv.get("neighbor_rsrp_dbm", {}):
            metrics_dict = {
                "rsrp": fv["neighbor_rsrp_dbm"][aid],
                "sinr": fv.get("neighbor_sinrs", {}).get(aid, 0),
            }
            rsrq_map = fv.get("neighbor_rsrqs")
            if rsrq_map and aid in rsrq_map:
                metrics_dict["rsrq"] = rsrq_map[aid]
            if isinstance(load_map, dict) and load_map.get(aid) is not None:
                metrics_dict["cell_load"] = load_map[aid]
            rf_metrics[aid] = metrics_dict
        
        ue_data = {
            "ue_id": ue_id,
            "latitude": fv.get("latitude", 0),
            "longitude": fv.get("longitude", 0),
            "altitude": fv.get("altitude"),
            "speed": fv.get("speed", 0.0),
            "direction": fv.get("direction", (0, 0, 0)),
            "connected_to": fv.get("connected_to"),
            "rf_metrics": rf_metrics,
            "service_type": fv.get("service_type", "default"),
            "service_priority": fv.get("service_priority", 5),
        }
        for key in _ML_PAYLOAD_PASSTHROUGH_FIELDS:
            if fv.get(key) is not None:
                ue_data[key] = fv[key]

        observed_qos = _filtered_observed_qos(fv.get("observed_qos"))
        if observed_qos:
            ue_data["observed_qos"] = observed_qos
        
        logger = getattr(self.state_mgr, "logger", self.logger)
        self._last_ml_error_reason = None
        self._last_ml_http_status = None
        
        # Handle local ML model
        if self.use_local_ml and self.model:
            try:
                features = self.model.extract_features(ue_data)
                pred = self.model.predict(features)
                if isinstance(pred, dict):
                    return _ml_result_from_response(pred, source="ml_local")
                return {"antenna_id": pred, "confidence": None, "source": "ml_local"}
            except Exception as exc:
                logger.exception("Local ML prediction failed", exc_info=exc)
                self._last_ml_error_reason = "local_ml_error"
                return None
        
        # Make remote ML HTTP call (this is the slow part)
        url = f"{self.ml_service_url.rstrip('/')}/api/predict-with-qos"
        try:
            logger.debug("HandoverEngine POST to ML URL: %s", url)
            logger.debug("HandoverEngine UE payload: %s", ue_data)
            
            headers = self._get_ml_headers()
            
            def _post_with_optional_headers(auth_headers):
                kwargs = {"json": ue_data, "timeout": self.http_timeout}
                if auth_headers:
                    kwargs["headers"] = auth_headers
                try:
                    return requests.post(url, **kwargs)
                except TypeError as exc:
                    if auth_headers and "headers" in str(exc):
                        return requests.post(url, json=ue_data, timeout=self.http_timeout)
                    raise
            
            resp = _post_with_optional_headers(headers)
            status = getattr(resp, "status_code", None)
            if status == 401 and headers:
                headers = self._get_ml_headers(force_refresh=True)
                if headers:
                    resp = _post_with_optional_headers(headers)
                    status = getattr(resp, "status_code", None)
            
            if status is not None and 400 <= status < 600:
                category = "ml_http_4xx" if status < 500 else "ml_http_5xx"
                self._last_ml_error_reason = category
                self._last_ml_http_status = int(status)
                logger.warning("ML service returned status %s for UE %s", status, ue_id)
                return None
            
            resp.raise_for_status()
            data = resp.json()
            logger.debug("HandoverEngine ML response data: %s", data)
            if not isinstance(data, dict):
                self._last_ml_error_reason = "ml_invalid_response"
                return None
            return _ml_result_from_response(data, source="ml_remote")
        except RequestException as exc:
            self._last_ml_error_reason = "ml_service_unavailable"
            logger.exception("Remote ML request failed", exc_info=exc)
            return None
        except Exception as exc:
            if self._last_ml_error_reason is None:
                self._last_ml_error_reason = "ml_service_unavailable"
            logger.exception("Remote ML request failed", exc_info=exc)
            return None
    
    def _select_rule_with_features(self, ue_id: str, fv: dict, now: Optional[datetime] = None) -> Optional[str]:
        """Make A3 rule decision using pre-computed features with per-UE TTT tracking.
        
        This implements proper 3GPP-compliant Time-to-Trigger (TTT) logic where each
        UE has independent timers for each potential target cell. A handover is only
        triggered when the A3 condition remains satisfied for the full TTT duration.
        """
        current = fv.get("connected_to")
        if not current:
            return None
        
        now = now or self._now()
        rsrp_map = fv.get("neighbor_rsrp_dbm", {})
        rsrq_map = fv.get("neighbor_rsrqs", {})
        
        if current not in rsrp_map:
            return None
        
        serving_rsrp = rsrp_map[current]
        serving_rsrq = rsrq_map.get(current)
        serving_metrics = {"rsrp": serving_rsrp, "rsrq": serving_rsrq} if serving_rsrq is not None else serving_rsrp
        
        # Initialize per-UE timer dict if needed
        if ue_id not in self._ttt_timers:
            self._ttt_timers[ue_id] = {}
        
        hysteresis_db, ttt_seconds = self._a3_params
        best_candidate = None
        best_rsrp = float('-inf')
        active_targets = set()  # Track which targets still meet A3 condition
        
        for aid, rsrp in rsrp_map.items():
            if aid == current:
                continue
            
            neighbor_rsrq = rsrq_map.get(aid)
            target_metrics = {"rsrp": rsrp, "rsrq": neighbor_rsrq} if neighbor_rsrq is not None else rsrp
            
            # Check A3 condition (without TTT - pure signal comparison)
            if hasattr(self.rule, "check_condition"):
                a3_met = self.rule.check_condition(serving_metrics, target_metrics)
            else:
                a3_met = self.rule.check(serving_metrics, target_metrics, now)
            
            if a3_met:
                active_targets.add(aid)
                
                # TTT tracking for this UE-target pair
                if aid not in self._ttt_timers[ue_id]:
                    # Start TTT timer for this target
                    self._ttt_timers[ue_id][aid] = now
                    self.logger.debug(
                        "TTT started for UE %s -> target %s (TTT=%.2fs)",
                        ue_id, aid, ttt_seconds
                    )
                
                # Check if TTT has expired
                elapsed = (now - self._ttt_timers[ue_id][aid]).total_seconds()
                
                if elapsed >= ttt_seconds:
                    # TTT expired - this is a valid handover candidate
                    if rsrp > best_rsrp:
                        best_candidate = aid
                        best_rsrp = rsrp
                        self.logger.debug(
                            "TTT expired for UE %s -> target %s (elapsed=%.2fs, rsrp=%.1f)",
                            ue_id, aid, elapsed, rsrp
                        )
        
        # Clean up timers for targets that no longer meet A3 condition
        stale_targets = set(self._ttt_timers[ue_id].keys()) - active_targets
        for stale in stale_targets:
            del self._ttt_timers[ue_id][stale]
            self.logger.debug("TTT reset for UE %s -> target %s (A3 no longer met)", ue_id, stale)
        
        # If we found a valid candidate, clear all timers for this UE
        if best_candidate:
            self._ttt_timers[ue_id].clear()
            self.logger.info(
                "A3 handover decision for UE %s: %s -> %s (hysteresis=%.1fdB, TTT=%.2fs)",
                ue_id, current, best_candidate, hysteresis_db, ttt_seconds
            )
        
        return best_candidate

    def _select_baseline_with_features(
        self,
        ue_id: str,
        fv: dict,
        mode: str,
        decision_time: datetime,
    ) -> dict:
        """Evaluate the authoritative baseline-service policy with NEF features."""
        policy_decision = self._baseline_policy_manager.decide(
            mode=mode,
            ue_id=ue_id,
            feature_vector=fv,
            timestamp_s=decision_time.timestamp(),
        )
        decision_payload = policy_decision.to_dict()
        target = (
            decision_payload.get("selected_target_cell")
            if decision_payload.get("decision_type") == "handover"
            else None
        )
        return {
            "antenna_id": target,
            "source": mode,
            "fallback_to_a3": False,
            "policy_decision": decision_payload,
        }
    
    def clear_ttt_timers(self, ue_id: str) -> None:
        """Clear TTT timers for a specific UE (call when UE movement stops)."""
        self._ttt_timers.pop(ue_id, None)
        self._baseline_policy_manager.reset(ue_id)
    
    def clear_all_ttt_timers(self) -> None:
        """Clear all TTT timers (call on topology reset)."""
        self._ttt_timers.clear()
        self._baseline_policy_manager.reset()
    
    def apply_decision(self, ue_id: str, decision: dict, fv: dict) -> Optional[dict]:
        """Apply a pre-computed handover decision to UE state.
        
        This should be called while holding the runtime lock to ensure
        atomic state updates.
        
        Args:
            ue_id: UE identifier
            decision: Decision dict from decide_with_features()
            fv: Original feature vector (for validation)
            
        Returns:
            Handover result dict, or None if no handover needed
        """
        target = decision.get("antenna_id")
        if target is None:
            return None
        
        current = fv.get("connected_to")
        resolved_target = self.state_mgr.resolve_antenna_id(target)
        resolved_current = self.state_mgr.resolve_antenna_id(current)
        
        if resolved_target is not None and resolved_target == resolved_current:
            return None  # Already connected, no handover needed
        
        # Apply the handover
        result = self.state_mgr.apply_handover_decision(ue_id, target)
        
        if result:
            self.logger.info(
                "Handover applied for UE %s: %s -> %s (source: %s)",
                ue_id, current, target, decision.get("source", "unknown")
            )
        
        return result

    # ------------------------------------------------------------------

    def _get_ml_headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        if not self._ml_username or not self._ml_password:
            if not self._ml_credentials_warned:
                self.logger.warning(
                    "ML service credentials are not configured; remote predictions will"
                    " require manual authentication."
                )
                self._ml_credentials_warned = True
            return {}

        with self._ml_auth_lock:
            now = time.time()
            if (
                self._ml_access_token
                and not force_refresh
                and now < (self._ml_token_expiry - self._token_refresh_skew)
            ):
                return {"Authorization": f"Bearer {self._ml_access_token}"}

            if self._ml_refresh_token and not force_refresh:
                if self._refresh_ml_token():
                    return {"Authorization": f"Bearer {self._ml_access_token}"}

            if self._login_ml():
                return {"Authorization": f"Bearer {self._ml_access_token}"}

            return {}

    def _login_ml(self) -> bool:
        login_url = f"{self.ml_service_url.rstrip('/')}/api/login"
        payload = {
            "username": self._ml_username,
            "password": self._ml_password,
        }
        try:
            resp = requests.post(login_url, json=payload, timeout=self.http_timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("ML service login failed: %s", exc)
            self._ml_access_token = None
            self._ml_refresh_token = None
            self._ml_token_expiry = 0.0
            return False

        return self._store_ml_tokens(data)

    def _refresh_ml_token(self) -> bool:
        refresh_url = f"{self.ml_service_url.rstrip('/')}/api/refresh"
        payload = {"refresh_token": self._ml_refresh_token}
        try:
            resp = requests.post(refresh_url, json=payload, timeout=self.http_timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            self.logger.info("ML token refresh failed: %s", exc)
            self._ml_refresh_token = None
            self._ml_access_token = None
            self._ml_token_expiry = 0.0
            return False

        return self._store_ml_tokens(data)

    def _store_ml_tokens(self, data: dict) -> bool:
        token = data.get("access_token")
        if not token:
            self.logger.warning("ML authentication response missing access_token")
            self._ml_access_token = None
            self._ml_token_expiry = 0.0
            return False

        self._ml_access_token = str(token)
        refresh_token = data.get("refresh_token")
        self._ml_refresh_token = str(refresh_token) if refresh_token else None
        expires_in = data.get("expires_in")
        self._ml_token_expiry = self._decode_token_expiry(self._ml_access_token, expires_in)
        return True

    def _decode_token_expiry(self, token: str, expires_in: Optional[float]) -> float:
        now = time.time()
        if isinstance(expires_in, (int, float)) and expires_in > 0:
            return now + float(expires_in)

        try:
            claims = jwt.get_unverified_claims(token)
            exp = claims.get("exp")
            if isinstance(exp, (int, float)):
                return float(exp)
        except Exception:  # noqa: BLE001
            pass

        # Fallback: refresh again in five minutes
        return now + self.token_expiry_fallback

    # ------------------------------------------------------------------

    def evaluate_and_apply_handover(
        self,
        ue_id: str,
        features: Optional[dict] = None,
        source: str = "direct",
    ):
        """Evaluate one canonical handover decision and apply it if needed."""
        self._update_mode()
        decision_time = self._now()
        
        # Initialize decision log for thesis analysis
        fv = None
        decision_log = {
            "timestamp": decision_time.isoformat(),
            "ue_id": ue_id,
            "source": source,
            "num_antennas": len(self.state_mgr.antenna_list),
            "ml_auto_activated": self._auto if hasattr(self, '_auto') else False,
        }
        
        try:
            # Get current state for logging
            fv = features if features is not None else self.state_mgr.get_feature_vector(ue_id)
            decision_log["current_antenna"] = fv.get("connected_to")
            decision_log["ue_speed"] = fv.get("speed", 0.0)
            decision_log["ue_position"] = {
                "latitude": fv.get("latitude"),
                "longitude": fv.get("longitude")
            }
            decision_log["candidate_complexity"] = _candidate_complexity_for_feature_vector(
                fv,
                high_complexity_threshold=self.high_complexity_threshold,
            )
            self._append_observed_qos(decision_log, fv.get("observed_qos"))
        except Exception as e:
            decision_log["feature_vector_error"] = str(e)
        
        # Get current mode (use handover_mode if set, fall back to use_ml boolean)
        current_mode = getattr(self, 'handover_mode', 'hybrid' if self.use_ml else 'a3')
        decision_log["handover_mode"] = current_mode

        if current_mode == TRACE_CAPTURE_MODE:
            decision_log["final_target"] = None
            decision_log["handover_triggered"] = False
            decision_log["outcome"] = "trace_capture_no_decision"
            self.logger.info("HANDOVER_DECISION: %s", json.dumps(decision_log))
            self.logger.info("HANDOVER_SKIPPED: %s", json.dumps(decision_log))
            return None

        if current_mode == COMPLEXITY_AWARE_MODE:
            complexity = decision_log.get("candidate_complexity")
            if not isinstance(complexity, dict) and fv:
                complexity = _candidate_complexity_for_feature_vector(
                    fv,
                    high_complexity_threshold=self.high_complexity_threshold,
                )
                decision_log["candidate_complexity"] = complexity

            if isinstance(complexity, dict) and complexity.get("complexity_bucket") == "high":
                decision_log["decision_source"] = "ml_high_complexity"
                decision_log["delegated_policy"] = "ml_policy"
                result = self._select_ml_with_features(ue_id, fv) if fv else self._select_ml(ue_id)
                decision_log["ml_response"] = result

                if result is None:
                    decision_log["ml_available"] = False
                    decision_log["fallback_reason"] = self._last_ml_error_reason or "ml_service_unavailable"
                    if self._last_ml_http_status is not None:
                        decision_log["ml_status_code"] = self._last_ml_http_status
                    target = None
                else:
                    decision_log["ml_available"] = True
                    target = result.get("antenna_id")
                    confidence = result.get("confidence") or 0.0
                    decision_log["ml_prediction"] = target
                    decision_log["ml_confidence"] = confidence
                    decision_log["fallback_to_a3"] = False
                    qos_comp = result.get("qos_compliance")
                    if isinstance(qos_comp, dict):
                        self._record_qos_compliance(decision_log, qos_comp)
                    else:
                        decision_log["qos_compliance"] = {"checked": False}
            else:
                decision_log["decision_source"] = "a3_complexity_gate"
                decision_log["delegated_policy"] = TUNED_A3_BASELINE_MODE
                result = (
                    self._select_baseline_with_features(
                        ue_id,
                        fv,
                        TUNED_A3_BASELINE_MODE,
                        decision_time,
                    )
                    if fv
                    else None
                )
                decision_log["baseline_policy"] = TUNED_A3_BASELINE_MODE
                decision_log["baseline_policy_decision"] = (
                    result.get("policy_decision") if result else None
                )
                target = result.get("antenna_id") if result else None

        elif current_mode in BASELINE_HANDOVER_MODES:
            decision_log["baseline_policy"] = current_mode
            result = (
                self._select_baseline_with_features(
                    ue_id,
                    fv,
                    current_mode,
                    decision_time,
                )
                if fv
                else None
            )
            decision_log["baseline_policy_decision"] = (
                result.get("policy_decision") if result else None
            )
            target = result.get("antenna_id") if result else None

        elif current_mode == "a3":
            # Pure A3 mode - no ML at all
            decision_log["a3_rule_params"] = {
                "hysteresis_db": self._a3_params[0],
                "ttt_seconds": self._a3_params[1]
            }
            target = self._select_rule_with_features(ue_id, fv, now=decision_time) if fv else self._select_rule(ue_id)
            decision_log["a3_target"] = target
            
        elif current_mode == "ml":
            # Pure ML mode - no A3 fallback
            result = self._select_ml_with_features(ue_id, fv) if fv else self._select_ml(ue_id)
            decision_log["ml_response"] = result
            
            if result is None:
                decision_log["ml_available"] = False
                decision_log["fallback_reason"] = self._last_ml_error_reason or "ml_service_unavailable"
                if self._last_ml_http_status is not None:
                    decision_log["ml_status_code"] = self._last_ml_http_status
                # In pure ML mode, no fallback - just no handover
                target = None
            else:
                decision_log["ml_available"] = True
                target = result.get("antenna_id")
                confidence = result.get("confidence") or 0.0
                decision_log["ml_prediction"] = target
                decision_log["ml_confidence"] = confidence
                qos_comp = result.get("qos_compliance")
                if isinstance(qos_comp, dict):
                    self._record_qos_compliance(decision_log, qos_comp)
                else:
                    decision_log["qos_compliance"] = {"checked": False}
                # In pure ML mode, use prediction directly without A3 fallback
                
        else:
            # Hybrid mode (default) - ML with A3 fallback on failures
            result = self._select_ml_with_features(ue_id, fv) if fv else self._select_ml(ue_id)
            decision_log["ml_response"] = result
            
            if result is None:
                decision_log["ml_available"] = False
                fallback_reason = self._last_ml_error_reason or "ml_service_unavailable"
                decision_log["fallback_reason"] = fallback_reason
                if self._last_ml_http_status is not None:
                    decision_log["ml_status_code"] = self._last_ml_http_status
                decision_log["fallback_to_a3"] = True
                metrics.HANDOVER_FALLBACKS.inc()
                self._record_fallback_metrics(None, fallback_reason)
                target = self._select_rule_with_features(ue_id, fv, now=decision_time) if fv else self._select_rule(ue_id)
                decision_log["a3_fallback_target"] = target
            else:
                decision_log["ml_available"] = True
                target = result.get("antenna_id")
                confidence = result.get("confidence")
                if confidence is None:
                    confidence = 0.0
                
                decision_log["ml_prediction"] = target
                decision_log["ml_confidence"] = confidence

                # Prefer structured qos_compliance when available
                qos_comp = result.get("qos_compliance")
                if isinstance(qos_comp, dict):
                    ok = self._record_qos_compliance(decision_log, qos_comp)
                    if not ok:
                        if qos_comp.get("violations"):
                            decision_log["qos_violations"] = qos_comp.get("violations")
                        decision_log["fallback_reason"] = "qos_compliance_failed"
                        decision_log["fallback_to_a3"] = True
                        metrics.HANDOVER_FALLBACKS.inc()
                        self._record_fallback_metrics(
                            decision_log["qos_compliance"].get("service_type"),
                            "qos_compliance_failed",
                            qos_comp.get("violations"),
                        )
                        target = self._select_rule_with_features(ue_id, fv, now=decision_time) if fv else self._select_rule(ue_id)
                        decision_log["a3_fallback_target"] = target
                else:
                    # Legacy behavior: use confidence threshold
                    decision_log["qos_compliance"] = {"checked": False}
                    
                    if confidence < self.confidence_threshold:
                        decision_log["fallback_reason"] = "low_confidence"
                        decision_log["fallback_to_a3"] = True
                        decision_log["confidence_threshold"] = self.confidence_threshold
                        metrics.HANDOVER_FALLBACKS.inc()
                        self._record_fallback_metrics(None, "low_confidence")
                        target = self._select_rule_with_features(ue_id, fv, now=decision_time) if fv else self._select_rule(ue_id)
                        decision_log["a3_fallback_target"] = target

        resolved_current = self.state_mgr.resolve_antenna_id(decision_log.get("current_antenna"))
        resolved_target = self.state_mgr.resolve_antenna_id(target) if target else None

        # COVERAGE LOSS DETECTION: Check if UE has moved outside current cell
        coverage_loss_detected = False
        if resolved_current and fv:
            ue_lat = fv.get("latitude")
            ue_lon = fv.get("longitude")
            
            if ue_lat is not None and ue_lon is not None:
                current_cell = self.state_mgr.get_cell(resolved_current)
                
                if current_cell:
                    try:
                        distance_to_current = _cell_distance(
                            float(ue_lat), float(ue_lon),
                            float(current_cell.latitude), float(current_cell.longitude)
                        )
                        
                        # Allow 1.5x radius before declaring coverage loss
                        max_coverage = float(current_cell.radius) * self.coverage_margin_factor
                        
                        if distance_to_current > max_coverage:
                            coverage_loss_detected = True
                            decision_log["coverage_loss"] = True
                            decision_log["distance_to_current_cell"] = distance_to_current
                            decision_log["max_coverage_distance"] = max_coverage
                            
                            self.logger.warning(
                                "Coverage loss detected for UE %s: %dm from current cell (max: %dm)",
                                ue_id, int(distance_to_current), int(max_coverage)
                            )
                            
                            # If ML/A3 didn't suggest a different cell, find nearest
                            if not target or resolved_target == resolved_current:
                                nearest_cell = self._find_nearest_cell((ue_lat, ue_lon))
                                if nearest_cell and nearest_cell != resolved_current:
                                    self.logger.info(
                                        "Forcing handover to nearest cell: %s", nearest_cell
                                    )
                                    target = nearest_cell
                                    resolved_target = self.state_mgr.resolve_antenna_id(nearest_cell)
                                    decision_log["forced_handover"] = True
                                    decision_log["fallback_reason"] = "coverage_loss"
                                    metrics.COVERAGE_LOSS_HANDOVERS.inc()
                                    metrics.HANDOVER_DECISIONS.labels(outcome="forced_coverage_loss").inc()
                    except Exception as exc:  # noqa: BLE001
                        self.logger.debug("Coverage check failed: %s", exc)

        resolved_target = self.state_mgr.resolve_antenna_id(target) if target else None
        decision_log["final_target"] = resolved_target or target
        decision_log["handover_triggered"] = target is not None

        if not target:
            decision_log["outcome"] = "no_handover"
            self.logger.info("HANDOVER_DECISION: %s", json.dumps(decision_log))
            self.logger.info("HANDOVER_SKIPPED: %s", json.dumps(decision_log))
            return None

        # Check if already connected (only if no coverage loss)
        if resolved_target is not None and resolved_target == resolved_current:
            if not coverage_loss_detected:
                decision_log["handover_triggered"] = False
                decision_log["outcome"] = "already_connected"
                self.logger.info("HANDOVER_DECISION: %s", json.dumps(decision_log))
                self.logger.info("HANDOVER_SKIPPED: %s", json.dumps(decision_log))
                try:
                    self._send_qos_feedback(ue_id, decision_log, fv)
                except Exception as exc:  # noqa: BLE001
                    self.logger.exception("Failed to send QoS feedback", exc_info=exc)
                return None
            # If coverage loss was detected, proceed with handover even if target == current

        # Apply handover and capture result
        handover_result = self.state_mgr.apply_handover_decision(ue_id, target)
        if handover_result is None:
            decision_log["handover_triggered"] = False
            decision_log["outcome"] = "already_connected"
            self.logger.info("HANDOVER_DECISION: %s", json.dumps(decision_log))
            self.logger.info("HANDOVER_SKIPPED: %s", json.dumps(decision_log))
            try:
                self._send_qos_feedback(ue_id, decision_log, fv)
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("Failed to send QoS feedback", exc_info=exc)
            return None
        
        decision_log["outcome"] = "applied"
        decision_log["handover_result"] = handover_result
        
        # Final log with complete decision trace
        self.logger.info("HANDOVER_DECISION: %s", json.dumps(decision_log))
        self.logger.info("HANDOVER_APPLIED: %s", json.dumps(decision_log))
 
        try:
            self._send_qos_feedback(ue_id, decision_log, fv)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Failed to send QoS feedback", exc_info=exc)

        return handover_result

    def decide_and_apply(self, ue_id: str, features: Optional[dict] = None):
        """Backward-compatible wrapper for the canonical handover API."""
        return self.evaluate_and_apply_handover(
            ue_id,
            features=features,
            source="legacy_decide_and_apply",
        )

    # ------------------------------------------------------------------
    # Internal helpers for QoS-aware logging
    # ------------------------------------------------------------------
    @staticmethod
    def _append_observed_qos(decision_log: dict, observed_summary: Optional[dict]) -> None:
        if not isinstance(observed_summary, dict):
            return

        decision_log["observed_qos"] = {
            "sample_count": observed_summary.get("sample_count"),
            "latest": observed_summary.get("latest"),
            "avg": observed_summary.get("avg"),
        }

    @staticmethod
    def _attach_qos_deltas(destination: dict, requirements: dict, observed: dict) -> None:
        if not isinstance(destination, dict):
            return
        if not isinstance(requirements, dict) or not isinstance(observed, dict):
            return

        deltas = {}

        req_latency = requirements.get("latency_requirement_ms")
        obs_latency = observed.get("latency_ms")
        if req_latency is not None and obs_latency is not None:
            deltas["latency_ms"] = obs_latency - req_latency

        req_tp = requirements.get("throughput_requirement_mbps")
        obs_tp = observed.get("throughput_mbps")
        if req_tp is not None and obs_tp is not None:
            deltas["throughput_mbps"] = obs_tp - req_tp

        req_reliability = requirements.get("reliability_pct")
        obs_loss = observed.get("packet_loss_rate")
        if req_reliability is not None and obs_loss is not None:
            max_loss = max(0.0, 100.0 - float(req_reliability))
            deltas["packet_loss_rate"] = obs_loss - max_loss

        if deltas:
            destination["observed_delta"] = deltas

    def _record_qos_compliance(self, decision_log: dict, qos_comp: dict) -> bool:
        """Attach ML QoS compliance details and update Prometheus counters."""
        ok = bool(qos_comp.get("service_priority_ok", True))
        decision_log["qos_compliance"] = {
            "checked": True,
            "passed": ok,
            "required_confidence": qos_comp.get("required_confidence"),
            "observed_confidence": qos_comp.get("observed_confidence"),
            "service_type": qos_comp.get("details", {}).get("service_type"),
            "service_priority": qos_comp.get("details", {}).get("service_priority"),
            "violations": qos_comp.get("violations", []),
            "metrics": qos_comp.get("metrics"),
            "confidence_ok": qos_comp.get("confidence_ok", True),
        }

        self._attach_qos_deltas(
            decision_log["qos_compliance"],
            qos_comp.get("details", {}),
            (decision_log.get("observed_qos") or {}).get("latest", {}),
        )

        try:
            metrics.HANDOVER_COMPLIANCE.labels(outcome="ok" if ok else "failed").inc()
        except Exception:
            pass

        return ok

    @staticmethod
    def _record_fallback_metrics(service_type: Optional[str], reason: str, violations: Optional[list] = None) -> None:
        label = (service_type or "unknown").lower()
        recorded = False

        if violations:
            for violation in violations:
                metric = violation.get("metric") if isinstance(violation, dict) else None
                if metric:
                    metrics.HANDOVER_FALLBACKS_BY_SERVICE.labels(
                        service_type=label,
                        reason=f"qos_{metric}",
                    ).inc()
                    recorded = True

        if not recorded:
            metrics.HANDOVER_FALLBACKS_BY_SERVICE.labels(
                service_type=label,
                reason=reason,
            ).inc()

    def _send_qos_feedback(self, ue_id: str, decision_log: dict, fv: Optional[dict]) -> None:
        mode = getattr(self, "handover_mode", "hybrid" if self.use_ml else "a3")
        if not self.use_ml and mode not in {"ml", "hybrid", COMPLEXITY_AWARE_MODE}:
            return

        compliance = decision_log.get("qos_compliance") or {}
        service_type = compliance.get("service_type") or compliance.get("details", {}).get("service_type")
        service_priority = compliance.get("service_priority") or compliance.get("details", {}).get("service_priority")
        success = compliance.get("passed")

        qos_requirements = compliance.get("details") or (fv.get("qos_requirements") if isinstance(fv, dict) else None)
        observed = self.state_mgr.get_observed_qos(ue_id)
        observed_latest = {}
        if isinstance(observed, dict):
            latest = observed.get("latest") if "latest" in observed else observed.get("avg")
            if isinstance(latest, dict):
                observed_latest = {
                    key: latest.get(key)
                    for key in ("latency_ms", "jitter_ms", "throughput_mbps", "packet_loss_rate")
                    if latest.get(key) is not None
                }

        payload = {
            "ue_id": ue_id,
            "antenna_id": decision_log.get("final_target") or decision_log.get("current_antenna"),
            "service_type": service_type or "default",
            "service_priority": int(service_priority) if service_priority is not None else 5,
            "confidence": float(decision_log.get("ml_confidence", 0.0)),
            "success": bool(success) if success is not None else True,
            "observed_qos": observed_latest,
            "qos_requirements": qos_requirements,
            "violations": compliance.get("violations"),
            "timestamp": self._now().timestamp(),
        }

        endpoint = f"{self.ml_service_url.rstrip('/')}/api/qos-feedback"
        try:
            self.logger.debug("Posting QoS feedback to %s: %s", endpoint, payload)
            headers = self._get_ml_headers()
            request_kwargs = {"json": payload, "timeout": self.feedback_timeout}
            if headers:
                request_kwargs["headers"] = headers
            response = requests.post(endpoint, **request_kwargs)
            status = getattr(response, "status_code", None)
            if status == 401 and headers:
                headers = self._get_ml_headers(force_refresh=True)
                if headers:
                    response = requests.post(
                        endpoint, json=payload, headers=headers, timeout=self.feedback_timeout
                    )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("QoS feedback POST failed: %s", exc)

    def _find_nearest_cell(self, ue_position: tuple[float, float]) -> Optional[str]:
        """Find nearest cell to UE position based on configured cell locations.
        
        Args:
            ue_position: Tuple of (latitude, longitude)
            
        Returns:
            Antenna ID of nearest cell, or None if position invalid
        """
        if ue_position[0] is None or ue_position[1] is None:
            return None
        
        cell_configs = _get_cell_configs()
        
        nearest_cell = None
        min_distance = float('inf')
        
        for antenna_id, config in cell_configs.items():
            try:
                distance = _cell_distance(
                    ue_position[0], ue_position[1],
                    config["latitude"], config["longitude"]
                )
                
                if distance < min_distance:
                    min_distance = distance
                    nearest_cell = antenna_id
            except (KeyError, TypeError, ValueError) as exc:
                self.logger.debug("Failed to compute distance to %s: %s", antenna_id, exc)
                continue
        
        return nearest_cell
