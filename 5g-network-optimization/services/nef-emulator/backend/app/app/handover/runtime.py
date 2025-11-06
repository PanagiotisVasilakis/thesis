"""Shared runtime utilities for coordinating handover decisions.

This module holds a singleton ``HandoverRuntime`` that keeps the
``NetworkStateManager`` and ``HandoverEngine`` instances used across FastAPI
endpoints and background threads.  It also exposes helpers to translate
geographic coordinates into the local coordinate system expected by the RF
models so that UE movement updates can feed the ML handover engine.
"""

from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Tuple

try:  # pragma: no cover - optional dependency in container image
    from antenna_models.models import MacroCellModel as _AntennaModel  # type: ignore
except ImportError:  # pragma: no cover - fallback when antenna_models is unavailable
    import math

    class _AntennaModel:
        """Lightweight antenna abstraction used when rf_models package is absent."""

        def __init__(self, ant_id: str, position, frequency_hz: float, tx_power_dbm: float):
            self.ant_id = ant_id
            self.position = position
            self.frequency_hz = frequency_hz
            self.tx_power_dbm = tx_power_dbm

        def rsrp_dbm(self, ue_position, include_shadowing: bool = False):
            dx = self.position[0] - ue_position[0]
            dy = self.position[1] - ue_position[1]
            dz = self.position[2] - ue_position[2]
            distance = math.sqrt(dx * dx + dy * dy + dz * dz)
            distance = max(distance, 1.0)
            path_loss = 32.45 + 20 * math.log10(self.frequency_hz / 1e9) + 20 * math.log10(distance / 1000.0)
            return self.tx_power_dbm - path_loss

from app.handover.engine import HandoverEngine
from app.network.state_manager import NetworkStateManager

EARTH_RADIUS_M = 6_371_000.0
DEFAULT_CELL_ALTITUDE_M = 25.0
DEFAULT_UE_ALTITUDE_M = 1.5
DEFAULT_CARRIER_HZ = 3.5e9
DEFAULT_TX_POWER_DBM = 40.0
TRAJECTORY_LIMIT = 900  # keep ~15 minutes of 1 Hz samples


class HandoverRuntime:
    """Keep shared ML handover state in a thread-safe helper."""

    def __init__(self) -> None:
        self.state_manager = NetworkStateManager()
        self.engine = HandoverEngine(self.state_manager)
        self._lock = threading.Lock()
        self._ref_lat: Optional[float] = None
        self._ref_lon: Optional[float] = None
        self._cells_by_key: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Topology management
    # ------------------------------------------------------------------
    def ensure_topology(self, cells: Iterable[dict]) -> None:
        """Load cell definitions into the shared state manager.

        The RF models expect Cartesian coordinates in metres. We lazily
        initialise a local tangent plane reference the first time we see cell
        coordinates and reuse it for every subsequent conversion to maintain
        consistency across threads.
        """

        with self._lock:
            cells_list = list(cells)
            if not cells_list:
                return

            if self._ref_lat is None or self._ref_lon is None:
                first = cells_list[0]
                self._ref_lat = first.get("latitude") or 0.0
                self._ref_lon = first.get("longitude") or 0.0

            for cell in cells_list:
                key = self._cell_key(cell.get("id"))
                if key in self.state_manager.antenna_list:
                    # Update cache to ensure metadata stays fresh
                    self._cells_by_key[key] = cell
                    continue

                position = self._to_local(
                    cell.get("latitude"), cell.get("longitude"), DEFAULT_CELL_ALTITUDE_M
                )
                self.state_manager.antenna_list[key] = _AntennaModel(
                    key,
                    position,
                    DEFAULT_CARRIER_HZ,
                    DEFAULT_TX_POWER_DBM,
                )
                self._cells_by_key[key] = cell

    # ------------------------------------------------------------------
    # UE state
    # ------------------------------------------------------------------
    def upsert_ue_state(
        self,
        supi: str,
        latitude: float,
        longitude: float,
        speed_label: str,
        current_cell_id: Optional[int],
        fallback_cell_id: Optional[int],
    ) -> Tuple[Optional[str], Tuple[float, float, float]]:
        """Update the UE position and return the serving cell key.

        Parameters
        ----------
        supi:
            UE identifier.
        latitude, longitude:
            Latest geographic position.
        speed_label:
            The textual speed stored in the NEF database ("LOW"/"HIGH").
        current_cell_id:
            Database identifier of the cell the UE is currently attached to
            according to the NEF state machine.
        fallback_cell_id:
            Candidate cell identifier derived from the proximity check. Used
            when the UE has not yet attached to any cell so the ML engine can
            still generate a feature vector.
        """

        with self._lock:
            if self._ref_lat is None or self._ref_lon is None:
                self._ref_lat = latitude
                self._ref_lon = longitude

            position = self._to_local(latitude, longitude, DEFAULT_UE_ALTITUDE_M)
            speed = self._speed_to_mps(speed_label)

            preferred = current_cell_id if current_cell_id is not None else fallback_cell_id
            conn_key = self._cell_key(preferred)

            ue_state = self.state_manager.ue_states.get(supi)
            if ue_state is None:
                ue_state = {
                    "position": position,
                    "speed": speed,
                    "connected_to": conn_key,
                    "trajectory": [],
                }
                if conn_key is None and self.state_manager.antenna_list:
                    ue_state["connected_to"] = next(iter(self.state_manager.antenna_list))
                self.state_manager.ue_states[supi] = ue_state
            else:
                ue_state["position"] = position
                ue_state["speed"] = speed
                if conn_key is not None:
                    ue_state["connected_to"] = conn_key

            traj = ue_state.setdefault("trajectory", [])
            traj.append({
                "timestamp": datetime.now(timezone.utc),
                "position": position,
            })
            if len(traj) > TRAJECTORY_LIMIT:
                del traj[: len(traj) - TRAJECTORY_LIMIT]

            return ue_state.get("connected_to"), position

    # ------------------------------------------------------------------
    # Decision helpers
    # ------------------------------------------------------------------
    def decide_handover(self, supi: str):
        with self._lock:
            return self.engine.decide_and_apply(supi)

    def get_cell_by_key(self, key: Optional[str]) -> Optional[dict]:
        if key is None:
            return None
        with self._lock:
            return self._cells_by_key.get(key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _cell_key(self, cell_id: Optional[int]) -> Optional[str]:
        if cell_id is None:
            return None
        return str(cell_id)

    def _to_local(self, lat: Optional[float], lon: Optional[float], altitude: float) -> Tuple[float, float, float]:
        if lat is None or lon is None:
            return (0.0, 0.0, altitude)
        if self._ref_lat is None or self._ref_lon is None:
            self._ref_lat = lat
            self._ref_lon = lon

        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        ref_lat_rad = math.radians(self._ref_lat)
        ref_lon_rad = math.radians(self._ref_lon)
        avg_lat = (lat_rad + ref_lat_rad) / 2.0
        x = (lon_rad - ref_lon_rad) * math.cos(avg_lat) * EARTH_RADIUS_M
        y = (lat_rad - ref_lat_rad) * EARTH_RADIUS_M
        return (x, y, altitude)

    @staticmethod
    def _speed_to_mps(speed_label: Optional[str]) -> float:
        if speed_label is None:
            return 0.0
        label = speed_label.strip().upper()
        if label == "HIGH":
            return 10.0
        if label == "LOW":
            return 1.0
        try:
            return float(label)
        except (TypeError, ValueError):
            return 0.0


# Global singleton shared across the application
runtime = HandoverRuntime()

__all__ = ["runtime", "HandoverRuntime"]
