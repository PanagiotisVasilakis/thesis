"""Data collection from NEF emulator for ML training."""
import requests
import json
import pandas as pd
import time
import os
import logging
from datetime import datetime

class NEFDataCollector:
    """Collect data from NEF emulator for ML training."""
    
    def __init__(self, nef_url="http://localhost:8080", username=None, password=None):
        """Initialize the data collector."""
        self.nef_url = nef_url
        self.username = username
        self.password = password
        self.token = None
        self.headers = {}
        self.data_dir = os.path.join(os.path.dirname(__file__), 'collected_data')
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger('NEFDataCollector')
    
    def login(self):
        """Login to NEF emulator and get access token."""
        if not self.username or not self.password:
            self.logger.warning("No credentials provided, skipping authentication")
            return False
        
        try:
            login_url = f"{self.nef_url}/api/v1/login/access-token"
            response = requests.post(
                login_url,
                data={
                    "username": self.username,
                    "password": self.password
                }
            )
            
            if response.status_code == 200:
                self.token = response.json().get("access_token")
                self.headers = {"Authorization": f"Bearer {self.token}"}
                self.logger.info("Successfully logged in to NEF emulator")
                return True
            else:
                self.logger.error(f"Login failed: {response.status_code} - {response.text}")
                return False
        
        except Exception as e:
            self.logger.error(f"Login error: {str(e)}")
            return False
    
    def get_ue_movement_state(self):
        """Get current state of all UEs in movement."""
        try:
            state_url = f"{self.nef_url}/api/v1/ue-movement/state-ues"
            response = requests.get(state_url, headers=self.headers)
            
            if response.status_code == 200:
                state = response.json()
                ue_count = len(state.keys())
                self.logger.info(f"Retrieved state for {ue_count} moving UEs")
                return state
            else:
                self.logger.error(f"Failed to get UE movement state: {response.status_code} - {response.text}")
                return {}
        
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
                    
                    # Create a data sample
                    sample = {
                        'timestamp': datetime.now().isoformat(),
                        'ue_id': ue_id,
                        'latitude': ue_data.get('latitude'),
                        'longitude': ue_data.get('longitude'),
                        'speed': ue_data.get('speed'),
                        'connected_to': optimal_cell_id,
                        'optimal_antenna': optimal_cell_id,
                        # We would add rf_metrics here in a real implementation
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
