# services/nef-emulator/network/state_manager.py

import logging
import os
from datetime import datetime, timezone
import math
from typing import Dict, Optional

from ..monitoring import QoSMonitor
from ..simulation.qos_simulator import QoSSimulator


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
        self._antenna_aliases: Dict[str, str] = {}
        self.handover_history = []  # list of {ue_id, from, to, timestamp}
        self.logger = logging.getLogger("NetworkStateManager")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = True
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

        # QoS monitoring (Phase 1.1 / 1.2): track observed latency/jitter/throughput/loss
        self.qos_monitor = QoSMonitor()
        self.qos_simulator = QoSSimulator()
        self._cell_lookup = None

    def get_feature_vector(self, ue_id):
        """
        Return a dict of features for ML based on current state.
        """
        state = self.ue_states.get(ue_id)
        if not state:
            raise KeyError(f"UE {ue_id} not found")

        x, y, z = state["position"]
        speed = state.get("speed", 0.0)
        connected = self.resolve_antenna_id(state.get("connected_to"))
        state["connected_to"] = connected

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
            conn = self.resolve_antenna_id(u_state.get("connected_to"))
            if conn != u_state.get("connected_to"):
                u_state["connected_to"] = conn
            if conn in antenna_loads:
                antenna_loads[conn] += 1
        antenna_loads = {aid: antenna_loads[aid] for aid, _ in ordered}

        features: Dict[str, object] = {
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

        # Generate synthetic QoS observations for the current snapshot.
        try:
            simulation_context = {
                "position": state["position"],
                "speed": speed,
                "connected_to": connected,
                "neighbor_rsrp_dbm": rsrp_dbm,
                "neighbor_cell_loads": antenna_loads,
            }
            simulated = self.qos_simulator.estimate(simulation_context)
            if simulated:
                self.qos_monitor.update_qos_metrics(ue_id, simulated)
        except Exception:  # noqa: BLE001 - defensive
            self.logger.exception("Failed to simulate QoS metrics for UE %s", ue_id)

        observed_qos = self.qos_monitor.get_qos_metrics(ue_id)
        if observed_qos is not None:
            features["observed_qos"] = observed_qos
        return features

    # ------------------------------------------------------------------
    # QoS helpers
    # ------------------------------------------------------------------
    def record_qos_measurement(self, ue_id: str, metrics: Dict[str, float]) -> None:
        """Record a QoS measurement for ``ue_id``.

        Parameters
        ----------
        ue_id: str
            UE identifier.
        metrics: Dict[str, float]
            Dict containing "latency_ms", "jitter_ms", "throughput_mbps",
            and "packet_loss_rate".
        """

        try:
            self.qos_monitor.update_qos_metrics(ue_id, metrics)
        except Exception:  # noqa: BLE001 - log and continue
            self.logger.exception("Failed to record QoS metrics for UE %s", ue_id)

    def get_observed_qos(self, ue_id: str) -> Optional[Dict[str, float]]:
        """Return observed QoS aggregates for ``ue_id`` if available."""

        return self.qos_monitor.get_qos_metrics(ue_id)

    def apply_handover_decision(self, ue_id, target_antenna_id):
        """Apply an ML-driven handover decision or rule-based one."""
        state = self.ue_states.get(ue_id)
        if not state:
            raise KeyError(f"UE {ue_id} not found")
        prev = self.resolve_antenna_id(state.get("connected_to"))
        if prev != state.get("connected_to"):
            state["connected_to"] = prev

        resolved_target = self.resolve_antenna_id(target_antenna_id)
        if resolved_target == prev:
            self.logger.info("Handover for %s skipped; already connected to %s", ue_id, resolved_target)
            return None

        if resolved_target not in self.antenna_list:
            raise KeyError(f"Antenna {target_antenna_id} unknown")

        # The A3 rule is evaluated by the HandoverEngine when machine learning
        # is disabled. NetworkStateManager simply applies the decision here.

        state["connected_to"] = resolved_target

        ev = {
            "ue_id": ue_id,
            "from": prev,
            "to": resolved_target,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.handover_history.append(ev)
        self.logger.info("Handover for %s: %s -> %s", ue_id, prev, resolved_target)
        return ev

    # ------------------------------------------------------------------
    # Cell metadata helpers
    # ------------------------------------------------------------------
    def register_cell_lookup(self, lookup_fn):
        """Allow external runtimes to provide cell metadata lookup."""
        self._cell_lookup = lookup_fn

    def get_cell(self, cell_key):
        """Return cell metadata if a lookup hook has been registered."""
        if self._cell_lookup is None or cell_key is None:
            return None
        try:
            return self._cell_lookup(cell_key)
        except Exception:  # noqa: BLE001 - defensive guard
            return None

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

    # ------------------------------------------------------------------
    # Antenna alias helpers
    # ------------------------------------------------------------------
    def register_antenna_alias(self, alias: Optional[str], canonical: Optional[str]) -> None:
        """Register an alternative identifier for a known antenna."""
        if alias is None or canonical is None:
            return

        alias_key = str(alias)
        canonical_key = str(canonical)
        if not alias_key:
            return

        self._antenna_aliases[alias_key] = canonical_key
        self._antenna_aliases[alias_key.lower()] = canonical_key

    def resolve_antenna_id(self, antenna_id: Optional[str]) -> Optional[str]:
        """Normalise antenna identifiers using registered aliases."""
        if antenna_id is None:
            return None

        candidate = str(antenna_id)
        if candidate in self.antenna_list:
            return candidate

        alias = self._antenna_aliases.get(candidate)
        if alias and alias in self.antenna_list:
            return alias

        lowered = candidate.lower()
        alias = self._antenna_aliases.get(lowered)
        if alias and alias in self.antenna_list:
            return alias

        if lowered.startswith("antenna"):
            digits = "".join(ch for ch in candidate if ch.isdigit())
            if digits and digits in self.antenna_list:
                return digits

        return candidate
