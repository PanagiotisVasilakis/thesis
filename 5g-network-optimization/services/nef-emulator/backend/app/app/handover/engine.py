from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

import logging
import requests
from requests import RequestException

from ..monitoring import metrics

from ..network.state_manager import NetworkStateManager
from .a3_rule import A3EventRule


class HandoverEngine:
    """Decide and apply handovers using the A3 rule or an external
    ML service."""

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

    def _update_mode(self) -> None:
        """Update handover mode automatically based on antenna count."""
        if self._auto:
            want_ml = len(self.state_mgr.antenna_list) >= self.min_antennas_ml
            if want_ml != self.use_ml:
                self.use_ml = want_ml

    # ------------------------------------------------------------------

    def _select_ml(self, ue_id: str) -> Optional[dict]:
        fv = self.state_mgr.get_feature_vector(ue_id)
        rf_metrics = {}
        for aid in fv["neighbor_rsrp_dbm"]:
            metrics_dict = {
                "rsrp": fv["neighbor_rsrp_dbm"][aid],
                "sinr": fv["neighbor_sinrs"][aid],
            }
            rsrq_map = fv.get("neighbor_rsrqs")
            if rsrq_map and aid in rsrq_map:
                metrics_dict["rsrq"] = rsrq_map[aid]
            rf_metrics[aid] = metrics_dict
        ue_data = {
            "ue_id": ue_id,
            "latitude": fv["latitude"],
            "longitude": fv["longitude"],
            "altitude": fv.get("altitude"),
            "speed": fv.get("speed", 0.0),
            "direction": (0, 0, 0),
            "connected_to": fv["connected_to"],
            "rf_metrics": rf_metrics,
        }
        logger = getattr(self.state_mgr, "logger", self.logger)
        if self.use_local_ml and self.model:
            try:
                features = self.model.extract_features(ue_data)
                pred = self.model.predict(features)
                if isinstance(pred, dict):
                    return {
                        "antenna_id": pred.get("antenna_id")
                        or pred.get("predicted_antenna"),
                        "confidence": pred.get("confidence"),
                        "qos_compliance": pred.get("qos_compliance"),
                    }
                return {"antenna_id": pred, "confidence": None}
            except Exception as exc:  # noqa: BLE001 - log and fall back
                logger.exception("Local ML prediction failed", exc_info=exc)
                return None

        # Use the QoS-aware prediction endpoint so the response may include
        # structured `qos_compliance` information used by the handover engine.
        url = f"{self.ml_service_url.rstrip('/')}/api/predict-with-qos"
        try:
            # Debug: record the UE payload and response for integration test
            try:
                logger.debug("HandoverEngine POST to ML URL: %s", url)
                logger.debug("HandoverEngine UE payload: %s", ue_data)
            except Exception:
                # Best-effort logging; don't fail the request if formatting fails
                pass

            resp = requests.post(url, json=ue_data, timeout=5)
            # For test Double-wrapped response object we rely on its
            # raise_for_status()/json() methods being available.
            resp.raise_for_status()
            data = resp.json()
            logger.debug("HandoverEngine ML response data: %s", data)
            return {
                "antenna_id": data.get("predicted_antenna")
                or data.get("antenna_id"),
                "confidence": data.get("confidence"),
                "qos_compliance": data.get("qos_compliance"),
            }
        except Exception as exc:  # noqa: BLE001 - capture any ML service error
            logger.exception("Remote ML request failed", exc_info=exc)
            return None

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

    def decide_and_apply(self, ue_id: str):
        """Select the best antenna and apply the handover with structured logging."""
        self._update_mode()
        
        # Initialize decision log for thesis analysis
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
        except Exception as e:
            decision_log["feature_vector_error"] = str(e)
        
        if self.use_ml:
            result = self._select_ml(ue_id)
            decision_log["ml_response"] = result
            
            if result is None:
                decision_log["ml_available"] = False
                decision_log["fallback_reason"] = "ml_service_unavailable"
                decision_log["fallback_to_a3"] = True
                target = None
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
                        "service_priority": qos_comp.get("details", {}).get("service_priority")
                    }
                    
                    # record compliance metric
                    try:
                        metrics.HANDOVER_COMPLIANCE.labels(outcome="ok" if ok else "failed").inc()
                    except Exception:
                        pass
                    
                    if not ok:
                        decision_log["fallback_reason"] = "qos_compliance_failed"
                        decision_log["fallback_to_a3"] = True
                        metrics.HANDOVER_FALLBACKS.inc()
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
                        target = self._select_rule(ue_id)
                        decision_log["a3_fallback_target"] = target
        else:
            # A3 mode
            decision_log["a3_rule_params"] = {
                "hysteresis_db": self._a3_params[0],
                "ttt_seconds": self._a3_params[1]
            }
            target = self._select_rule(ue_id)
            decision_log["a3_target"] = target

        decision_log["final_target"] = target
        decision_log["handover_triggered"] = target is not None
        
        # Log structured JSON for thesis analysis
        self.logger.info(f"HANDOVER_DECISION: {json.dumps(decision_log)}")
        
        if not target:
            decision_log["outcome"] = "no_handover"
            return None
        
        # Apply handover and capture result
        handover_result = self.state_mgr.apply_handover_decision(ue_id, target)
        decision_log["outcome"] = "applied"
        decision_log["handover_result"] = handover_result
        
        # Final log with complete decision trace
        self.logger.info(f"HANDOVER_APPLIED: {json.dumps(decision_log)}")
        
        return handover_result
