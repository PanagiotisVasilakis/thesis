"""Async client for interacting with the NEF emulator."""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin

import aiohttp
from aiohttp import ClientTimeout, ClientSession, ClientError


class AsyncNEFClientError(Exception):
    """Raised when an HTTP request to the NEF emulator fails."""


class AsyncNEFClient:
    """Async client for the NEF emulator API."""

    def __init__(
        self,
        base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """Initialize the async NEF client.
        
        Args:
            base_url: Base URL of the NEF emulator
            username: Username for authentication
            password: Password for authentication
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
            retry_delay: Delay between retries in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.token: Optional[str] = None
        self.logger = logging.getLogger(__name__)
        
        # Configure timeouts and retry policy
        self.timeout = ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Session management
        self._session: Optional[ClientSession] = None
        self._session_lock = asyncio.Lock()

    async def _get_session(self) -> ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    connector = aiohttp.TCPConnector(
                        limit=50,  # Total connection pool size
                        limit_per_host=10,  # Per-host connection limit
                        ttl_dns_cache=300,  # DNS cache TTL
                        use_dns_cache=True,
                    )
                    self._session = ClientSession(
                        connector=connector,
                        timeout=self.timeout,
                        headers={
                            'User-Agent': 'ml-service/1.0.0',
                            'Accept': 'application/json',
                        },
                        json_serialize=json.dumps,
                    )
        return self._session

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    def get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication token if available."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _make_request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """Make HTTP request with retry logic."""
        session = await self._get_session()
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                async with session.request(method, url, **kwargs) as response:
                    # For successful responses, return immediately
                    if response.status < 500:
                        return response
                    
                    # For server errors, retry
                    self.logger.warning(
                        "Server error %d on attempt %d/%d for %s %s",
                        response.status, attempt + 1, self.max_retries, method, url
                    )
                    
            except (ClientError, asyncio.TimeoutError) as exc:
                last_exception = exc
                self.logger.warning(
                    "Request failed on attempt %d/%d for %s %s: %s",
                    attempt + 1, self.max_retries, method, url, exc
                )
            
            # Wait before retry (except on last attempt)
            if attempt < self.max_retries - 1:
                delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                await asyncio.sleep(delay)
        
        # All retries exhausted
        raise AsyncNEFClientError(
            f"Request failed after {self.max_retries} attempts: {last_exception}"
        ) from last_exception

    async def login(self) -> bool:
        """Authenticate with the NEF emulator."""
        if not self.username or not self.password:
            self.logger.warning("No credentials provided, skipping authentication")
            return False

        login_url = urljoin(self.base_url, "/api/v1/login/access-token")
        
        try:
            response = await self._make_request_with_retry(
                "POST",
                login_url,
                data={
                    "username": self.username,
                    "password": self.password
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status == 200:
                data = await response.json()
                self.token = data.get("access_token")
                self.logger.info("Successfully authenticated with NEF emulator")
                return True
            else:
                error_text = await response.text()
                self.logger.error(
                    "Authentication failed: %s - body: %s",
                    response.status, error_text
                )
                return False
                
        except (AsyncNEFClientError, json.JSONDecodeError) as exc:
            self.logger.error("Authentication request failed: %s", exc)
            raise AsyncNEFClientError(f"Authentication failed: {exc}") from exc

    async def get_status(self) -> Dict[str, Any]:
        """Get NEF emulator status."""
        url = urljoin(self.base_url, "/api/v1/paths/")
        
        try:
            response = await self._make_request_with_retry(
                "GET", url, headers=self.get_headers()
            )
            
            if response.status == 200:
                return {
                    "status_code": response.status,
                    "headers": dict(response.headers),
                    "data": await response.json()
                }
            else:
                error_text = await response.text()
                self.logger.error(
                    "Error querying NEF status: %s - body: %s",
                    response.status, error_text
                )
                return {
                    "status_code": response.status,
                    "error": error_text
                }
                
        except (AsyncNEFClientError, json.JSONDecodeError) as exc:
            self.logger.error("Status request failed: %s", exc)
            raise AsyncNEFClientError(f"Status request failed: {exc}") from exc

    async def generate_mobility_pattern(
        self,
        model_type: str,
        ue_id: str,
        parameters: Dict[str, Any],
        duration: float = 300.0,
        time_step: float = 1.0,
    ) -> Optional[List[Dict[str, Any]]]:
        """Generate a mobility pattern using the NEF emulator API."""
        url = urljoin(self.base_url, "/api/v1/mobility-patterns/generate")
        
        payload = {
            "model_type": model_type,
            "ue_id": ue_id,
            "duration": duration,
            "time_step": time_step,
            "parameters": parameters,
        }
        
        try:
            response = await self._make_request_with_retry(
                "POST",
                url,
                json=payload,
                headers=self.get_headers()
            )
            
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                self.logger.error(
                    "Error generating mobility pattern: %s - body: %s",
                    response.status, error_text
                )
                return None
                
        except (AsyncNEFClientError, json.JSONDecodeError) as exc:
            self.logger.error("Mobility pattern request failed: %s", exc)
            raise AsyncNEFClientError(f"Mobility pattern request failed: {exc}") from exc

    async def get_ue_movement_state(self) -> Dict[str, Any]:
        """Get current state of all UEs in movement."""
        url = urljoin(self.base_url, "/api/v1/ue-movement/state-ues")
        
        try:
            response = await self._make_request_with_retry(
                "GET", url, headers=self.get_headers()
            )
            
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                self.logger.error(
                    "Error getting UE movement state: %s - body: %s",
                    response.status, error_text
                )
                return {}
                
        except json.JSONDecodeError as exc:
            self.logger.error("Error parsing movement state response: %s", exc)
            raise AsyncNEFClientError(f"Invalid JSON response: {exc}") from exc
        except AsyncNEFClientError as exc:
            self.logger.error("Movement state request failed: %s", exc)
            raise

    async def get_feature_vector(self, ue_id: str) -> Dict[str, Any]:
        """Return the ML feature vector for the given UE."""
        url = urljoin(self.base_url, f"/api/v1/ml/state/{ue_id}")
        
        try:
            response = await self._make_request_with_retry(
                "GET", url, headers=self.get_headers()
            )
            
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                self.logger.error(
                    "Error getting feature vector: %s - body: %s",
                    response.status, error_text
                )
                return {}
                
        except json.JSONDecodeError as exc:
            self.logger.error("Error parsing feature vector response: %s", exc)
            raise AsyncNEFClientError(f"Invalid JSON response: {exc}") from exc
        except AsyncNEFClientError as exc:
            self.logger.error("Feature vector request failed: %s", exc)
            raise

    async def batch_get_feature_vectors(
        self, ue_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Get feature vectors for multiple UEs concurrently."""
        if not ue_ids:
            return {}
        
        # Create concurrent tasks
        tasks = [
            asyncio.create_task(
                self.get_feature_vector(ue_id), name=f"feature_vector_{ue_id}"
            )
            for ue_id in ue_ids
        ]
        
        # Wait for all tasks to complete
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            feature_vectors = {}
            for ue_id, result in zip(ue_ids, results):
                if isinstance(result, Exception):
                    self.logger.error(
                        "Failed to get feature vector for UE %s: %s", ue_id, result
                    )
                    feature_vectors[ue_id] = {}
                else:
                    feature_vectors[ue_id] = result
                    
            return feature_vectors
            
        except Exception as exc:
            self.logger.error("Batch feature vector request failed: %s", exc)
            raise AsyncNEFClientError(f"Batch request failed: {exc}") from exc

    async def health_check(self) -> bool:
        """Simple health check for the NEF emulator."""
        try:
            status_result = await self.get_status()
            return status_result.get("status_code") == 200
        except Exception as exc:
            self.logger.error("Health check failed: %s", exc)
            return False