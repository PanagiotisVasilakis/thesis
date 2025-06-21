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
        min_antennas_ml: int = 4,
        a3_hysteresis_db: float = 2.0,
        a3_ttt_s: float = 0.0,
    ) -> None:
        self.state_mgr = state_mgr

        if use_ml is None:
            env = os.getenv("ML_HANDOVER_ENABLED")
            if env is not None:
                use_ml = env.lower() in {"1", "true", "yes"}
            else:
                use_ml = len(state_mgr.antenna_list) >= min_antennas_ml
        self.use_ml = bool(use_ml)

        if self.use_ml:
            if AntennaSelector is None:
                raise RuntimeError("AntennaSelector not available")
            self.selector = AntennaSelector(model_path=ml_model_path)
        else:
            self.rule = A3EventRule(hysteresis_db=a3_hysteresis_db, ttt_seconds=a3_ttt_s)

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
        target = self._select_ml(ue_id) if self.use_ml else self._select_rule(ue_id)
        if not target:
            return None
        return self.state_mgr.apply_handover_decision(ue_id, target)
