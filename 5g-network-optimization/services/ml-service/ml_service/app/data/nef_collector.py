"""Data collection from NEF emulator for ML training."""
import logging
import os
from datetime import datetime

import asyncio
import time
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..config.constants import (
    env_constants,
    DEFAULT_COLLECTION_DURATION,
    DEFAULT_COLLECTION_INTERVAL,
    DEFAULT_NEF_TIMEOUT,
    DEFAULT_COLLECTION_RETRIES,
    DEFAULT_STATS_LOG_INTERVAL,
)
from ..utils.common_validators import (
    DataCollectionValidator,
    UEDataValidator,
    validate_ue_sample_data,
    ValidationError,
)
from ..utils.exception_handler import (
    handle_exceptions,
    exception_context,
)
from ..utils.resource_manager import (
    global_resource_manager,
    ResourceType,
)
from ..clients.nef_client import NEFClient, NEFClientError
from ..clients.async_nef_client import AsyncNEFClient, AsyncNEFClientError, CircuitBreakerError
from .feature_extractor import (
    FeatureExtractor,
    HandoverTracker,
    SignalProcessor,
    MobilityProcessor,
)
from .persistence import TrainingDataPersistence

SIGNAL_WINDOW_SIZE = env_constants.SIGNAL_WINDOW_SIZE
POSITION_WINDOW_SIZE = env_constants.POSITION_WINDOW_SIZE


def _normalize_qos_payload(
    payload: Any,
    ue_id: str,
    logger: logging.Logger,
) -> Tuple[Optional[str], Optional[int], Optional[Dict[str, float]]]:
    """Validate and normalize QoS payloads returned by the NEF API.

    Args:
        payload: Raw payload returned by the NEF client.
        ue_id: Identifier of the UE the payload belongs to.
        logger: Logger used to emit diagnostic messages.

    Returns:
        Tuple containing service type, service priority, and a normalized
        dictionary of QoS thresholds. Elements are ``None`` when validation
        fails.
    """

    if payload in (None, {}):
        logger.debug("No QoS requirements returned for UE %s", ue_id)
        return None, None, None

    if is_dataclass(payload):
        payload = asdict(payload)

    if not isinstance(payload, dict):
        coerced: Optional[Dict[str, Any]] = None

        if isinstance(payload, Mapping):
            coerced = dict(payload)
        else:
            for attr in ("model_dump", "dict", "to_dict"):
                method = getattr(payload, attr, None)
                if callable(method):
                    try:
                        candidate = method()
                    except Exception:  # pragma: no cover - defensive conversion
                        continue
                    if isinstance(candidate, dict):
                        coerced = candidate
                        break

            if coerced is None:
                try:
                    coerced = dict(payload)  # type: ignore[arg-type]
                except Exception:  # pragma: no cover - defensive conversion
                    coerced = None

        if coerced is None:
            logger.error(
                "Unexpected QoS payload type for UE %s: %s",
                ue_id,
                type(payload).__name__,
            )
            return None, None, None

        payload = coerced

    def _lookup(keys: List[str], source: Dict[str, Any]) -> Any:
        for key in keys:
            if key in source:
                return source[key]
        return None

    service_type: Optional[str] = None
    raw_service_type = _lookup(["service_type", "serviceType"], payload)
    if isinstance(raw_service_type, str):
        service_type = raw_service_type.strip() or None
    elif raw_service_type is not None:
        logger.warning(
            "Invalid QoS service_type for UE %s: %r", ue_id, raw_service_type
        )

    service_priority: Optional[int] = None
    raw_priority = _lookup(["service_priority", "servicePriority"], payload)
    if raw_priority is not None:
        try:
            service_priority = int(raw_priority)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid QoS service_priority for UE %s: %r", ue_id, raw_priority
            )

    candidate_sections = [
        payload.get("requirements"),
        payload.get("qos_requirements"),
        payload.get("qosRequirements"),
    ]
    requirements_section = next(
        (section for section in candidate_sections if isinstance(section, dict)),
        None,
    )

    if requirements_section is None:
        requirements_section = payload

    normalized: Dict[str, float] = {}

    def _extract_float(keys: List[str]) -> Optional[float]:
        if not isinstance(requirements_section, dict):
            return None
        for key in keys:
            if key not in requirements_section:
                continue
            value = requirements_section.get(key)
            try:
                return float(value)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid QoS %s for UE %s: %r",
                    key,
                    ue_id,
                    value,
                )
        return None

    latency = _extract_float([
        "latency_requirement_ms",
        "latencyRequirementMs",
        "latency_ms",
        "latency",
    ])
    if latency is not None:
        normalized["latency_requirement_ms"] = latency

    throughput = _extract_float([
        "throughput_requirement_mbps",
        "throughputRequirementMbps",
        "throughput_mbps",
        "throughput",
    ])
    if throughput is not None:
        normalized["throughput_requirement_mbps"] = throughput

    reliability = _extract_float([
        "reliability_pct",
        "reliabilityPct",
        "reliability_percent",
        "reliability",
    ])
    if reliability is not None:
        normalized["reliability_pct"] = reliability

    jitter = _extract_float([
        "jitter_ms",
        "jitterMs",
    ])
    if jitter is not None:
        normalized["jitter_ms"] = jitter

    if not normalized and service_type is None and service_priority is None:
        logger.warning(
            "QoS payload for UE %s did not contain recognizable requirement fields",
            ue_id,
        )

    return service_type, service_priority, normalized or None


class _CollectorComponents:
    """Bundle of helper components shared by collectors."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        data_dir: str,
        max_ues: int,
        ue_ttl_hours: float,
        signal_window_size: int,
        position_window_size: int,
    ) -> None:
        self._logger = logger
        self.max_ues = max_ues
        self.feature_extractor = FeatureExtractor()
        self.handover_tracker = HandoverTracker(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        self.signal_processor = SignalProcessor(
            signal_window_size=signal_window_size,
            max_ues=max_ues,
            ue_ttl_hours=ue_ttl_hours,
        )
        self.mobility_processor = MobilityProcessor(
            position_window_size=position_window_size,
            max_ues=max_ues,
            ue_ttl_hours=ue_ttl_hours,
        )
        self.persistence = TrainingDataPersistence(data_dir=data_dir)

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def build_sample(
        self,
        *,
        ue_id: str,
        ue_data: Dict[str, Any],
        feature_vector: Dict[str, Any],
        connected_cell_id: str,
        service_type: Optional[str],
        service_priority: Optional[int],
        qos_requirements: Optional[Dict[str, float]],
        timestamp: float,
    ) -> Dict[str, Any]:
        rf_metrics = self.feature_extractor.extract_rf_features(feature_vector or {})
        optimal_antenna = (
            self.feature_extractor.determine_optimal_antenna(rf_metrics)
            if rf_metrics
            else connected_cell_id
        )

        env_features = self.feature_extractor.extract_environment_features(feature_vector or {})
        cell_load = self._to_float(env_features.get("cell_load"))
        environment = self._to_float(env_features.get("environment"))
        signal_trend_override = self._to_float(env_features.get("signal_trend"))

        serving_metrics = rf_metrics.get(connected_cell_id, {}) if connected_cell_id else {}
        rsrp_current = self._to_float(serving_metrics.get("rsrp"))
        sinr_current = self._to_float(serving_metrics.get("sinr"))
        rsrq_current = self._to_float(serving_metrics.get("rsrq"))

        rsrp_stddev, sinr_stddev = self.signal_processor.update_signal_metrics(
            ue_id,
            rsrp_current,
            sinr_current,
            rsrq_current,
        )
        signal_trend = self.signal_processor.calculate_signal_trend(
            ue_id,
            rsrp_current,
            sinr_current,
            rsrq_current,
        )
        if signal_trend_override is not None:
            signal_trend = signal_trend_override

        latitude = ue_data.get("latitude")
        longitude = ue_data.get("longitude")
        speed = self._to_float(ue_data.get("speed"))

        heading_change_rate, path_curvature, derived_accel = self.mobility_processor.update_mobility_metrics(
            ue_id,
            latitude if isinstance(latitude, (int, float)) else 0.0,
            longitude if isinstance(longitude, (int, float)) else 0.0,
            speed,
        )

        handover_count, time_since_handover = self.handover_tracker.update_handover_state(
            ue_id,
            connected_cell_id,
            timestamp,
        )

        velocity_val = self._to_float(feature_vector.get("velocity"))
        velocity = velocity_val if velocity_val is not None else speed

        accel_feature = self._to_float(feature_vector.get("acceleration"))
        accel_data = self._to_float(ue_data.get("acceleration"))
        acceleration = (
            accel_feature
            if accel_feature is not None
            else accel_data if accel_data is not None else derived_accel
        )

        altitude = ue_data.get("altitude")
        if altitude is None:
            altitude = feature_vector.get("altitude")

        if cell_load is None:
            fallback_cell_load = self._to_float(feature_vector.get("cell_load"))
            if fallback_cell_load is not None:
                cell_load = fallback_cell_load
            else:
                cell_load = (len(rf_metrics) / 10.0) if rf_metrics else 0.0

        if environment is None:
            environment = 0.0

        sample = {
            "timestamp": datetime.fromtimestamp(timestamp).isoformat(),
            "ue_id": ue_id,
            "latitude": ue_data.get("latitude"),
            "longitude": ue_data.get("longitude"),
            "heading_change_rate": heading_change_rate,
            "path_curvature": path_curvature,
            "altitude": altitude,
            "speed": speed,
            "velocity": velocity,
            "acceleration": acceleration,
            "cell_load": cell_load,
            "handover_count": handover_count,
            "time_since_handover": time_since_handover,
            "signal_trend": signal_trend,
            "environment": environment,
            "rsrp_stddev": rsrp_stddev,
            "sinr_stddev": sinr_stddev,
            "connected_to": connected_cell_id,
            "optimal_antenna": optimal_antenna,
            "rf_metrics": rf_metrics,
            "service_type": service_type,
            "service_priority": service_priority,
            "qos_requirements": qos_requirements,
        }

        return sample

    def get_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        try:
            stats["handover_tracker"] = self.handover_tracker.get_stats()
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.debug("Failed to collect handover tracker stats: %s", exc)
            try:
                stats["handover_tracker"] = {"tracked_ues": len(self.handover_tracker._prev_cell)}
            except Exception:
                pass
        try:
            stats["signal_processor"] = self.signal_processor.get_stats()
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.debug("Failed to collect signal processor stats: %s", exc)
            try:
                stats["signal_processor"] = {"tracked_ues": len(self.signal_processor._prev_signal)}
            except Exception:
                pass
        try:
            stats["mobility_processor"] = self.mobility_processor.get_stats()
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.debug("Failed to collect mobility processor stats: %s", exc)
            try:
                stats["mobility_processor"] = {"tracked_ues": len(self.mobility_processor._prev_speed)}
            except Exception:
                pass
        try:
            stats["storage"] = self.persistence.get_storage_stats()
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.debug("Failed to collect storage stats: %s", exc)
            try:
                stats["storage"] = {"data_directory": self.persistence.data_dir.as_posix()}
            except Exception:
                pass
        return stats

    def cleanup(self) -> None:
        try:
            self.handover_tracker._prev_cell.clear()
            self.handover_tracker._handover_counts.clear()
            self.handover_tracker._last_handover_ts.clear()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self.signal_processor._prev_signal.clear()
            self.signal_processor._signal_buffer.clear()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self.mobility_processor._prev_speed.clear()
        except Exception:  # pragma: no cover - defensive
            pass


class NEFDataCollector:
    """Collect data from NEF emulator for ML training."""

    def __init__(self, nef_url=None, username=None, password=None, data_dir: Optional[str] = None):
        """Initialize the data collector with optimized NEF client."""
        # Use environment-aware defaults
        nef_url = nef_url or env_constants.NEF_URL
        
        # Use connection pooling for better performance
        self.client = NEFClient(
            nef_url, 
            username=username, 
            password=password,
            pool_connections=5,  # Smaller pool for data collector
            pool_maxsize=10,     # Fewer connections needed
            max_retries=env_constants.COLLECTION_RETRIES
        )
        self.nef_url = nef_url
        self.username = username
        self.password = password
        default_dir = data_dir or os.path.join(os.path.dirname(__file__), 'collected_data')
        self._data_dir = os.path.abspath(default_dir)
        os.makedirs(self._data_dir, exist_ok=True)

        # Set up logger for this collector
        self.logger = logging.getLogger('NEFDataCollector')

        max_ues = env_constants.UE_TRACKING_MAX_UES
        ttl_hours = env_constants.UE_TRACKING_TTL_HOURS

        self._components = _CollectorComponents(
            logger=self.logger,
            data_dir=self._data_dir,
            max_ues=max_ues,
            ue_ttl_hours=ttl_hours,
            signal_window_size=SIGNAL_WINDOW_SIZE,
            position_window_size=POSITION_WINDOW_SIZE,
        )

        # Track last statistics logging time
        self._last_stats_log = time.time()
        self._stats_log_interval = env_constants.STATS_LOG_INTERVAL
        
        # Register with resource manager
        self._resource_id = global_resource_manager.register_resource(
            self,
            ResourceType.CLIENT,
            cleanup_method=self.cleanup_resources,
            metadata={
                "collector_type": "NEFDataCollector",
                "nef_url": self.nef_url,
                "max_ues": max_ues
            }
        )

        # Track UEs for which QoS data was unavailable to avoid spamming logs
        self._missing_qos_logged: set[str] = set()

    @property
    def data_dir(self) -> str:
        return self._data_dir

    @data_dir.setter
    def data_dir(self, value: str) -> None:
        """Reconfigure the persistence directory at runtime."""
        path = os.path.abspath(value)
        os.makedirs(path, exist_ok=True)
        self._data_dir = path
        if hasattr(self, "_components"):
            self._components.persistence = TrainingDataPersistence(data_dir=path)

    def _log_memory_stats(self):
        """Log comprehensive memory usage statistics for optimized tracking dictionaries."""
        now = time.time()
        if now - self._last_stats_log >= self._stats_log_interval:
            stats = self._components.get_stats()
            if stats:
                self.logger.info("=== NEF Collector Runtime Statistics ===")
                for name, details in stats.items():
                    self.logger.info("%s: %s", name, details)
                self.logger.info("=== End Runtime Statistics ===")
            self._last_stats_log = now
    
    def _cleanup_inactive_ues(self):
        """Compatibility no-op; helpers manage eviction internally."""
        return 0

    def _fetch_qos_requirements(
        self, ue_id: str
    ) -> Tuple[Optional[str], Optional[int], Optional[Dict[str, float]]]:
        """Retrieve QoS requirements for a UE with robust error handling."""

        client_method = getattr(self.client, "get_qos_requirements", None)
        if client_method is None:
            if ue_id not in self._missing_qos_logged:
                self.logger.info(
                    "NEF client does not expose QoS endpoint; skipping QoS for UE %s",
                    ue_id,
                )
                self._missing_qos_logged.add(ue_id)
            return None, None, None

        try:
            payload = client_method(ue_id)
        except NEFClientError as exc:
            if ue_id not in self._missing_qos_logged:
                self.logger.warning(
                    "Failed to fetch QoS requirements for UE %s: %s",
                    ue_id,
                    exc,
                )
                self._missing_qos_logged.add(ue_id)
            return None, None, None
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.exception(
                "Unexpected error retrieving QoS requirements for UE %s", ue_id
            )
            return None, None, None

        service_type, service_priority, qos_requirements = _normalize_qos_payload(
            payload,
            ue_id,
            self.logger,
        )

        if (
            service_type is not None
            or service_priority is not None
            or qos_requirements is not None
        ) and ue_id in self._missing_qos_logged:
            self._missing_qos_logged.discard(ue_id)

        if (
            service_type is None
            and service_priority is None
            and qos_requirements is None
            and ue_id not in self._missing_qos_logged
        ):
            self.logger.warning(
                "QoS requirements unavailable after validation for UE %s", ue_id
            )
            self._missing_qos_logged.add(ue_id)

        return service_type, service_priority, qos_requirements

    def _build_sample(
        self,
        *,
        ue_id: str,
        ue_data: Dict[str, Any],
        feature_vector: Dict[str, Any],
        connected_cell_id: str,
        service_type: Optional[str],
        service_priority: Optional[int],
        qos_requirements: Optional[Dict[str, float]],
    ) -> Dict[str, Any]:
        timestamp = time.time()
        return self._components.build_sample(
            ue_id=ue_id,
            ue_data=ue_data,
            feature_vector=feature_vector,
            connected_cell_id=connected_cell_id,
            service_type=service_type,
            service_priority=service_priority,
            qos_requirements=qos_requirements,
            timestamp=timestamp,
        )

    @handle_exceptions(NEFClientError, context="NEF authentication", reraise=False, default_return=False, logger_name="NEFDataCollector")
    def login(self):
        """Authenticate with the NEF emulator via the underlying client."""
        return self.client.login()

    def get_ue_movement_state(self):
        """Get current state of all UEs in movement."""
        with exception_context("Getting UE movement state", reraise=False, default_return={}) as handler:
            state = self.client.get_ue_movement_state()
            if state is not None:
                ue_count = len(state.keys())
                self.logger.info(f"Retrieved state for {ue_count} moving UEs")
            return state

    async def collect_training_data(
        self, 
        duration: float = None, 
        interval: float = None
    ) -> List[Dict[str, Any]]:
        """
        Collect training data for the specified duration with comprehensive validation.

        Args:
            duration: Collection duration in seconds (default from config)
            interval: Sampling interval in seconds (default from config)

        Returns:
            List of collected data samples

        Raises:
            ValueError: If parameters are invalid
            NEFClientError: If NEF communication fails
        """
        # Use environment defaults if not provided
        duration = duration if duration is not None else env_constants.COLLECTION_DURATION
        interval = interval if interval is not None else env_constants.COLLECTION_INTERVAL
        
        # Use common validation logic
        try:
            duration, interval = DataCollectionValidator.validate_collection_parameters(duration, interval)
        except ValidationError as e:
            raise ValueError(str(e)) from e
            
        # Check if NEF client is available
        try:
            status = self.client.get_status()
            if not getattr(status, "status_code", 0) == 200:
                raise NEFClientError("NEF service not available")
        except Exception as e:
            raise NEFClientError(f"Cannot connect to NEF service: {e}") from e

        self.logger.info(
            f"Starting data collection for {duration} seconds at {interval}s intervals"
        )

        collected_data = []
        start_time = time.time()
        end_time = start_time + duration

        while time.time() < end_time:
            with exception_context("Data collection iteration", reraise=False) as handler:
                # Log memory statistics periodically
                self._log_memory_stats()
                
                ue_state = self.get_ue_movement_state()

                for ue_id, ue_data in ue_state.items():
                    if sample := self._collect_sample(ue_id, ue_data):
                        collected_data.append(sample)

            # Always sleep between iterations, regardless of errors
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
        """Create a single training sample for the given UE with input validation."""
        # Use common validation for UE data
        sample_data = validate_ue_sample_data(ue_id, ue_data, f"UE {ue_id} sample")
        if sample_data is None:
            return None
            
        ue_id, ue_data, latitude, longitude = sample_data
        
        # Validate Cell_id
        try:
            connected_cell_id = UEDataValidator.validate_cell_id(ue_data)
        except ValidationError:
            self.logger.debug("No Cell_id for UE %s", ue_id)
            return None

        fv = self.client.get_feature_vector(ue_id) or {}
        service_type, service_priority, qos_requirements = self._fetch_qos_requirements(ue_id)

        return self._build_sample(
            ue_id=ue_id,
            ue_data=ue_data,
            feature_vector=fv,
            connected_cell_id=connected_cell_id,
            service_type=service_type,
            service_priority=service_priority,
            qos_requirements=qos_requirements,
        )

    def _save_collected_data(self, collected_data: list) -> None:
        """Persist collected samples to disk."""
        filepath = self._components.persistence.save_training_data(collected_data)
        if not collected_data:
            self.logger.warning("Saved empty training data file to %s", filepath)
        else:
            self.logger.info(
                "Collected %d samples, saved to %s",
                len(collected_data),
                filepath,
            )

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the data collection system.
        
        Returns:
            Dictionary containing collection statistics
        """
        stats: Dict[str, Any] = {
            "nef_client": {
                "url": self.nef_url,
            }
        }
        try:
            stats["nef_client"]["circuit_breaker_stats"] = self.client.get_circuit_breaker_stats()
        except Exception:  # pragma: no cover - defensive
            pass

        stats["components"] = self._components.get_stats()
        return stats
    
    def cleanup_resources(self) -> None:
        """Clean up resources used by the collector."""
        try:
            # Clean up NEF client
            if hasattr(self.client, 'close'):
                self.client.close()
            if hasattr(self, "_components"):
                self._components.cleanup()

            # Unregister from resource manager
            if hasattr(self, '_resource_id') and self._resource_id:
                global_resource_manager.unregister_resource(self._resource_id, force_cleanup=False)
                self._resource_id = None
            
            self.logger.info("NEF data collector resources cleaned up")
        except Exception as e:
            self.logger.error(f"Error cleaning up collector resources: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up resources."""
        self.cleanup_resources()


class AsyncNEFDataCollector:
    """Async version of NEF data collector for improved performance."""
    
    def __init__(self, nef_url=None, username=None, password=None, data_dir: Optional[str] = None):
        """Initialize the async data collector."""
        # Use environment-aware defaults
        nef_url = nef_url or env_constants.NEF_URL
        
        # Use async NEF client instead of sync client
        self.client = AsyncNEFClient(
            base_url=nef_url,
            username=username,
            password=password,
            timeout=env_constants.NEF_TIMEOUT,
            max_retries=env_constants.COLLECTION_RETRIES
        )
        self.nef_url = nef_url
        self.username = username
        self.password = password
        self.data_dir = data_dir or os.path.join(os.path.dirname(__file__), 'collected_data')
        os.makedirs(self.data_dir, exist_ok=True)

        # Set up logger for this collector
        self.logger = logging.getLogger('AsyncNEFDataCollector')

        max_ues = env_constants.UE_TRACKING_MAX_UES
        ttl_hours = env_constants.UE_TRACKING_TTL_HOURS

        self._components = _CollectorComponents(
            logger=self.logger,
            data_dir=self.data_dir,
            max_ues=max_ues,
            ue_ttl_hours=ttl_hours,
            signal_window_size=SIGNAL_WINDOW_SIZE,
            position_window_size=POSITION_WINDOW_SIZE,
        )

        self._last_stats_log = time.time()
        self._stats_log_interval = env_constants.STATS_LOG_INTERVAL
        self._missing_qos_logged: set[str] = set()

    def _log_memory_stats(self):
        """Log memory usage statistics for tracking dictionaries."""
        now = time.time()
        if now - self._last_stats_log >= self._stats_log_interval:
            stats = self._components.get_stats()
            if stats:
                self.logger.info("=== Async NEF Collector Runtime Statistics ===")
                for name, details in stats.items():
                    self.logger.info("%s: %s", name, details)
                self.logger.info("=== End Runtime Statistics ===")
            self._last_stats_log = now

    async def login(self) -> bool:
        """Authenticate with the NEF emulator via the async client."""
        try:
            return await self.client.login()
        except (AsyncNEFClientError, CircuitBreakerError) as exc:
            self.logger.error(f"NEF authentication error: {exc}")
            return False

    async def get_ue_movement_state(self) -> Dict[str, Any]:
        """Get current state of all UEs in movement."""
        try:
            state = await self.client.get_ue_movement_state()
            if state:
                ue_count = len(state.keys())
                self.logger.info(f"Retrieved state for {ue_count} moving UEs")
            return state
        except (AsyncNEFClientError, CircuitBreakerError) as exc:
            self.logger.error(f"NEF movement state error: {exc}")
            return {}
        except Exception as e:
            self.logger.error(f"Error getting UE movement state: {str(e)}")
            return {}

    async def collect_training_data(
        self, 
        duration: float = None, 
        interval: float = None
    ) -> List[Dict[str, Any]]:
        """
        Async collect training data for the specified duration with comprehensive validation.
        """
        # Use environment defaults if not provided
        duration = duration if duration is not None else env_constants.COLLECTION_DURATION
        interval = interval if interval is not None else env_constants.COLLECTION_INTERVAL
        
        # Use common validation logic (same as sync version)
        try:
            duration, interval = DataCollectionValidator.validate_collection_parameters(duration, interval)
        except ValidationError as e:
            raise ValueError(str(e)) from e
            
        # Check if NEF client is available
        try:
            status = await self.client.get_status()
            if not getattr(status, "status_code", 0) == 200:
                raise AsyncNEFClientError("NEF service not available")
        except Exception as e:
            raise AsyncNEFClientError(f"Cannot connect to NEF service: {e}") from e

        self.logger.info(
            f"Starting async data collection for {duration} seconds at {interval}s intervals"
        )

        collected_data = []
        start_time = time.time()
        end_time = start_time + duration

        while time.time() < end_time:
            with exception_context("Async data collection iteration", reraise=False) as handler:
                # Log memory statistics periodically
                self._log_memory_stats()
                
                ue_state = await self.get_ue_movement_state()

                # Process UEs concurrently when possible
                if ue_state:
                    # Get feature vectors for all UEs in parallel
                    ue_ids = list(ue_state.keys())
                    feature_vectors = await self.client.batch_get_feature_vectors(ue_ids)
                    
                    # Process each UE sample
                    for ue_id, ue_data in ue_state.items():
                        fv = feature_vectors.get(ue_id, {}) or {}
                        service_type, service_priority, qos_requirements = await self._fetch_qos_requirements(ue_id)
                        sample = self._collect_sample(
                            ue_id,
                            ue_data,
                            fv,
                            service_type,
                            service_priority,
                            qos_requirements,
                        )
                        if sample:
                            collected_data.append(sample)

            # Always sleep between iterations, regardless of errors
            await asyncio.sleep(interval)

        if not collected_data:
            self.logger.warning("No data collected; writing empty data file")

        self._save_collected_data(collected_data)
        return collected_data

    async def _fetch_qos_requirements(self, ue_id: str) -> Tuple[Optional[str], Optional[int], Optional[Dict[str, float]]]:
        client_method = getattr(self.client, "get_qos_requirements", None)
        if client_method is None:
            if ue_id not in self._missing_qos_logged:
                self.logger.info(
                    "Async NEF client does not expose QoS endpoint; skipping QoS for UE %s",
                    ue_id,
                )
                self._missing_qos_logged.add(ue_id)
            return None, None, None

        try:
            payload = await client_method(ue_id)
        except AsyncNEFClientError as exc:
            if ue_id not in self._missing_qos_logged:
                self.logger.warning(
                    "Failed to fetch QoS requirements for UE %s: %s",
                    ue_id,
                    exc,
                )
                self._missing_qos_logged.add(ue_id)
            return None, None, None
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.exception("Unexpected error retrieving QoS requirements for UE %s", ue_id)
            return None, None, None

        service_type, service_priority, qos_requirements = _normalize_qos_payload(
            payload,
            ue_id,
            self.logger,
        )

        if (
            service_type is not None
            or service_priority is not None
            or qos_requirements is not None
        ) and ue_id in self._missing_qos_logged:
            self._missing_qos_logged.discard(ue_id)

        if (
            service_type is None
            and service_priority is None
            and qos_requirements is None
            and ue_id not in self._missing_qos_logged
        ):
            self.logger.warning(
                "QoS requirements unavailable after validation for UE %s", ue_id
            )
            self._missing_qos_logged.add(ue_id)

        return service_type, service_priority, qos_requirements

    def _collect_sample(
        self,
        ue_id: str,
        ue_data: dict,
        fv: dict,
        service_type: Optional[str],
        service_priority: Optional[int],
        qos_requirements: Optional[Dict[str, float]],
    ) -> dict | None:
        """Create a single training sample with async-fetched feature vector."""
        # Use common validation for UE data (same as sync version)
        sample_data = validate_ue_sample_data(ue_id, ue_data, f"UE {ue_id} sample")
        if sample_data is None:
            return None
            
        ue_id, ue_data, latitude, longitude = sample_data
        
        # Validate Cell_id
        try:
            connected_cell_id = UEDataValidator.validate_cell_id(ue_data)
        except ValidationError:
            self.logger.debug("No Cell_id for UE %s", ue_id)
            return None

        return self._components.build_sample(
            ue_id=ue_id,
            ue_data=ue_data,
            feature_vector=fv or {},
            connected_cell_id=connected_cell_id,
            service_type=service_type,
            service_priority=service_priority,
            qos_requirements=qos_requirements,
            timestamp=time.time(),
        )

    def _save_collected_data(self, collected_data: list) -> None:
        """Persist collected samples to disk (same as sync version)."""
        filepath = self._components.persistence.save_training_data(collected_data, filename_prefix="async_training_data")
        if not collected_data:
            self.logger.warning("Saved empty training data file to %s", filepath)
        else:
            self.logger.info(
                "Collected %d samples, saved to %s",
                len(collected_data),
                filepath,
            )

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the async data collection system."""
        stats: Dict[str, Any] = {
            "nef_client": {"url": self.nef_url}
        }
        try:
            stats["nef_client"]["circuit_breaker_stats"] = self.client.get_circuit_breaker_stats()
        except Exception:  # pragma: no cover - defensive
            pass
        stats["components"] = self._components.get_stats()
        stats["performance"] = {"async_enabled": True, "concurrent_requests": True}
        return stats
    
    async def cleanup_resources(self) -> None:
        """Clean up async resources used by the collector."""
        try:
            await self.client.close()
            self._components.cleanup()
            self.logger.info("Async NEF data collector resources cleaned up")
        except Exception as e:
            self.logger.error(f"Error cleaning up async collector resources: {e}")

    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - clean up resources."""
        await self.cleanup_resources()
