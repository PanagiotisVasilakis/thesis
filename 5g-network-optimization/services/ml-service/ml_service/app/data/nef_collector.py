"""Data collection from NEF emulator for ML training."""
import json
import logging
import os
from datetime import datetime

import asyncio
import time

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

        connected_cell_id = ue_data.get("Cell_id")
        rf_metrics: dict[str, dict] = {}
        best_antenna = connected_cell_id
        best_rsrp = float("-inf")
        best_sinr = float("-inf")

        for aid, rsrp in rsrps.items():
            sinr = sinrs.get(aid)
            rsrq = rsrqs.get(aid)
            rf_metrics[aid] = {"rsrp": rsrp, "sinr": sinr, "rsrq": rsrq}

            sinr_val = sinr if sinr is not None else float("-inf")
            if rsrp > best_rsrp or (rsrp == best_rsrp and sinr_val > best_sinr):
                best_rsrp = rsrp
                best_sinr = sinr_val
                best_antenna = aid

        return {
            "timestamp": datetime.now().isoformat(),
            "ue_id": ue_id,
            "latitude": ue_data.get("latitude"),
            "longitude": ue_data.get("longitude"),
            "speed": ue_data.get("speed"),
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
