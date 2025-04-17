# services/nef-emulator/network/state_manager.py

import logging
from datetime import datetime
import math

class NetworkStateManager:
    """Manages UEs, antennas, connections, and history for ML integration."""

    def __init__(self):
        # existing initialization...
        self.ue_states = {}          # supi -> { 'position':(x,y,z), 'speed':v, 'connected_to':ant_id, ... }
        self.antenna_list = {}       # ant_id -> AntennaModel instance
        self.handover_history = []   # list of {ue_id, from, to, timestamp}
        self.logger = logging.getLogger('NetworkStateManager')
        # Default noise floor in dBm (tunable)
        self.noise_floor_dbm = -100.0

    # … existing methods …

    def get_feature_vector(self, ue_id):
        """
        Return a dict of features for ML based on current state.
        {
          'ue_id': str,
          'latitude': float, 'longitude': float, 'altitude': float,
          'speed': float,
          'connected_to': str,
          'neighbor_rsrs': {ant_id: rsrp, …},
          'neighbor_sinrs': {ant_id: sinr, …}
        }
        """
        state = self.ue_states.get(ue_id)
        if not state:
            raise KeyError(f"UE {ue_id} not found")

        # Basic kinematics
        x, y, z = state['position']
        speed = state.get('speed', 0.0)
        connected = state.get('connected_to')

        # Collect RF metrics for all antennas
        # 1) Gather RSRP in dBm for all antennas
        rsrp_dbm = {
            ant_id: antenna.rsrp_dbm(state['position'])
            for ant_id, antenna in self.antenna_list.items()
        }

        # 2) Convert to linear mW
        rsrp_mw = {aid: 10**(dbm/10.0) for aid, dbm in rsrp_dbm.items()}

        # 3) Noise in mW
        noise_mw = 10**(self.noise_floor_dbm/10.0)

        # 4) Compute SINR for each antenna: 
        #    SINR = signal / (noise + sum(interference from other Rsrp))
        neighbor_sinrs = {}
        for aid, sig_mw in rsrp_mw.items():
            interf_mw = sum(m for other, m in rsrp_mw.items() if other != aid)
            sinr_linear = sig_mw / (noise_mw + interf_mw) if (noise_mw + interf_mw) > 0 else 0.0
            neighbor_sinrs[aid] = 10 * math.log10(sinr_linear) if sinr_linear > 0 else -float('inf')

        # 5) Keep RSRP (dBm) as neighbor_rsrs
        neighbor_rsrs = rsrp_dbm

        features = {
            'ue_id':        ue_id,
            'latitude':     x,
            'longitude':    y,
            'altitude':     z,
            'speed':        speed,
            'connected_to': connected,
            'neighbor_rsrs': neighbor_rsrs,
            'neighbor_sinrs': neighbor_sinrs,
        }
        return features

    def apply_handover_decision(self, ue_id, target_antenna_id):
        """
        Apply an ML‑driven handover decision.
        Updates the UE’s connection and logs the event.
        """
        state = self.ue_states.get(ue_id)
        if not state:
            raise KeyError(f"UE {ue_id} not found")
        prev = state.get('connected_to')
        if target_antenna_id not in self.antenna_list:
            raise KeyError(f"Antenna {target_antenna_id} unknown")

        # Update connection
        state['connected_to'] = target_antenna_id

        # Log handover
        ev = {
            'ue_id':     ue_id,
            'from':      prev,
            'to':        target_antenna_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        self.handover_history.append(ev)
        self.logger.info(f"Handover for {ue_id}: {prev} → {target_antenna_id}")
        return ev
