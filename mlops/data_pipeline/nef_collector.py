"""Utilities to collect QoS requirements from the NEF API for MLOps pipelines."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

__all__ = [
    "NEFAPIError",
    "QoSValidationError",
    "QoSRequirements",
    "NEFAPIClient",
    "NEFQoSCollector",
]


LOGGER = logging.getLogger(__name__)


class NEFAPIError(RuntimeError):
    """Raised when the NEF API cannot be reached or returns an error."""


class QoSValidationError(ValueError):
    """Raised when QoS payloads returned by the NEF API fail validation."""


@dataclass(frozen=True)
class QoSRequirements:
    """Validated QoS requirements for a UE returned by the NEF API."""

    ue_id: str
    service_type: Optional[str]
    service_priority: Optional[int]
    thresholds: Dict[str, float]

    @classmethod
    def from_payload(
        cls,
        ue_id: str,
        payload: Any,
        *,
        required_thresholds: Sequence[str] | None = None,
        logger: logging.Logger | None = None,
    ) -> "QoSRequirements":
        """Create a :class:`QoSRequirements` instance from a NEF payload.

        Args:
            ue_id: Identifier of the UE.
            payload: Raw payload returned by the NEF API.
            required_thresholds: Optional iterable of threshold names that must
                be present in the payload.
            logger: Optional logger for validation diagnostics. Defaults to the
                module logger.

        Raises:
            QoSValidationError: If the payload is missing or malformed.
        """

        log = logger or LOGGER

        if payload in (None, {}):
            raise QoSValidationError(f"UE {ue_id} returned an empty QoS payload")

        if not isinstance(payload, dict):
            raise QoSValidationError(
                f"UE {ue_id} returned QoS payload of type {type(payload).__name__}"
            )

        def _coerce_service_type(raw: Any) -> Optional[str]:
            if raw is None:
                return None
            if isinstance(raw, str):
                value = raw.strip()
                return value or None
            log.warning("Invalid QoS service_type for UE %s: %r", ue_id, raw)
            return None

        def _coerce_priority(raw: Any) -> Optional[int]:
            if raw is None:
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                log.warning("Invalid QoS service_priority for UE %s: %r", ue_id, raw)
                return None

        def _lookup(keys: Iterable[str], source: Dict[str, Any]) -> Any:
            for key in keys:
                if key in source:
                    return source[key]
            return None

        service_type = _coerce_service_type(
            _lookup(["service_type", "serviceType"], payload)
        )
        service_priority = _coerce_priority(
            _lookup(["service_priority", "servicePriority"], payload)
        )

        candidate_sections: List[Any] = [
            payload.get("requirements"),
            payload.get("qos_requirements"),
            payload.get("qosRequirements"),
        ]

        requirements_section = next(
            (section for section in candidate_sections if isinstance(section, dict)),
            payload,
        )

        def _extract_float(keys: Iterable[str]) -> Optional[float]:
            if not isinstance(requirements_section, dict):
                return None
            for key in keys:
                if key not in requirements_section:
                    continue
                value = requirements_section.get(key)
                try:
                    return float(value)
                except (TypeError, ValueError):
                    log.warning("Invalid QoS %s for UE %s: %r", key, ue_id, value)
            return None

        normalized_thresholds: Dict[str, float] = {}
        key_mapping = {
            "latency_requirement_ms": [
                "latency_requirement_ms",
                "latencyRequirementMs",
                "latency_ms",
                "latency",
            ],
            "throughput_requirement_mbps": [
                "throughput_requirement_mbps",
                "throughputRequirementMbps",
                "throughput_mbps",
                "throughput",
            ],
            "reliability_pct": [
                "reliability_pct",
                "reliabilityPct",
                "reliability_percent",
                "reliability",
            ],
            "jitter_ms": ["jitter_ms", "jitterMs"],
        }

        for normalized_name, source_keys in key_mapping.items():
            value = _extract_float(source_keys)
            if value is not None:
                normalized_thresholds[normalized_name] = value

        if not normalized_thresholds:
            raise QoSValidationError(
                f"UE {ue_id} returned QoS payload without numeric thresholds"
            )

        if required_thresholds:
            missing = [
                threshold
                for threshold in required_thresholds
                if threshold not in normalized_thresholds
            ]
            if missing:
                raise QoSValidationError(
                    f"UE {ue_id} missing required QoS thresholds: {', '.join(missing)}"
                )

        return cls(
            ue_id=ue_id,
            service_type=service_type,
            service_priority=service_priority,
            thresholds=normalized_thresholds,
        )


class NEFAPIClient:
    """Minimal synchronous client for fetching QoS data from the NEF API."""

    def __init__(
        self,
        base_url: str,
        *,
        session: Optional[requests.Session] = None,
        timeout: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout

    def get_qos_requirements(self, ue_id: str) -> Dict[str, Any]:
        """Fetch QoS requirements for a UE from the NEF API."""

        url = f"{self._base_url}/nef/qos/{ue_id}"
        try:
            response = self._session.get(url, timeout=self._timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:  # pragma: no cover - network errors
            raise NEFAPIError(f"Failed to fetch QoS for UE {ue_id}: {exc}") from exc
        except ValueError as exc:
            raise NEFAPIError(
                f"NEF returned invalid JSON for UE {ue_id}: {exc}"
            ) from exc


@dataclass(frozen=True)
class CollectedQoSRecord:
    """Structured representation of collected QoS data for a UE."""

    ue_id: str
    collected_at: datetime
    service_type: Optional[str]
    service_priority: Optional[int]
    qos_requirements: Dict[str, float]

    def asdict(self) -> Dict[str, Any]:
        record = asdict(self)
        record["collected_at"] = self.collected_at.isoformat()
        return record


class NEFQoSCollector:
    """Collect QoS requirements from the NEF API for downstream processing."""

    def __init__(
        self,
        client: NEFAPIClient,
        *,
        required_thresholds: Sequence[str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._required_thresholds = tuple(required_thresholds) if required_thresholds else None
        self._logger = logger or LOGGER

    def collect_for_ue(self, ue_id: str) -> Optional[Dict[str, Any]]:
        """Collect QoS information for a single UE.

        Returns ``None`` when the NEF API fails or the payload cannot be validated.
        """

        try:
            payload = self._client.get_qos_requirements(ue_id)
        except NEFAPIError as exc:
            self._logger.error("Unable to fetch QoS for UE %s: %s", ue_id, exc)
            return None

        try:
            qos = QoSRequirements.from_payload(
                ue_id,
                payload,
                required_thresholds=self._required_thresholds,
                logger=self._logger,
            )
        except QoSValidationError as exc:
            self._logger.warning("Skipping UE %s due to invalid QoS payload: %s", ue_id, exc)
            return None

        record = CollectedQoSRecord(
            ue_id=qos.ue_id,
            collected_at=datetime.now(timezone.utc),
            service_type=qos.service_type,
            service_priority=qos.service_priority,
            qos_requirements=qos.thresholds,
        )
        return record.asdict()

    def collect_for_ues(self, ue_ids: Sequence[str]) -> List[Dict[str, Any]]:
        """Collect QoS information for multiple UEs."""

        records: List[Dict[str, Any]] = []
        for ue_id in ue_ids:
            record = self.collect_for_ue(ue_id)
            if record is not None:
                records.append(record)
        return records

