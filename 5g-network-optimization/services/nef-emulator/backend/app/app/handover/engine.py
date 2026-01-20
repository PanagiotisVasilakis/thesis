from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import logging
import requests
from jose import jwt
from requests import RequestException

from ..monitoring import metrics

from ..network.state_manager import NetworkStateManager
from .a3_rule import A3EventRule


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
    ) -> None:
        self.state_mgr = state_mgr
        self.logger = getattr(state_mgr, "logger", logging.getLogger("HandoverEngine"))
        self.ml_model_path = ml_model_path
        self.ml_service_url = ml_service_url or os.getenv(
            "ML_SERVICE_URL", "http://ml-service:5050"
        )
        self.min_antennas_ml = min_antennas_ml
        env_thresh = os.getenv("ML_CONFIDENCE_THRESHOLD")
        if env_thresh is not None:
            try:
                confidence_threshold = float(env_thresh)
            except ValueError:
                self.logger.warning(
                    "Invalid value for ML_CONFIDENCE_THRESHOLD: '%s'. Using default.",
                    env_thresh,
                )
        self.confidence_threshold = confidence_threshold
        env_local = os.getenv("ML_LOCAL")
        if env_local is not None:
            self.use_local_ml = env_local.lower() in {"1", "true", "yes"}
        else:
            self.use_local_ml = bool(use_local_ml)
        self.model = None
        if self.use_local_ml:
            try:
                from ml_service.app.api_lib import load_model

                self.model = load_model(self.ml_model_path)
            except Exception:
                self.model = None
        self._a3_params = (a3_hysteresis_db, a3_ttt_s)
        # Always have an A3 rule available; it will only be used when
        # machine learning is disabled.
        self.rule = A3EventRule(
            hysteresis_db=self._a3_params[0], 
            ttt_seconds=self._a3_params[1],
            event_type="rsrp_based"  # Default to RSRP-based for backward compatibility
        )

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

        # Handover mode: "ml" (pure), "a3" (pure), or "hybrid" (ML with A3 fallback)
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
        try:
            self._token_refresh_skew = float(os.getenv("ML_TOKEN_REFRESH_SKEW", "15"))
        except ValueError:
            self._token_refresh_skew = 15.0
        self._last_ml_error_reason: Optional[str] = None
        self._last_ml_http_status: Optional[int] = None

    def _update_mode(self) -> None:
        """Update handover mode automatically based on antenna count."""
        if self._auto:
            want_ml = len(self.state_mgr.antenna_list) >= self.min_antennas_ml
            if want_ml != self.use_ml:
                self.use_ml = want_ml

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
        current = fv["connected_to"]
        now = datetime.now(timezone.utc)
        
        # Prepare serving cell metrics
        serving_rsrp = fv["neighbor_rsrp_dbm"][current]
        serving_rsrq = fv["neighbor_rsrqs"].get(current) if "neighbor_rsrqs" in fv else None
        serving_metrics = {
            "rsrp": serving_rsrp,
            "rsrq": serving_rsrq
        } if serving_rsrq is not None else serving_rsrp
        
        # Check each neighbor
        for aid, rsrp in fv["neighbor_rsrp_dbm"].items():
            if aid == current:
                continue
            
            neighbor_rsrq = fv["neighbor_rsrqs"].get(aid) if "neighbor_rsrqs" in fv else None
            target_metrics = {
                "rsrp": rsrp,
                "rsrq": neighbor_rsrq
            } if neighbor_rsrq is not None else rsrp
            
            if self.rule.check(serving_metrics, target_metrics, now):
                return aid
        return None

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
        
        if self.use_ml:
            result = self._select_ml_with_features(ue_id, fv)
            if result is None:
                # ML unavailable, fallback to A3 rule
                target = self._select_rule_with_features(ue_id, fv)
                if target:
                    return {"antenna_id": target, "source": "a3_fallback"}
                return None
            return result
        else:
            target = self._select_rule_with_features(ue_id, fv)
            if target:
                return {"antenna_id": target, "source": "a3_rule"}
            return None
    
    def _select_ml_with_features(self, ue_id: str, fv: dict) -> Optional[dict]:
        """Make ML prediction using pre-computed features (no state_mgr access).
        
        This is a lock-free version of _select_ml that uses the provided
        feature vector instead of reading from state_manager.
        """
        # Build RF metrics from feature vector
        rf_metrics = {}
        for aid in fv.get("neighbor_rsrp_dbm", {}):
            metrics_dict = {
                "rsrp": fv["neighbor_rsrp_dbm"][aid],
                "sinr": fv.get("neighbor_sinrs", {}).get(aid, 0),
            }
            rsrq_map = fv.get("neighbor_rsrqs")
            if rsrq_map and aid in rsrq_map:
                metrics_dict["rsrq"] = rsrq_map[aid]
            rf_metrics[aid] = metrics_dict
        
        ue_data = {
            "ue_id": ue_id,
            "latitude": fv.get("latitude", 0),
            "longitude": fv.get("longitude", 0),
            "altitude": fv.get("altitude"),
            "speed": fv.get("speed", 0.0),
            "direction": (0, 0, 0),
            "connected_to": fv.get("connected_to"),
            "rf_metrics": rf_metrics,
        }
        
        # Add observed QoS if present
        observed_qos = fv.get("observed_qos")
        if isinstance(observed_qos, dict):
            latest = observed_qos.get("latest") or {}
            if isinstance(latest, dict):
                simplified = {
                    key: latest.get(key)
                    for key in ("latency_ms", "jitter_ms", "throughput_mbps", "packet_loss_rate")
                    if latest.get(key) is not None
                }
                if simplified:
                    ue_data["observed_qos"] = simplified
        
        logger = getattr(self.state_mgr, "logger", self.logger)
        self._last_ml_error_reason = None
        self._last_ml_http_status = None
        
        # Handle local ML model
        if self.use_local_ml and self.model:
            try:
                features = self.model.extract_features(ue_data)
                pred = self.model.predict(features)
                if isinstance(pred, dict):
                    return {
                        "antenna_id": pred.get("antenna_id") or pred.get("predicted_antenna"),
                        "confidence": pred.get("confidence"),
                        "qos_compliance": pred.get("qos_compliance"),
                        "source": "ml_local",
                    }
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
                kwargs = {"json": ue_data, "timeout": 5}
                if auth_headers:
                    kwargs["headers"] = auth_headers
                try:
                    return requests.post(url, **kwargs)
                except TypeError as exc:
                    if auth_headers and "headers" in str(exc):
                        return requests.post(url, json=ue_data, timeout=5)
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
            return {
                "antenna_id": data.get("predicted_antenna") or data.get("antenna_id"),
                "confidence": data.get("confidence"),
                "qos_compliance": data.get("qos_compliance"),
                "source": "ml_remote",
            }
        except RequestException as exc:
            self._last_ml_error_reason = "ml_service_unavailable"
            logger.exception("Remote ML request failed", exc_info=exc)
            return None
        except Exception as exc:
            if self._last_ml_error_reason is None:
                self._last_ml_error_reason = "ml_service_unavailable"
            logger.exception("Remote ML request failed", exc_info=exc)
            return None
    
    def _select_rule_with_features(self, ue_id: str, fv: dict) -> Optional[str]:
        """Make A3 rule decision using pre-computed features (no state_mgr access)."""
        current = fv.get("connected_to")
        if not current:
            return None
        
        now = datetime.now(timezone.utc)
        rsrp_map = fv.get("neighbor_rsrp_dbm", {})
        rsrq_map = fv.get("neighbor_rsrqs", {})
        
        if current not in rsrp_map:
            return None
        
        serving_rsrp = rsrp_map[current]
        serving_rsrq = rsrq_map.get(current)
        serving_metrics = {"rsrp": serving_rsrp, "rsrq": serving_rsrq} if serving_rsrq else serving_rsrp
        
        for aid, rsrp in rsrp_map.items():
            if aid == current:
                continue
            
            neighbor_rsrq = rsrq_map.get(aid)
            target_metrics = {"rsrp": rsrp, "rsrq": neighbor_rsrq} if neighbor_rsrq else rsrp
            
            if self.rule.check(serving_metrics, target_metrics, now):
                return aid
        
        return None
    
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
            resp = requests.post(login_url, json=payload, timeout=5)
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
            resp = requests.post(refresh_url, json=payload, timeout=5)
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

    @staticmethod
    def _decode_token_expiry(token: str, expires_in: Optional[float]) -> float:
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
        return now + 300.0

    # ------------------------------------------------------------------

    def decide_and_apply(self, ue_id: str):
        """Select the best antenna and apply the handover with structured logging."""
        self._update_mode()
        
        # Initialize decision log for thesis analysis
        fv = None
        decision_log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ue_id": ue_id,
            "mode": "ml" if self.use_ml else "a3",
            "num_antennas": len(self.state_mgr.antenna_list),
            "ml_auto_activated": self._auto if hasattr(self, '_auto') else False,
        }
        
        try:
            # Get current state for logging
            fv = self.state_mgr.get_feature_vector(ue_id)
            decision_log["current_antenna"] = fv.get("connected_to")
            decision_log["ue_speed"] = fv.get("speed", 0.0)
            decision_log["ue_position"] = {
                "latitude": fv.get("latitude"),
                "longitude": fv.get("longitude")
            }
            self._append_observed_qos(decision_log, fv.get("observed_qos"))
        except Exception as e:
            decision_log["feature_vector_error"] = str(e)
        
        # Get current mode (use handover_mode if set, fall back to use_ml boolean)
        current_mode = getattr(self, 'handover_mode', 'hybrid' if self.use_ml else 'a3')
        decision_log["handover_mode"] = current_mode

        if current_mode == "a3":
            # Pure A3 mode - no ML at all
            decision_log["a3_rule_params"] = {
                "hysteresis_db": self._a3_params[0],
                "ttt_seconds": self._a3_params[1]
            }
            target = self._select_rule(ue_id)
            decision_log["a3_target"] = target
            
        elif current_mode == "ml":
            # Pure ML mode - no A3 fallback
            result = self._select_ml(ue_id)
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
                # In pure ML mode, use prediction directly without checking thresholds
                
        else:
            # Hybrid mode (default) - ML with A3 fallback on failures
            result = self._select_ml(ue_id)
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
                target = self._select_rule(ue_id)
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
                    
                    # record compliance metric
                    try:
                        metrics.HANDOVER_COMPLIANCE.labels(outcome="ok" if ok else "failed").inc()
                    except Exception:
                        pass
                    
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
                        target = self._select_rule(ue_id)
                        decision_log["a3_fallback_target"] = target
                        
                        # If the rule-based selector found no candidate, use the
                        # current serving cell as a safe fallback
                        if not target:
                            try:
                                fv = self.state_mgr.get_feature_vector(ue_id)
                                target = fv.get("connected_to")
                                decision_log["final_fallback"] = "current_cell"
                            except Exception:
                                target = None
                                decision_log["final_fallback"] = "none"
                else:
                    # Legacy behavior: use confidence threshold
                    decision_log["qos_compliance"] = {"checked": False}
                    
                    if confidence < self.confidence_threshold:
                        decision_log["fallback_reason"] = "low_confidence"
                        decision_log["fallback_to_a3"] = True
                        decision_log["confidence_threshold"] = self.confidence_threshold
                        metrics.HANDOVER_FALLBACKS.inc()
                        self._record_fallback_metrics(None, "low_confidence")
                        target = self._select_rule(ue_id)
                        decision_log["a3_fallback_target"] = target

        resolved_current = self.state_mgr.resolve_antenna_id(decision_log.get("current_antenna"))
        resolved_target = self.state_mgr.resolve_antenna_id(target) if target else None

        decision_log["final_target"] = resolved_target or target
        decision_log["handover_triggered"] = target is not None

        # Log structured JSON for thesis analysis
        self.logger.info("HANDOVER_DECISION: %s", json.dumps(decision_log))

        if not target:
            decision_log["outcome"] = "no_handover"
            return None

        # COVERAGE LOSS DETECTION: Check if UE has moved outside current cell
        coverage_loss_detected = False
        if resolved_current and fv:
            ue_lat = fv.get("latitude")
            ue_lon = fv.get("longitude")
            
            if ue_lat is not None and ue_lon is not None:
                current_cell = self.state_mgr.get_cell(resolved_current)
                
                if current_cell:
                    try:
                        from ml_service.app.config.cells import haversine_distance
                        
                        distance_to_current = haversine_distance(
                            float(ue_lat), float(ue_lon),
                            float(current_cell.latitude), float(current_cell.longitude)
                        )
                        
                        # Allow 1.5x radius before declaring coverage loss
                        max_coverage = float(current_cell.radius) * 1.5
                        
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
                                    decision_log["final_target"] = resolved_target or target
                                    metrics.COVERAGE_LOSS_HANDOVERS.inc()
                                    metrics.HANDOVER_DECISIONS.labels(decision="forced_coverage_loss").inc()
                    except ImportError:
                        self.logger.debug("Cell config unavailable for coverage check")
                    except Exception as exc:  # noqa: BLE001
                        self.logger.debug("Coverage check failed: %s", exc)

        # Check if already connected (only if no coverage loss)
        if resolved_target is not None and resolved_target == resolved_current:
            if not coverage_loss_detected:
                decision_log["handover_triggered"] = False
                decision_log["outcome"] = "already_connected"
                self.logger.info("HANDOVER_SKIPPED: %s", json.dumps(decision_log))
                return None
            # If coverage loss was detected, proceed with handover even if target == current

        # Apply handover and capture result
        handover_result = self.state_mgr.apply_handover_decision(ue_id, target)
        if handover_result is None:
            decision_log["handover_triggered"] = False
            decision_log["outcome"] = "already_connected"
            self.logger.info("HANDOVER_SKIPPED: %s", json.dumps(decision_log))
            return None
        
        decision_log["outcome"] = "applied"
        decision_log["handover_result"] = handover_result
        
        # Final log with complete decision trace
        self.logger.info("HANDOVER_APPLIED: %s", json.dumps(decision_log))
 
        try:
            self._send_qos_feedback(ue_id, decision_log, fv)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Failed to send QoS feedback", exc_info=exc)

        return handover_result

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
        if not self.use_ml:
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
            "timestamp": datetime.now(timezone.utc).timestamp(),
        }

        endpoint = f"{self.ml_service_url.rstrip('/')}/api/qos-feedback"
        try:
            self.logger.debug("Posting QoS feedback to %s: %s", endpoint, payload)
            headers = self._get_ml_headers()
            request_kwargs = {"json": payload, "timeout": 3}
            if headers:
                request_kwargs["headers"] = headers
            response = requests.post(endpoint, **request_kwargs)
            status = getattr(response, "status_code", None)
            if status == 401 and headers:
                headers = self._get_ml_headers(force_refresh=True)
                if headers:
                    response = requests.post(
                        endpoint, json=payload, headers=headers, timeout=3
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
        
        try:
            from ml_service.app.config.cells import CELL_CONFIGS, haversine_distance
        except ImportError:
            self.logger.warning("Cell configuration not available for distance calculation")
            return None
        
        nearest_cell = None
        min_distance = float('inf')
        
        for antenna_id, config in CELL_CONFIGS.items():
            try:
                distance = haversine_distance(
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
