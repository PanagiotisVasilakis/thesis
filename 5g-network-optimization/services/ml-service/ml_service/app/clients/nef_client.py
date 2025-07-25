# File: services/ml-service/app/clients/nef_client.py

"""Client for interacting with the NEF emulator."""
import requests
import logging
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin


class NEFClient:
    """Client for the NEF emulator API."""

    def __init__(
        self, base_url: str, username: str = None, password: str = None
    ):
        """Initialize the NEF client."""
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = None
        self.logger = logging.getLogger(__name__)

    def login(self) -> bool:
        """Authenticate with the NEF emulator."""
        if not self.username or not self.password:
            self.logger.warning(
                "No credentials provided, skipping authentication"
            )
            return False

        try:
            login_url = urljoin(self.base_url, "/api/v1/login/access-token")
            response = requests.post(
                login_url,
                data={"username": self.username, "password": self.password},
                timeout=10,
            )

            if response.status_code == 200:
                self.token = response.json().get("access_token")
                self.logger.info(
                    "Successfully authenticated with NEF emulator"
                )
                return True
            else:
                self.logger.error(
                    "Authentication failed: %s - %s",
                    response.status_code,
                    response.text,
                )
                return False
        except requests.exceptions.RequestException as exc:
            self.logger.error("HTTP error during authentication: %s", exc)
            return False
        except Exception as e:
            self.logger.error(f"Error during authentication: {str(e)}")
            return False

    def get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication token if available."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def generate_mobility_pattern(
        self,
        model_type: str,
        ue_id: str,
        parameters: Dict[str, Any],
        duration: float = 300.0,
        time_step: float = 1.0,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Generate a mobility pattern using the NEF emulator API.

        Args:
            model_type: Type of mobility model (linear, l_shaped)
            ue_id: UE identifier
            parameters: Model-specific parameters
            duration: Duration in seconds
            time_step: Time step in seconds

        Returns:
            List of path points or None if request fails
        """
        try:
            url = urljoin(self.base_url, "/api/v1/mobility-patterns/generate")

            payload = {
                "model_type": model_type,
                "ue_id": ue_id,
                "duration": duration,
                "time_step": time_step,
                "parameters": parameters,
            }

            response = requests.post(
                url, json=payload, headers=self.get_headers(), timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                self.logger.error(
                    "Error generating mobility pattern: %s - %s",
                    response.status_code,
                    response.text,
                )
                return None
        except requests.exceptions.RequestException as exc:
            self.logger.error(
                "HTTP error generating mobility pattern: %s", exc
            )
            return None
        except Exception as e:
            self.logger.error(f"Error in generate_mobility_pattern: {str(e)}")
            return None

    def get_ue_movement_state(self) -> Dict[str, Any]:
        """Get current state of all UEs in movement."""
        try:
            url = urljoin(self.base_url, "/api/v1/ue-movement/state-ues")

            response = requests.get(
                url, headers=self.get_headers(), timeout=10
            )

            if response.status_code == 200:
                return response.json()
            else:
                self.logger.error(
                    "Error getting UE movement state: %s - %s",
                    response.status_code,
                    response.text,
                )
                return {}
        except requests.exceptions.RequestException as exc:
            self.logger.error("HTTP error getting movement state: %s", exc)
            return {}
        except Exception as e:
            self.logger.error(f"Error in get_ue_movement_state: {str(e)}")
            return {}

    def get_feature_vector(self, ue_id: str) -> Dict[str, Any]:
        """Return the ML feature vector for the given UE."""
        try:
            url = urljoin(self.base_url, f"/api/v1/ml/state/{ue_id}")
            response = requests.get(url, headers=self.get_headers(), timeout=10)
            if response.status_code == 200:
                return response.json()
            self.logger.error(
                "Error getting feature vector: %s - %s",
                response.status_code,
                response.text,
            )
            return {}
        except requests.exceptions.RequestException as exc:
            self.logger.error("HTTP error getting feature vector: %s", exc)
            return {}
        except Exception as e:
            self.logger.error(f"Error in get_feature_vector: {str(e)}")
            return {}
