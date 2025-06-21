# services/nef-emulator/network/state_manager.py

import logging
from datetime import datetime
import math

class NetworkStateManager:
    """Manages UEs, antennas, connections, and history for ML integration."""

    def __init__(self, simple_mode: bool = False, a3_hysteresis_db: float = 2.0,
                 a3_ttt_s: float = 0.0):
        self.ue_states = {}          # supi -> { 'position':(x,y,z), 'speed':v, 'connected_to':ant_id, 'trajectory':[...] }
        self.antenna_list = {}       # ant_id -> AntennaModel instance
        self.handover_history = []   # list of {ue_id, from, to, timestamp}
        self.logger = logging.getLogger('NetworkStateManager')
        # Default noise floor in dBm (tunable)
        self.noise_floor_dbm = -100.0
        self.simple_mode = simple_mode
        if simple_mode:
            from ..handover.a3_rule import A3EventRule
            self._a3_params = (a3_hysteresis_db, a3_ttt_s)
            self._rules = {}  # ue_id -> A3EventRule

    def get_feature_vector(self, ue_id):
        """
        Return a dict of features for ML based on current state.
        """
        state = self.ue_states.get(ue_id)
        if not state:
            raise KeyError(f"UE {ue_id} not found")

        x, y, z = state['position']
        speed = state.get('speed', 0.0)
        connected = state.get('connected_to')

        # RSRP in dBm
        rsrp_dbm = {
            ant_id: ant.rsrp_dbm(state['position'])
            for ant_id, ant in self.antenna_list.items()
        }
        # Convert to linear mW
        rsrp_mw = {aid: 10**(dbm/10.0) for aid, dbm in rsrp_dbm.items()}
        noise_mw = 10**(self.noise_floor_dbm/10.0)

        # Compute per-antenna SINR
        neighbor_sinrs = {}
        for aid, sig in rsrp_mw.items():
            interf = sum(m for other, m in rsrp_mw.items() if other != aid)
            lin = sig / (noise_mw + interf) if (noise_mw + interf) > 0 else 0.0
            neighbor_sinrs[aid] = 10 * math.log10(lin) if lin > 0 else -float('inf')

        features = {
            'ue_id':        ue_id,
            'latitude':     x,
            'longitude':    y,
            'altitude':     z,
            'speed':        speed,
            'connected_to': connected,
            'neighbor_rsrs': rsrp_dbm,
            'neighbor_sinrs': neighbor_sinrs,
        }
        return features

    def apply_handover_decision(self, ue_id, target_antenna_id):
        """Apply an ML-driven handover decision or rule-based one."""
        state = self.ue_states.get(ue_id)
        if not state:
            raise KeyError(f"UE {ue_id} not found")
        prev = state.get('connected_to')
        if target_antenna_id not in self.antenna_list:
            raise KeyError(f"Antenna {target_antenna_id} unknown")

        if self.simple_mode:
            rule = self._rules.get(ue_id)
            if rule is None:
                from ..handover.a3_rule import A3EventRule
                rule = A3EventRule(*self._a3_params)
                self._rules[ue_id] = rule
            now = datetime.utcnow()
            rsrp_serv = self.antenna_list[prev].rsrp_dbm(state['position'])
            rsrp_tgt = self.antenna_list[target_antenna_id].rsrp_dbm(state['position'])
            if not rule.check(rsrp_serv, rsrp_tgt, now):
                return None

        state['connected_to'] = target_antenna_id

        ev = {
            'ue_id':     ue_id,
            'from':      prev,
            'to':        target_antenna_id,
            'timestamp': datetime.utcnow().isoformat()
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
        traj = state.get('trajectory') or []
        if not traj:
            raise ValueError(f"No trajectory recorded for UE {ue_id}")

        # Sort trajectory by timestamp
        traj = sorted(traj, key=lambda p: p['timestamp'])
        # If before first or after last, clamp
        if query_time <= traj[0]['timestamp']:
            return traj[0]['position']
        if query_time >= traj[-1]['timestamp']:
            return traj[-1]['position']

        # Find segment bracketing query_time
        for i in range(len(traj)-1):
            t0, t1 = traj[i]['timestamp'], traj[i+1]['timestamp']
            if t0 <= query_time <= t1:
                p0, p1 = traj[i]['position'], traj[i+1]['position']
                total = (t1 - t0).total_seconds()
                frac = (query_time - t0).total_seconds() / total if total > 0 else 0
                # Linear interpolate each coordinate
                return tuple(p0[j] + frac*(p1[j] - p0[j]) for j in range(3))

        # Fallback (shouldn't reach)
        return traj[-1]['position']
