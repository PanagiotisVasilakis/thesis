"""Data collection from NEF emulator for ML training."""
import json
import logging
import os
from datetime import datetime

import asyncio
import time
from collections import deque

SIGNAL_WINDOW_SIZE = int(os.getenv("SIGNAL_WINDOW_SIZE", "5"))

from ..clients.nef_client import NEFClient, NEFClientError

class NEFDataCollector:
    """Collect data from NEF emulator for ML training."""
    
    def __init__(self, nef_url="http://localhost:8080", username=None, password=None):
        """Initialize the data collector."""
        self.client = NEFClient(nef_url, username=username, password=password)
        self.nef_url = nef_url
        self.username = username
        self.password = password
        self.data_dir = os.path.join(os.path.dirname(__file__), 'collected_data')
        os.makedirs(self.data_dir, exist_ok=True)

        # Set up logger for this collector
        self.logger = logging.getLogger('NEFDataCollector')

        # Tracking previous metrics to compute derived features
        self._prev_speed: dict[str, float] = {}
        self._prev_cell: dict[str, str] = {}
        self._handover_counts: dict[str, int] = {}
        self._prev_signal: dict[str, dict[str, float]] = {}
        # Rolling window of recent signal values per UE for variance calculation
        self._signal_buffer: dict[str, dict[str, deque]] = {}
        # Timestamp of last handover event per UE for time_since_handover
        self._last_handover_ts: dict[str, float] = {}
    
    def login(self):
        """Authenticate with the NEF emulator via the underlying client."""
        try:
            return self.client.login()
        except NEFClientError as exc:
            self.logger.error(f"NEF authentication error: {exc}")
            return False
    
    def get_ue_movement_state(self):
        """Get current state of all UEs in movement."""
        try:
            state = self.client.get_ue_movement_state()
            if state is not None:
                ue_count = len(state.keys())
                self.logger.info(f"Retrieved state for {ue_count} moving UEs")
            return state
        except NEFClientError as exc:
            self.logger.error(f"NEF movement state error: {exc}")
            return {}
        except Exception as e:
            self.logger.error(f"Error getting UE movement state: {str(e)}")
            return {}
    
    async def collect_training_data(
        self, duration: float = 60, interval: float = 1
    ) -> list[dict]:
        """
        Collect training data for the specified duration.
        
        Args:
            duration: Collection duration in seconds
            interval: Sampling interval in seconds
        
        Returns:
            List of collected data samples
        """
        if duration <= 0:
            msg = f"duration must be positive, got {duration}"
            self.logger.warning(msg)
            raise ValueError(msg)
        if interval <= 0:
            msg = f"interval must be positive, got {interval}"
            self.logger.warning(msg)
            raise ValueError(msg)

        self.logger.info(
            f"Starting data collection for {duration} seconds at {interval}s intervals"
        )

        collected_data = []
        start_time = time.time()
        end_time = start_time + duration

        while time.time() < end_time:
            try:
                ue_state = self.get_ue_movement_state()

                for ue_id, ue_data in ue_state.items():
                    if sample := self._collect_sample(ue_id, ue_data):
                        collected_data.append(sample)

                await asyncio.sleep(interval)

            except NEFClientError as exc:
                self.logger.error(f"NEF client error during collection: {exc}")
                await asyncio.sleep(interval)
            except Exception as e:
                self.logger.error(f"Error during data collection: {str(e)}")
                await asyncio.sleep(interval)

        # Always persist a file, even when no samples were collected, so that
        # downstream processes relying on a training data artifact can operate
        # consistently.  When the dataset is empty we still create an empty JSON
        # file and log a warning for visibility.
        if not collected_data:
            self.logger.warning("No data collected; writing empty data file")

        self._save_collected_data(collected_data)

        return collected_data

    def _collect_sample(self, ue_id: str, ue_data: dict) -> dict | None:
        """Create a single training sample for the given UE."""
        if ue_data.get("Cell_id") is None:
            return None

        fv = self.client.get_feature_vector(ue_id)
        rsrps = fv.get("neighbor_rsrp_dbm", {})
        sinrs = fv.get("neighbor_sinrs", {})
        rsrqs = fv.get("neighbor_rsrqs", {})
        loads = fv.get("neighbor_cell_loads", {})
        if not isinstance(rsrps, dict):
            rsrps = {}
        if not isinstance(sinrs, dict):
            sinrs = {}
        if not isinstance(rsrqs, dict):
            rsrqs = {}
        if not isinstance(loads, dict):
            loads = {}
        cell_load = fv.get("cell_load")
        environment = fv.get("environment")
        velocity = fv.get("velocity")
        acceleration = fv.get("acceleration")
        signal_trend = fv.get("signal_trend")

        if not isinstance(cell_load, (int, float)):
            cell_load = None
        if not isinstance(environment, (int, float)):
            environment = None
        if not isinstance(velocity, (int, float)):
            velocity = None
        if not isinstance(acceleration, (int, float)):
            acceleration = None
        if not isinstance(signal_trend, (int, float)):
            signal_trend = None

        connected_cell_id = ue_data.get("Cell_id")
        rf_metrics: dict[str, dict] = {}
        best_antenna = connected_cell_id
        best_rsrp = float("-inf")
        best_sinr = float("-inf")

        for aid, rsrp in rsrps.items():
            sinr = sinrs.get(aid)
            rsrq = rsrqs.get(aid)
            load = loads.get(aid)
            metrics = {"rsrp": rsrp}
            if sinr is not None:
                metrics["sinr"] = sinr
            if rsrq is not None:
                metrics["rsrq"] = rsrq
            if load is not None:
                metrics["cell_load"] = load
            rf_metrics[aid] = metrics

            sinr_val = sinr if sinr is not None else float("-inf")
            if rsrp > best_rsrp or (rsrp == best_rsrp and sinr_val > best_sinr):
                best_rsrp = rsrp
                best_sinr = sinr_val
                best_antenna = aid

        speed = ue_data.get("speed")
        prev_speed = self._prev_speed.get(ue_id)
        if acceleration is None and prev_speed is not None and speed is not None:
            acceleration = speed - prev_speed
        self._prev_speed[ue_id] = speed if speed is not None else 0

        now_ts = time.time()
        prev_cell = self._prev_cell.get(ue_id)
        if prev_cell is not None and prev_cell != connected_cell_id:
            self._handover_counts[ue_id] = self._handover_counts.get(ue_id, 0) + 1
            self._last_handover_ts[ue_id] = now_ts
        self._prev_cell[ue_id] = connected_cell_id
        if ue_id not in self._last_handover_ts:
            self._last_handover_ts[ue_id] = now_ts
        handover_count = self._handover_counts.get(ue_id, 0)
        time_since_handover = now_ts - self._last_handover_ts.get(ue_id, now_ts)

        prev_sig = self._prev_signal.get(ue_id)
        cur_rsrp = rsrps.get(connected_cell_id)
        cur_sinr = sinrs.get(connected_cell_id)
        if not isinstance(cur_rsrp, (int, float)):
            cur_rsrp = None
        if not isinstance(cur_sinr, (int, float)):
            cur_sinr = None
        cur_rsrq = rsrqs.get(connected_cell_id)
        if not isinstance(cur_rsrq, (int, float)):
            cur_rsrq = None
        buf = self._signal_buffer.setdefault(
            ue_id,
            {
                "rsrp": deque(maxlen=SIGNAL_WINDOW_SIZE),
                "sinr": deque(maxlen=SIGNAL_WINDOW_SIZE),
            },
        )
        if cur_rsrp is not None:
            buf["rsrp"].append(cur_rsrp)
        if cur_sinr is not None:
            buf["sinr"].append(cur_sinr)

        def _std(values: deque) -> float:
            n = len(values)
            if n == 0:
                return 0.0
            mean_v = sum(values) / n
            var = sum((v - mean_v) ** 2 for v in values) / n
            return var ** 0.5

        rsrp_std = _std(buf["rsrp"])
        sinr_std = _std(buf["sinr"])
        if signal_trend is None and prev_sig:
            diffs = []
            if cur_rsrp is not None:
                diffs.append(cur_rsrp - prev_sig.get("rsrp", 0))
            if cur_sinr is not None:
                diffs.append(cur_sinr - prev_sig.get("sinr", 0))
            if cur_rsrq is not None:
                diffs.append(cur_rsrq - prev_sig.get("rsrq", 0))
            signal_trend = sum(diffs) / len(diffs) if diffs else 0
        self._prev_signal[ue_id] = {
            "rsrp": cur_rsrp or 0,
            "sinr": cur_sinr or 0,
            "rsrq": cur_rsrq or 0,
        }

        if cell_load is None:
            cell_load = len(rsrps) / 10.0 if rsrps else 0.0
        if velocity is None:
            velocity = speed
        if acceleration is None:
            acceleration = 0.0
        if signal_trend is None:
            signal_trend = 0.0
        if environment is None:
            environment = 0.0

        return {
            "timestamp": datetime.now().isoformat(),
            "ue_id": ue_id,
            "latitude": ue_data.get("latitude"),
            "altitude": ue_data.get("altitude")
            if ue_data.get("altitude") is not None
            else fv.get("altitude"),
            "longitude": ue_data.get("longitude"),
            "speed": speed,
            "velocity": velocity,
            "acceleration": acceleration,
            "cell_load": cell_load,
            "handover_count": handover_count,
            "time_since_handover": time_since_handover,
            "signal_trend": signal_trend,
            "environment": environment,
            "rsrp_stddev": rsrp_std,
            "sinr_stddev": sinr_std,
            "connected_to": connected_cell_id,
            "optimal_antenna": best_antenna,
            "rf_metrics": rf_metrics,
        }

    def _save_collected_data(self, collected_data: list) -> None:
        """Persist collected samples to disk."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.data_dir, f"training_data_{timestamp}.json")
        os.makedirs(self.data_dir, exist_ok=True)
        with open(filename, "w") as f:
            json.dump(collected_data, f, indent=2)

        if not collected_data:
            self.logger.warning(
                f"Saved empty training data file to {filename}"
            )
        else:
            self.logger.info(
                f"Collected {len(collected_data)} samples, saved to {filename}"
            )
