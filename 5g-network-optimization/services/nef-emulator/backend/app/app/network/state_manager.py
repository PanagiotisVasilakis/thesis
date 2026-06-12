# services/nef-emulator/network/state_manager.py

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..core.env_utils import parse_env_float, parse_env_int
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
        # Read overrides from environment variables using env_utils
        a3_hysteresis_db = parse_env_float("A3_HYSTERESIS_DB", a3_hysteresis_db)
        a3_ttt_s = parse_env_float("A3_TTT_S", a3_ttt_s, min_value=0.0)
        resource_blocks = parse_env_int("RESOURCE_BLOCKS", resource_blocks, min_value=1)

        self.ue_states = {}  # supi -> {'position': (x, y, z), 'speed': v,
        # 'connected_to': ant_id, 'trajectory': [...]}
        self.antenna_list = {}  # ant_id -> AntennaModel instance
        self._antenna_aliases: Dict[str, str] = {}
        self.handover_history = []  # list of {ue_id, from, to, timestamp}
        self.logger = logging.getLogger("NetworkStateManager")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = True
        
        # Default noise floor in dBm (tunable)
        self.noise_floor_dbm = parse_env_float("NOISE_FLOOR_DBM", -100.0)

        self._a3_params = (a3_hysteresis_db, a3_ttt_s)
        self.resource_blocks = resource_blocks

        # QoS monitoring (Phase 1.1 / 1.2): track observed latency/jitter/throughput/loss
        self.qos_monitor = QoSMonitor()
        self.qos_simulator = QoSSimulator()
        self._cell_lookup = None

    def get_feature_vector(self, ue_id, *, simulate_qos: bool = True):
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
            "cell_load": antenna_loads.get(connected, 0),
            "connected_to": connected,
            "neighbor_rsrp_dbm": rsrp_dbm,
            "neighbor_sinrs": neighbor_sinrs,
            "neighbor_rsrqs": neighbor_rsrqs,
            "neighbor_cell_loads": antenna_loads,
            "rsrp_stddev": self._stddev(rsrp_dbm.values()),
            "sinr_stddev": self._stddev(neighbor_sinrs.values()),
        }
        features.update(self._trajectory_features(state))
        features.update(self._handover_features(ue_id))
        for key in (
            "service_type",
            "service_priority",
            "qos_requirements",
            "latency_requirement_ms",
            "throughput_requirement_mbps",
            "reliability_pct",
            "jitter_ms",
        ):
            if state.get(key) is not None:
                features[key] = state[key]

        if simulate_qos:
            self.simulate_qos_observation(
                ue_id,
                position=state["position"],
                speed=speed,
                connected_to=connected,
                neighbor_rsrp_dbm=rsrp_dbm,
                neighbor_cell_loads=antenna_loads,
            )

        observed_qos = self.qos_monitor.get_qos_metrics(ue_id)
        if observed_qos is not None:
            features["observed_qos"] = observed_qos
        return features

    @staticmethod
    def _stddev(values) -> float:
        numeric = [
            float(value)
            for value in values
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        ]
        if len(numeric) < 2:
            return 0.0
        mean = sum(numeric) / len(numeric)
        return math.sqrt(sum((value - mean) ** 2 for value in numeric) / len(numeric))

    @staticmethod
    def _timestamp_seconds(value: Any) -> Optional[float]:
        if isinstance(value, datetime):
            timestamp = value
        elif isinstance(value, str):
            try:
                timestamp = datetime.fromisoformat(value)
            except ValueError:
                return None
        else:
            return None
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.timestamp()

    def _trajectory_features(
        self,
        state: Dict[str, Any],
    ) -> Dict[str, float | tuple[float, float, float]]:
        trajectory = state.get("trajectory")
        if not isinstance(trajectory, list) or len(trajectory) < 2:
            return {
                "direction": (0.0, 0.0, 0.0),
                "velocity": float(state.get("speed", 0.0) or 0.0),
                "acceleration": 0.0,
                "heading_change_rate": 0.0,
                "path_curvature": 0.0,
            }

        latest = trajectory[-1]
        previous = trajectory[-2]
        latest_pos = latest.get("position") if isinstance(latest, dict) else None
        previous_pos = previous.get("position") if isinstance(previous, dict) else None
        if not latest_pos or not previous_pos:
            return {}

        dx = float(latest_pos[0]) - float(previous_pos[0])
        dy = float(latest_pos[1]) - float(previous_pos[1])
        dz = float(latest_pos[2]) - float(previous_pos[2])
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        direction = (
            dx / distance if distance > 0 else 0.0,
            dy / distance if distance > 0 else 0.0,
            dz / distance if distance > 0 else 0.0,
        )

        t1 = (
            self._timestamp_seconds(latest.get("timestamp"))
            if isinstance(latest, dict)
            else None
        )
        t0 = (
            self._timestamp_seconds(previous.get("timestamp"))
            if isinstance(previous, dict)
            else None
        )
        dt = max((t1 - t0), 1e-6) if t1 is not None and t0 is not None else 1.0
        velocity = distance / dt
        features: Dict[str, float | tuple[float, float, float]] = {
            "direction": direction,
            "velocity": velocity,
            "acceleration": 0.0,
            "heading_change_rate": 0.0,
            "path_curvature": 0.0,
        }

        if len(trajectory) >= 3:
            before_previous = trajectory[-3]
            prior_pos = (
                before_previous.get("position")
                if isinstance(before_previous, dict)
                else None
            )
            prior_time = (
                self._timestamp_seconds(before_previous.get("timestamp"))
                if isinstance(before_previous, dict)
                else None
            )
            if prior_pos and prior_time is not None and t0 is not None:
                pdx = float(previous_pos[0]) - float(prior_pos[0])
                pdy = float(previous_pos[1]) - float(prior_pos[1])
                pdz = float(previous_pos[2]) - float(prior_pos[2])
                previous_distance = math.sqrt(pdx * pdx + pdy * pdy + pdz * pdz)
                previous_dt = max(t0 - prior_time, 1e-6)
                previous_velocity = previous_distance / previous_dt
                features["acceleration"] = (velocity - previous_velocity) / dt
                current_heading = math.atan2(dy, dx)
                previous_heading = math.atan2(pdy, pdx)
                heading_delta = abs(
                    (current_heading - previous_heading + math.pi)
                    % (2 * math.pi)
                    - math.pi
                )
                features["heading_change_rate"] = heading_delta / dt
                features["path_curvature"] = heading_delta / max(distance, 1e-6)

        return features

    def _handover_features(self, ue_id: str) -> Dict[str, Any]:
        history = [
            dict(event)
            for event in self.handover_history
            if event.get("ue_id") == ue_id
        ]
        features: Dict[str, Any] = {
            "handover_count": len(history),
            "handover_history": history[-10:],
        }
        if history:
            timestamp = self._timestamp_seconds(history[-1].get("timestamp"))
            if timestamp is not None:
                now = datetime.now(timezone.utc).timestamp()
                features["time_since_handover"] = max(0.0, now - timestamp)
        else:
            features["time_since_handover"] = 0.0
        return features

    def peek_feature_vector(self, ue_id):
        """Return ML features without mutating synthetic QoS observations."""
        return self.get_feature_vector(ue_id, simulate_qos=False)

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

    def simulate_qos_observation(
        self,
        ue_id: str,
        *,
        position,
        speed: float,
        connected_to: Optional[str],
        neighbor_rsrp_dbm: Dict[str, float],
        neighbor_cell_loads: Dict[str, int],
    ) -> None:
        """Generate and record one synthetic QoS observation for an explicit tick."""
        try:
            simulation_context = {
                "position": position,
                "speed": speed,
                "connected_to": connected_to,
                "neighbor_rsrp_dbm": neighbor_rsrp_dbm,
                "neighbor_cell_loads": neighbor_cell_loads,
            }
            simulated = self.qos_simulator.estimate(simulation_context)
            if simulated:
                self.qos_monitor.update_qos_metrics(ue_id, simulated)
        except Exception:  # noqa: BLE001 - defensive
            self.logger.exception("Failed to simulate QoS metrics for UE %s", ue_id)

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
        except Exception as exc:  # noqa: BLE001 - defensive guard
            self.logger.warning("Cell lookup failed for %s: %s", cell_key, exc)
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
