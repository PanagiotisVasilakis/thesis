"""Async client for interacting with the NEF emulator with circuit breaker protection."""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin
from enum import Enum
from dataclasses import dataclass

import aiohttp
from aiohttp import ClientTimeout, ClientSession, ClientError

from ..utils.common_validators import StringValidator, ValidationError
from ..utils.resource_manager import (
    global_resource_manager, 
    ResourceType, 
    ResourceState,
    async_managed_resource
)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    success_threshold: int = 2
    timeout_seconds: float = 30.0


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class AsyncCircuitBreaker:
    """Async circuit breaker for fault tolerance."""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)
    
    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        async with self._lock:
            if self.state == CircuitBreakerState.OPEN:
                if time.time() - self.last_failure_time > self.config.recovery_timeout:
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.success_count = 0
                    self.logger.info("Circuit breaker moving to HALF_OPEN state")
                else:
                    raise CircuitBreakerError("Circuit breaker is OPEN")
        
        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.config.timeout_seconds
            )
            
            async with self._lock:
                if self.state == CircuitBreakerState.HALF_OPEN:
                    self.success_count += 1
                    if self.success_count >= self.config.success_threshold:
                        self.state = CircuitBreakerState.CLOSED
                        self.failure_count = 0
                        self.logger.info("Circuit breaker CLOSED - service recovered")
                elif self.state == CircuitBreakerState.CLOSED:
                    self.failure_count = 0
            
            return result
            
        except asyncio.TimeoutError:
            await self._record_failure("Timeout")
            raise
        except Exception as e:
            await self._record_failure(str(e))
            raise
    
    async def _record_failure(self, error: str):
        """Record a failure and potentially open the circuit."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if (self.state == CircuitBreakerState.CLOSED and 
                self.failure_count >= self.config.failure_threshold):
                self.state = CircuitBreakerState.OPEN
                self.logger.warning(
                    "Circuit breaker OPEN after %d failures. Last error: %s",
                    self.failure_count, error
                )
            elif self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.OPEN
                self.logger.warning("Circuit breaker OPEN - recovery attempt failed: %s", error)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "success_threshold": self.config.success_threshold,
                "timeout_seconds": self.config.timeout_seconds
            }
        }


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
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
    ):
        """Initialize the async NEF client.
        
        Args:
            base_url: Base URL of the NEF emulator
            username: Username for authentication
            password: Password for authentication
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
            retry_delay: Delay between retries in seconds
            circuit_breaker_config: Circuit breaker configuration
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
        
        # Circuit breaker for fault tolerance
        cb_config = circuit_breaker_config or CircuitBreakerConfig(timeout_seconds=timeout)
        self.circuit_breaker = AsyncCircuitBreaker(cb_config)
        
        # Session management
        self._session: Optional[ClientSession] = None
        self._session_lock = asyncio.Lock()
        self._closed = False
        self._session_resource_id: Optional[str] = None

    async def _get_session(self) -> ClientSession:
        """Get or create an aiohttp session."""
        if self._closed:
            raise AsyncNEFClientError("Client has been closed")
            
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    connector = aiohttp.TCPConnector(
                        limit=50,  # Total connection pool size
                        limit_per_host=10,  # Per-host connection limit
                        ttl_dns_cache=300,  # DNS cache TTL
                        use_dns_cache=True,
                        keepalive_timeout=30,
                        enable_cleanup_closed=True,
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
                    
                    # Register session with resource manager
                    self._session_resource_id = global_resource_manager.register_resource(
                        self._session,
                        ResourceType.HTTP_SESSION,
                        cleanup_method=self._session.close,
                        metadata={
                            "client_type": "AsyncNEFClient",
                            "base_url": self.base_url,
                            "connector_limit": 50
                        }
                    )
        return self._session

    async def close(self):
        """Close the HTTP session and clean up resources."""
        self._closed = True
        
        # Unregister from resource manager first
        if self._session_resource_id:
            global_resource_manager.unregister_resource(self._session_resource_id, force_cleanup=True)
            self._session_resource_id = None
        
        if self._session and not self._session.closed:
            await self._session.close()
            
        # Wait a bit for connections to close
        await asyncio.sleep(0.1)

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
    ) -> Dict[str, Any]:
        """Make HTTP request with circuit breaker protection and retry logic."""
        
        async def _execute_request():
            session = await self._get_session()
            last_exception = None
            
            for attempt in range(self.max_retries):
                try:
                    async with session.request(method, url, **kwargs) as response:
                        # For successful responses, return JSON data
                        if response.status < 400:
                            try:
                                return await response.json()
                            except json.JSONDecodeError:
                                # Return empty dict for non-JSON responses
                                return {"status_code": response.status}
                        
                        # For client errors (4xx), don't retry
                        if 400 <= response.status < 500:
                            error_text = await response.text()
                            raise AsyncNEFClientError(
                                f"HTTP {response.status}: {error_text}"
                            )
                        
                        # For server errors (5xx), retry
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
        
        # Execute with circuit breaker protection
        return await self.circuit_breaker.call(_execute_request)

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
            
            # Response is now a dict, check for access_token
            if "access_token" in response:
                self.token = response["access_token"]
                self.logger.info("Successfully authenticated with NEF emulator")
                return True
            else:
                self.logger.error("Authentication failed: no access token in response")
                return False
                
        except (AsyncNEFClientError, CircuitBreakerError) as exc:
            self.logger.error("Authentication request failed: %s", exc)
            return False

    async def get_status(self) -> Dict[str, Any]:
        """Get NEF emulator status."""
        url = urljoin(self.base_url, "/api/v1/paths/")
        
        try:
            response = await self._make_request_with_retry(
                "GET", url, headers=self.get_headers()
            )
            return response
                
        except (AsyncNEFClientError, CircuitBreakerError) as exc:
            self.logger.error("Status request failed: %s", exc)
            return {"error": str(exc), "status_code": 0}

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
            return response
                
        except (AsyncNEFClientError, CircuitBreakerError) as exc:
            self.logger.error("Mobility pattern request failed: %s", exc)
            return None

    async def get_ue_movement_state(self) -> Dict[str, Any]:
        """Get current state of all UEs in movement."""
        url = urljoin(self.base_url, "/api/v1/ue-movement/state-ues")
        
        try:
            response = await self._make_request_with_retry(
                "GET", url, headers=self.get_headers()
            )
            return response
                
        except (AsyncNEFClientError, CircuitBreakerError) as exc:
            self.logger.error("Movement state request failed: %s", exc)
            return {}

    async def get_feature_vector(self, ue_id: str) -> Dict[str, Any]:
        """Return the ML feature vector for the given UE."""
        try:
            ue_id = StringValidator.validate_ue_id(ue_id)
        except ValidationError as e:
            raise ValueError(str(e)) from e
            
        url = urljoin(self.base_url, f"/api/v1/ml/state/{ue_id}")
        
        try:
            response = await self._make_request_with_retry(
                "GET", url, headers=self.get_headers()
            )
            return response
                
        except (AsyncNEFClientError, CircuitBreakerError) as exc:
            self.logger.error("Feature vector request for UE %s failed: %s", ue_id, exc)
            return {}

    async def batch_get_feature_vectors(
        self, ue_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Get feature vectors for multiple UEs concurrently."""
        if not ue_ids:
            return {}
        
        # Validate UE IDs
        valid_ue_ids = []
        for ue_id in ue_ids:
            try:
                valid_ue_id = StringValidator.validate_ue_id(ue_id)
                valid_ue_ids.append(valid_ue_id)
            except ValidationError:
                self.logger.warning("Invalid UE ID in batch request: %s", ue_id)
                continue
        
        if not valid_ue_ids:
            return {}
        
        # Use semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(10)  # Max 10 concurrent requests
        
        async def get_single_feature(ue_id: str) -> tuple[str, Dict[str, Any]]:
            async with semaphore:
                features = await self.get_feature_vector(ue_id)
                return ue_id, features
        
        # Create concurrent tasks
        tasks = [get_single_feature(ue_id) for ue_id in valid_ue_ids]
        
        # Wait for all tasks to complete
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            feature_vectors = {}
            for result in results:
                if isinstance(result, Exception):
                    self.logger.warning("Batch feature request failed: %s", result)
                    continue
                
                ue_id, features = result
                if features:  # Only include non-empty results
                    feature_vectors[ue_id] = features
                    
            return feature_vectors
            
        except Exception as exc:
            self.logger.error("Batch feature vector request failed: %s", exc)
            return {}

    async def health_check(self) -> bool:
        """Simple health check for the NEF emulator."""
        try:
            status_result = await self.get_status()
            return "error" not in status_result
        except Exception as exc:
            self.logger.error("Health check failed: %s", exc)
            return False
    
    def get_circuit_breaker_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        return self.circuit_breaker.get_stats()