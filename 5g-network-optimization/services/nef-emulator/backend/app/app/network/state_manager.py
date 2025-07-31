# services/nef-emulator/network/state_manager.py

import logging
import os
from datetime import datetime
import math


class NetworkStateManager:
    """Manages UEs, antennas, connections, and history for ML integration."""

    def __init__(
        self,
        a3_hysteresis_db: float = 2.0,
        a3_ttt_s: float = 0.0,
        resource_blocks: int = 50,
    ):
        """Initialize the network state manager.

        Parameters can be overridden by the following environment variables:
        A3_HYSTERESIS_DB - hysteresis in dB for the A3 event
        A3_TTT_S - time-to-trigger in seconds for the A3 event
        RESOURCE_BLOCKS - number of resource blocks for RSRQ calculation
        """
        # Read overrides from environment variables

        env_hyst = os.getenv("A3_HYSTERESIS_DB")
        if env_hyst is not None:
            try:
                a3_hysteresis_db = float(env_hyst)
            except ValueError:
                logging.warning(
                    "Invalid value for A3_HYSTERESIS_DB: "
                    f"'{env_hyst}'. Using default value."
                )

        env_ttt = os.getenv("A3_TTT_S")
        if env_ttt is not None:
            try:
                a3_ttt_s = float(env_ttt)
            except ValueError:
                pass
        self.ue_states = {}  # supi -> {'position': (x, y, z), 'speed': v,
        # 'connected_to': ant_id, 'trajectory': [...]}
        self.antenna_list = {}  # ant_id -> AntennaModel instance
        self.handover_history = []  # list of {ue_id, from, to, timestamp}
        self.logger = logging.getLogger("NetworkStateManager")
        # Default noise floor in dBm (tunable)
        self.noise_floor_dbm = -100.0
        env_noise = os.getenv("NOISE_FLOOR_DBM")
        if env_noise is not None:
            try:
                self.noise_floor_dbm = float(env_noise)
            except ValueError:
                self.logger.warning(
                    "Invalid value for NOISE_FLOOR_DBM: "
                    f"'{env_noise}'. Using default."
                )
        env_rbs = os.getenv("RESOURCE_BLOCKS")
        if env_rbs is not None:
            try:
                resource_blocks = int(env_rbs)
            except ValueError:
                self.logger.warning(
                    "Invalid value for RESOURCE_BLOCKS: '%s'. Using default.",
                    env_rbs,
                )

        self._a3_params = (a3_hysteresis_db, a3_ttt_s)
        self.resource_blocks = max(int(resource_blocks), 1)

    def get_feature_vector(self, ue_id):
        """
        Return a dict of features for ML based on current state.
        """
        state = self.ue_states.get(ue_id)
        if not state:
            raise KeyError(f"UE {ue_id} not found")

        x, y, z = state["position"]
        speed = state.get("speed", 0.0)
        connected = state.get("connected_to")

        # RSRP in dBm for each antenna
        rsrp_dbm = {
            ant_id: ant.rsrp_dbm(state["position"])
            for ant_id, ant in self.antenna_list.items()
        }
        # Convert to linear mW
        rsrp_mw = {aid: 10 ** (dbm / 10.0) for aid, dbm in rsrp_dbm.items()}
        noise_mw = 10 ** (self.noise_floor_dbm / 10.0)

        # Compute per-antenna SINR and RSRQ
        neighbor_sinrs = {}
        neighbor_rsrqs = {}
        for aid, sig in rsrp_mw.items():
            interf = sum(m for other, m in rsrp_mw.items() if other != aid)
            denom = noise_mw + interf
            lin = sig / denom if denom > 0 else 0.0
            neighbor_sinrs[aid] = (
                10 * math.log10(lin) if lin > 0 else -float("inf")
            )

            rssi = sig + denom
            rsrq_lin = (self.resource_blocks * sig) / rssi if rssi > 0 else 0.0
            neighbor_rsrqs[aid] = (
                10 * math.log10(rsrq_lin) if rsrq_lin > 0 else -float("inf")
            )

        # Order neighbors by RSRP strength
        ordered = sorted(rsrp_dbm.items(), key=lambda x: x[1], reverse=True)
        rsrp_dbm = {aid: val for aid, val in ordered}
        neighbor_sinrs = {aid: neighbor_sinrs[aid] for aid, _ in ordered}
        neighbor_rsrqs = {aid: neighbor_rsrqs[aid] for aid, _ in ordered}

        # Calculate current load per antenna as number of connected UEs
        antenna_loads = {aid: 0 for aid in self.antenna_list}
        for u_state in self.ue_states.values():
            conn = u_state.get("connected_to")
            if conn in antenna_loads:
                antenna_loads[conn] += 1
        antenna_loads = {aid: antenna_loads[aid] for aid, _ in ordered}

        features = {
            "ue_id": ue_id,
            "latitude": x,
            "longitude": y,
            "altitude": z,
            "speed": speed,
            "connected_to": connected,
            "neighbor_rsrp_dbm": rsrp_dbm,
            "neighbor_sinrs": neighbor_sinrs,
            "neighbor_rsrqs": neighbor_rsrqs,
            "neighbor_cell_loads": antenna_loads,
        }
        return features

    def apply_handover_decision(self, ue_id, target_antenna_id):
        """Apply an ML-driven handover decision or rule-based one."""
        state = self.ue_states.get(ue_id)
        if not state:
            raise KeyError(f"UE {ue_id} not found")
        prev = state.get("connected_to")
        if target_antenna_id not in self.antenna_list:
            raise KeyError(f"Antenna {target_antenna_id} unknown")

        # The A3 rule is evaluated by the HandoverEngine when machine learning
        # is disabled. NetworkStateManager simply applies the decision here.

        state["connected_to"] = target_antenna_id

        ev = {
            "ue_id": ue_id,
            "from": prev,
            "to": target_antenna_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.handover_history.append(ev)
        self.logger.info(f"Handover for {ue_id}: {prev} → {target_antenna_id}")
        return ev

    def get_position_at_time(self, ue_id, query_time):
        """
        Return the UE's interpolated position at a given datetime.
        If before the first point, returns the first; after the last, the last.
        """
        state = self.ue_states.get(ue_id)
        if not state:
            raise KeyError(f"UE {ue_id} not found")
        traj = state.get("trajectory") or []
        if not traj:
            raise ValueError(f"No trajectory recorded for UE {ue_id}")

        # Sort trajectory by timestamp
        traj = sorted(traj, key=lambda p: p["timestamp"])
        # If before first or after last, clamp
        if query_time <= traj[0]["timestamp"]:
            return traj[0]["position"]
        if query_time >= traj[-1]["timestamp"]:
            return traj[-1]["position"]

        # Find segment bracketing query_time
        for i in range(len(traj) - 1):
            t0, t1 = traj[i]["timestamp"], traj[i + 1]["timestamp"]
            if t0 <= query_time <= t1:
                p0, p1 = traj[i]["position"], traj[i + 1]["position"]
                total = (t1 - t0).total_seconds()
                frac = (
                    (query_time - t0).total_seconds() / total
                    if total > 0
                    else 0
                )
                # Linear interpolate each coordinate
                return tuple(p0[j] + frac * (p1[j] - p0[j]) for j in range(3))

        # Fallback (shouldn't reach)
        return traj[-1]["position"]
