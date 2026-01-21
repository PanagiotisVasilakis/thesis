"""Shared runtime utilities for coordinating handover decisions.

This module holds a singleton ``HandoverRuntime`` that keeps the
``NetworkStateManager`` and ``HandoverEngine`` instances used across FastAPI
endpoints and background threads.  It also exposes helpers to translate
geographic coordinates into the local coordinate system expected by the RF
models so that UE movement updates can feed the ML handover engine.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Tuple

try:  # pragma: no cover - optional dependency in container image
    from antenna_models.models import MacroCellModel as _AntennaModel  # type: ignore
except ImportError:  # pragma: no cover - fallback when antenna_models is unavailable
    # Note: math already imported at line 13

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
try:
    DEFAULT_CELL_ALTITUDE_M = float(os.environ.get("DEFAULT_CELL_ALTITUDE_M", 25.0))
except ValueError:
    DEFAULT_CELL_ALTITUDE_M = 25.0
try:
    DEFAULT_UE_ALTITUDE_M = float(os.environ.get("DEFAULT_UE_ALTITUDE_M", 1.5))
except ValueError:
    DEFAULT_UE_ALTITUDE_M = 1.5

# Network configuration defaults - can be overridden via environment variables
try:
    DEFAULT_CARRIER_HZ = float(os.environ.get("DEFAULT_CARRIER_HZ", 3.5e9))
except ValueError:
    DEFAULT_CARRIER_HZ = 3.5e9
try:
    DEFAULT_TX_POWER_DBM = float(os.environ.get("DEFAULT_TX_POWER_DBM", 40.0))
except ValueError:
    DEFAULT_TX_POWER_DBM = 40.0
try:
    TRAJECTORY_LIMIT = int(os.environ.get("TRAJECTORY_LIMIT", 900))
except ValueError:
    TRAJECTORY_LIMIT = 900  # keep ~15 minutes of 1 Hz samples

# Speed mapping constants (m/s)
try:
    HIGH_SPEED_MPS = float(os.environ.get("HIGH_SPEED_MPS", 10.0))
except ValueError:
    HIGH_SPEED_MPS = 10.0  # Vehicular speed
try:
    LOW_SPEED_MPS = float(os.environ.get("LOW_SPEED_MPS", 1.0))
except ValueError:
    LOW_SPEED_MPS = 1.0    # Walking speed


class HandoverRuntime:
    """Keep shared ML handover state in a thread-safe helper."""

    def __init__(self) -> None:
        self.state_manager = NetworkStateManager()
        self.engine = HandoverEngine(self.state_manager)
        self._lock = threading.Lock()
        self._ref_lat: Optional[float] = None
        self._ref_lon: Optional[float] = None
        self._cells_by_key: Dict[str, dict] = {}
        self._cells_by_alias: Dict[str, str] = {}
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = True

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
                self.logger.debug("ensure_topology invoked with no cells; antenna_list_size=%s", len(self.state_manager.antenna_list))
                return

            if self._ref_lat is None or self._ref_lon is None:
                first = cells_list[0]
                self._ref_lat = first.get("latitude") or 0.0
                self._ref_lon = first.get("longitude") or 0.0

            self.logger.debug(
                "ensure_topology received %d cells; ref_lat=%s ref_lon=%s",
                len(cells_list),
                self._ref_lat,
                self._ref_lon,
            )
            for cell in cells_list:
                key = self._cell_key(cell.get("id"))
                if key is None:
                    self.logger.warning(
                        "ensure_topology skipping cell without primary id: %s",
                        cell,
                    )
                else:
                    self.logger.debug(
                        "ensure_topology evaluating cell id=%s cell_id=%s name=%s",
                        key,
                        cell.get("cell_id"),
                        cell.get("name"),
                    )
                if key in self.state_manager.antenna_list:
                    # Update cache to ensure metadata stays fresh
                    self._cells_by_key[key] = cell
                    before_aliases = len(self._cells_by_alias)
                    self._register_cell_aliases(cell, key)
                    after_aliases = len(self._cells_by_alias)
                    self.logger.debug(
                        "ensure_topology refreshed existing antenna entry id=%s alias_delta=%s",
                        key,
                        after_aliases - before_aliases,
                    )
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
                before_aliases = len(self._cells_by_alias)
                self._register_cell_aliases(cell, key)
                after_aliases = len(self._cells_by_alias)
                self.logger.debug(
                    "ensure_topology registered antenna id=%s position=%s total_antennas=%d alias_delta=%s",
                    key,
                    position,
                    len(self.state_manager.antenna_list),
                    after_aliases - before_aliases,
                )
            self.state_manager.register_cell_lookup(self.get_cell_by_key)
            self.logger.info(
                "ensure_topology complete; antenna_list_size=%d aliases=%d",
                len(self.state_manager.antenna_list),
                len(self._cells_by_alias),
            )

    def reset_topology(self) -> None:
        """Clear cached topology/UE state so a scenario import can start clean."""
        with self._lock:
            self.state_manager.antenna_list.clear()
            self.state_manager.ue_states.clear()
            self.state_manager.handover_history.clear()
            if hasattr(self.state_manager, "_antenna_aliases"):
                self.state_manager._antenna_aliases.clear()
            self._cells_by_key.clear()
            self._cells_by_alias.clear()
            self._ref_lat = None
            self._ref_lon = None
            # Clear per-UE TTT timers to avoid stale state
            self.engine.clear_all_ttt_timers()
            self.state_manager.register_cell_lookup(lambda *_args, **_kwargs: None)
            self.logger.info("reset_topology completed; antenna_list_size=%d", len(self.state_manager.antenna_list))

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
        """Make handover decision without blocking other threads during HTTP call.
        
        Uses Read-Copy-Update pattern:
        1. Read feature vector under lock (fast)
        2. Release lock for HTTP call to ML service (can take 5+ seconds)
        3. Re-acquire lock to apply decision (fast)
        
        This prevents other UE movement threads from being blocked while
        waiting for ML service responses.
        """
        # Step 1: Read feature vector under lock
        with self._lock:
            try:
                fv = self.state_manager.get_feature_vector(supi)
            except KeyError:
                self.logger.warning("UE %s not found for handover decision", supi)
                return None
            current_cell = fv.get("connected_to")
        
        # Step 2: Make HTTP call OUTSIDE lock (can take 5+ seconds)
        # This allows other threads to proceed with their state updates
        decision = self.engine.decide_with_features(supi, fv)
        
        # Step 3: Apply decision if still valid
        if decision is None:
            return None
        
        with self._lock:
            # Verify state hasn't changed significantly during HTTP call
            try:
                current_fv = self.state_manager.get_feature_vector(supi)
                if current_fv.get("connected_to") != current_cell:
                    self.logger.info(
                        "UE %s cell changed during ML call (%s -> %s), skipping apply",
                        supi, current_cell, current_fv.get("connected_to")
                    )
                    return None  # State changed, let caller retry on next iteration
            except KeyError:
                self.logger.warning("UE %s removed during ML call", supi)
                return None  # UE was removed
            
            result = self.engine.apply_decision(supi, decision, fv)
            
            # Merge ML confidence from original decision into result
            # This ensures the confidence flows through to ue_movement.py
            if result is not None:
                result["confidence"] = decision.get("confidence")
                use_ml = getattr(self.engine, "use_ml", False)
                result["source"] = decision.get("source", "ml" if use_ml else "a3")
            
            return result

    def get_cell_by_key(self, key: Optional[str]) -> Optional[dict]:
        if key is None:
            return None
        with self._lock:
            lookup_key = self.state_manager.resolve_antenna_id(key)
            if lookup_key in self._cells_by_key:
                return self._cells_by_key.get(lookup_key)

            alt = self._cells_by_alias.get(str(key)) or self._cells_by_alias.get(str(key).lower())
            if alt:
                return self._cells_by_key.get(alt)

            return self._cells_by_key.get(str(key))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _cell_key(self, cell_id: Optional[int]) -> Optional[str]:
        if cell_id is None:
            return None
        return str(cell_id)

    def _register_cell_aliases(self, cell: dict, canonical: str) -> None:
        aliases = set()
        cell_id = cell.get("id")
        if cell_id is not None:
            cid = str(cell_id)
            aliases.update({
                f"antenna_{cid}",
                f"antenna-{cid}",
                f"antenna{cid}",
                f"cell_{cid}",
                f"cell{cid}",
            })

        cell_identifier = cell.get("cell_id")
        if cell_identifier:
            cid_str = str(cell_identifier)
            aliases.update({cid_str, cid_str.lower()})

        name = cell.get("name")
        if name:
            name_str = str(name)
            aliases.update({name_str, name_str.lower()})

        new_aliases = []
        for alias in aliases:
            if not alias or alias == canonical:
                continue
            previous = self._cells_by_alias.get(alias)
            self._cells_by_alias[alias] = canonical
            self.state_manager.register_antenna_alias(alias, canonical)
            if previous != canonical:
                new_aliases.append(alias)
        if new_aliases:
            preview = ", ".join(sorted(new_aliases)[:5])
            if len(new_aliases) > 5:
                preview = f"{preview}, ..."
            self.logger.info(
                "registered aliases for antenna %s; count=%d sample=[%s]",
                canonical,
                len(new_aliases),
                preview,
            )

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
            return HIGH_SPEED_MPS
        if label == "LOW":
            return LOW_SPEED_MPS
        try:
            return float(label)
        except (TypeError, ValueError):
            return 0.0


# Global singleton shared across the application
runtime = HandoverRuntime()

__all__ = ["runtime", "HandoverRuntime"]
