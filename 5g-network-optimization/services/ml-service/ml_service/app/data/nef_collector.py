"""Data collection from NEF emulator for ML training."""
import json
import logging
import os
from datetime import datetime

import time

from ..clients.nef_client import NEFClient

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
        return self.client.login()
    
    def get_ue_movement_state(self):
        """Get current state of all UEs in movement."""
        try:
            state = self.client.get_ue_movement_state()
            if state is not None:
                ue_count = len(state.keys())
                self.logger.info(f"Retrieved state for {ue_count} moving UEs")
            return state
        except Exception as e:
            self.logger.error(f"Error getting UE movement state: {str(e)}")
            return {}
    
    def collect_training_data(self, duration=60, interval=1):
        """
        Collect training data for the specified duration.
        
        Args:
            duration: Collection duration in seconds
            interval: Sampling interval in seconds
        
        Returns:
            List of collected data samples
        """
        self.logger.info(f"Starting data collection for {duration} seconds at {interval}s intervals")
        
        # Initialize data collection
        collected_data = []
        start_time = time.time()
        end_time = start_time + duration
        
        while time.time() < end_time:
            try:
                # Get current UE movement state
                ue_state = self.get_ue_movement_state()
                
                # Process each UE
                for ue_id, ue_data in ue_state.items():
                    # Skip UEs not connected to any cell
                    if ue_data.get('Cell_id') is None:
                        continue
                    
                    # For this initial version, we'll assume current cell is optimal
                    # In a real implementation, this would use more sophisticated logic
                    optimal_cell_id = ue_data.get('Cell_id')
                    
                    fv = self.client.get_feature_vector(ue_id)
                    rf_metrics = {}
                    rsrps = fv.get('neighbor_rsrp_dbm', {})
                    sinrs = fv.get('neighbor_sinrs', {})
                    for aid, rsrp in rsrps.items():
                        rf_metrics[aid] = {
                            'rsrp': rsrp,
                            'sinr': sinrs.get(aid)
                        }

                    # Create a data sample
                    sample = {
                        'timestamp': datetime.now().isoformat(),
                        'ue_id': ue_id,
                        'latitude': ue_data.get('latitude'),
                        'longitude': ue_data.get('longitude'),
                        'speed': ue_data.get('speed'),
                        'connected_to': optimal_cell_id,
                        'optimal_antenna': optimal_cell_id,
                        'rf_metrics': rf_metrics,
                    }
                    
                    collected_data.append(sample)
                
                # Sleep until next sample
                time.sleep(interval)
            
            except Exception as e:
                self.logger.error(f"Error during data collection: {str(e)}")
                time.sleep(interval)
        
        # Save collected data
        if collected_data:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(self.data_dir, f'training_data_{timestamp}.json')
            os.makedirs(self.data_dir, exist_ok=True)
            
            with open(filename, 'w') as f:
                json.dump(collected_data, f, indent=2)
            
            self.logger.info(f"Collected {len(collected_data)} samples, saved to {filename}")
        else:
            self.logger.warning("No data collected")
            
        return collected_data
