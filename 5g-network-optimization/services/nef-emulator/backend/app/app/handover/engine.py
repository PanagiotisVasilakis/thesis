from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from app.network.state_manager import NetworkStateManager
from .a3_rule import A3EventRule

try:
    from app.models.antenna_selector import AntennaSelector
except Exception:  # pragma: no cover - optional dependency
    AntennaSelector = None  # type: ignore


class HandoverEngine:
    """Decide and apply handovers using rule-based or ML approaches."""

    def __init__(
        self,
        state_mgr: NetworkStateManager,
        use_ml: Optional[bool] = None,
        ml_model_path: Optional[str] = None,
        min_antennas_ml: int = 3,
        a3_hysteresis_db: float = 2.0,
        a3_ttt_s: float = 0.0,
    ) -> None:
        self.state_mgr = state_mgr
        self.ml_model_path = ml_model_path
        self.min_antennas_ml = min_antennas_ml
        self._a3_params = (a3_hysteresis_db, a3_ttt_s)

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

        self._ensure_mode()

    def _ensure_mode(self) -> None:
        """Instantiate selector or rule depending on current mode."""
        if self.use_ml:
            if AntennaSelector is None:
                raise RuntimeError("AntennaSelector not available")
            if not hasattr(self, "selector"):
                self.selector = AntennaSelector(model_path=self.ml_model_path)
            if hasattr(self, "rule"):
                del self.rule
        else:
            if not hasattr(self, "rule"):
                self.rule = A3EventRule(
                    hysteresis_db=self._a3_params[0], ttt_seconds=self._a3_params[1]
                )
            if hasattr(self, "selector"):
                del self.selector

    def _update_mode(self) -> None:
        """Update handover mode automatically based on antenna count."""
        if self._auto:
            want_ml = len(self.state_mgr.antenna_list) >= self.min_antennas_ml
            if want_ml != self.use_ml:
                self.use_ml = want_ml
                self._ensure_mode()

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
        feats = self.selector.extract_features(ue_data)
        pred = self.selector.predict(feats)
        return pred.get("antenna_id")

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
