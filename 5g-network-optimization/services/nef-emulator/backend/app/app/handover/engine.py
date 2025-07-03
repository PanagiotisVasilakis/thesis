from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import requests

from ..network.state_manager import NetworkStateManager
from .a3_rule import A3EventRule


class HandoverEngine:
    """Decide and apply handovers using the A3 rule or an external ML service."""

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
    ) -> None:
        self.state_mgr = state_mgr
        self.ml_model_path = ml_model_path
        self.ml_service_url = ml_service_url or os.getenv(
            "ML_SERVICE_URL", "http://ml-service:5050"
        )
        self.min_antennas_ml = min_antennas_ml
        env_local = os.getenv("ML_LOCAL")
        if env_local is not None:
            self.use_local_ml = env_local.lower() in {"1", "true", "yes"}
        else:
            self.use_local_ml = bool(use_local_ml)
        self.model = None
        if self.use_local_ml:
            try:
                from ml_service.app.initialization.model_init import get_model

                self.model = get_model(self.ml_model_path)
            except Exception:
                self.model = None
        self._a3_params = (a3_hysteresis_db, a3_ttt_s)
        # Always have an A3 rule available; it will only be used when
        # machine learning is disabled.
        self.rule = A3EventRule(
            hysteresis_db=self._a3_params[0], ttt_seconds=self._a3_params[1]
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
    def _select_ml(self, ue_id: str) -> Optional[str]:
        fv = self.state_mgr.get_feature_vector(ue_id)
        rf_metrics = {
            aid: {
                "rsrp": fv["neighbor_rsrp_dbm"][aid],
                "sinr": fv["neighbor_sinrs"][aid],
            }
            for aid in fv["neighbor_rsrp_dbm"]
        }
        ue_data = {
            "ue_id": ue_id,
            "latitude": fv["latitude"],
            "longitude": fv["longitude"],
            "speed": fv.get("speed", 0.0),
            "direction": (0, 0, 0),
            "connected_to": fv["connected_to"],
            "rf_metrics": rf_metrics,
        }
        if self.use_local_ml and self.model:
            try:
                features = self.model.extract_features(ue_data)
                pred = self.model.predict(features)
                return pred.get("antenna_id") or pred.get("predicted_antenna")
            except Exception:
                return None
        url = f"{self.ml_service_url.rstrip('/')}/api/predict"
        try:
            resp = requests.post(url, json=ue_data, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            return data.get("predicted_antenna") or data.get("antenna_id")
        except Exception:
            return None

    def _select_rule(self, ue_id: str) -> Optional[str]:
        fv = self.state_mgr.get_feature_vector(ue_id)
        current = fv["connected_to"]
        now = datetime.utcnow()
        for aid, rsrp in fv["neighbor_rsrp_dbm"].items():
            if aid == current:
                continue
            if self.rule.check(fv["neighbor_rsrp_dbm"][current], rsrp, now):
                return aid
        return None

    # ------------------------------------------------------------------
    def decide_and_apply(self, ue_id: str):
        """Select the best antenna and apply the handover."""
        self._update_mode()
        target = self._select_ml(ue_id) if self.use_ml else self._select_rule(ue_id)
        if not target:
            return None
        return self.state_mgr.apply_handover_decision(ue_id, target)
