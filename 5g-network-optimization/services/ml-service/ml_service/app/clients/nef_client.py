# File: services/ml-service/app/clients/nef_client.py

"""Client for interacting with the NEF emulator.

This module defines :class:`NEFClient` for communicating with the NEF emulator
and :class:`NEFClientError` which is raised whenever an HTTP request fails
because of a :class:`requests.exceptions.RequestException`.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils.circuit_breaker import CircuitBreaker, CircuitBreakerError, circuit_registry


class NEFClientError(Exception):
    """Raised when an HTTP request to the NEF emulator fails."""


class NEFClient:
    """Client for the NEF emulator API."""

    def __init__(
        self,
        base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        pool_connections: int = 10,
        pool_maxsize: int = 20,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        http_client: Optional[Any] = None,
    ):
        """Initialize the NEF client with connection pooling and circuit breaker protection.

        Args:
            base_url: Base URL for the NEF emulator
            username: Authentication username
            password: Authentication password
            pool_connections: Number of connection pools to cache
            pool_maxsize: Maximum number of connections in each pool
            max_retries: Maximum number of retry attempts
            backoff_factor: Backoff factor for retries
            http_client: Optional custom HTTP client for testing
        """
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = None
        self.logger = logging.getLogger(__name__)

        # Select HTTP client implementation suitable for the environment
        self._http = self._initialize_http_client(
            http_client=http_client,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=max_retries,
            backoff_factor=backoff_factor,
        )

        # Backwards compatibility: expose session attr when HTTP client supports closing
        self.session = self._http if hasattr(self._http, "close") else None
        
        # Initialize circuit breakers for different endpoint types
        self._login_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30.0,
            expected_exception=requests.exceptions.RequestException,
            name=f"NEF-Login-{base_url}"
        )
        
        self._api_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            expected_exception=requests.exceptions.RequestException,
            name=f"NEF-API-{base_url}"
        )
        
        # Register circuit breakers
        circuit_registry.register(self._login_breaker)
        circuit_registry.register(self._api_breaker)
        
        self.logger.info(
            "NEF client initialized with connection pooling "
            "(pool_connections=%d, pool_maxsize=%d, max_retries=%d) "
            "and circuit breaker protection",
            pool_connections, pool_maxsize, max_retries
        )

    def _initialize_http_client(
        self,
        http_client: Optional[Any],
        pool_connections: int,
        pool_maxsize: int,
        max_retries: int,
        backoff_factor: float,
    ) -> Any:
        """Return an HTTP client instance suited for production or tests."""
        if http_client is not None:
            return http_client

        session = requests.Session()
        retry_kwargs: Dict[str, Any] = {
            "total": max_retries,
            "status_forcelist": [429, 500, 502, 503, 504],
            "backoff_factor": backoff_factor,
            "raise_on_status": False,
        }
        retry_strategy = Retry(**retry_kwargs)
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry_strategy,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({
            "User-Agent": "NEFClient/1.0",
            "Connection": "keep-alive",
        })
        return session

    def login(self) -> bool:
        """Authenticate with the NEF emulator using circuit breaker protection."""
        if not self.username or not self.password:
            self.logger.warning(
                "No credentials provided, skipping authentication"
            )
            return False

        def _do_login():
            login_url = urljoin(self.base_url, "/api/v1/login/access-token")
            response = self._http.post(
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
                    "Authentication failed: %s - body: %s",
                    response.status_code,
                    response.text,
                )
                return False

        try:
            return self._login_breaker.call(_do_login)
        except CircuitBreakerError as e:
            self.logger.error("Login circuit breaker is open: %s", e)
            raise NEFClientError(f"NEF login service unavailable: {e}") from e
        except requests.exceptions.RequestException as exc:
            self.logger.error("Login request failed: %s", exc)
            raise NEFClientError(f"Authentication request failed: {exc}") from exc

    def get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication token if available."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_status(self) -> requests.Response:
        """Return the raw response from the NEF status endpoint."""
        url = urljoin(self.base_url, "/api/v1/paths/")
        try:
            response = self._http.get(url, headers=self.get_headers(), timeout=5)
            if response.status_code != 200:
                self.logger.error(
                    "Error querying NEF status: %s - body: %s",
                    response.status_code,
                    response.text,
                )
            return response
        except requests.exceptions.RequestException as exc:
            self.logger.error("Request to %s failed: %s", url, exc)
            raise NEFClientError(f"Status request failed: {exc}") from exc

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
        url = urljoin(self.base_url, "/api/v1/mobility-patterns/generate")
        try:

            payload = {
                "model_type": model_type,
                "ue_id": ue_id,
                "duration": duration,
                "time_step": time_step,
                "parameters": parameters,
            }

            response = self._http.post(
                url, json=payload, headers=self.get_headers(), timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                self.logger.error(
                    "Error generating mobility pattern: %s - body: %s",
                    response.status_code,
                    response.text,
                )
                return None
        except requests.exceptions.RequestException as exc:
            self.logger.error("Request to %s failed: %s", url, exc)
            raise NEFClientError(
                f"Mobility pattern request failed: {exc}"
            ) from exc

    def get_ue_movement_state(self) -> Dict[str, Any]:
        """Get current state of all UEs in movement."""
        url = urljoin(self.base_url, "/api/v1/ue-movement/state-ues")
        try:

            response = self._http.get(
                url, headers=self.get_headers(), timeout=10
            )

            if response.status_code == 200:
                return response.json()
            else:
                self.logger.error(
                    "Error getting UE movement state: %s - body: %s",
                    response.status_code,
                    response.text,
                )
                return {}
        except requests.exceptions.RequestException as exc:
            self.logger.error("Request to %s failed: %s", url, exc)
            raise NEFClientError(
                f"Movement state request failed: {exc}"
            ) from exc
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Handle JSON parsing and data extraction errors
            self.logger.error(f"Error parsing movement state response: {str(e)}")
            raise NEFClientError(f"Invalid response format: {e}") from e

    def get_feature_vector(self, ue_id: str) -> Dict[str, Any]:
        """Return the ML feature vector for the given UE."""
        url = urljoin(self.base_url, f"/api/v1/ml/state/{ue_id}")
        try:
            response = self._http.get(
                url, headers=self.get_headers(), timeout=10
            )
            if response.status_code == 200:
                return response.json()
            self.logger.error(
                "Error getting feature vector: %s - body: %s",
                response.status_code,
                response.text,
            )
            return {}
        except requests.exceptions.RequestException as exc:
            self.logger.error("Request to %s failed: %s", url, exc)
            raise NEFClientError(
                f"Feature vector request failed: {exc}"
            ) from exc
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Handle JSON parsing and data extraction errors
            self.logger.error(f"Error parsing feature vector response: {str(e)}")
            raise NEFClientError(f"Invalid response format: {e}") from e

    def get_circuit_breaker_stats(self) -> Dict[str, Any]:
        """Get statistics for all circuit breakers in this client."""
        return {
            "login_breaker": self._login_breaker.get_stats(),
            "api_breaker": self._api_breaker.get_stats()
        }
    
    def reset_circuit_breakers(self) -> None:
        """Reset all circuit breakers to closed state."""
        self._login_breaker.reset()
        self._api_breaker.reset()
        self.logger.info("All NEF client circuit breakers reset")
    
    def close(self) -> None:
        """Close the session and clean up connection pools."""
        session = getattr(self, "session", None)
        if session is not None and hasattr(session, "close"):
            session.close()
            self.logger.info("NEF client session closed and connection pools cleaned up")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up resources."""
        self.close()
