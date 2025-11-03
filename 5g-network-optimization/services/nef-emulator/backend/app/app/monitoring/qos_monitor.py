"""QoS monitoring utilities for tracking per-UE quality metrics.

This module implements the first phase of the QoS integration roadmap:
it provides in-memory storage for recent QoS measurements (latency, jitter,
throughput, packet loss) per UE with a configurable sliding window. The
monitor exposes helper methods for updating and retrieving recent metrics so
that higher-level components (e.g., `NetworkStateManager`, `HandoverEngine`)
can consume consistent QoS data.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class QoSMeasurement:
    """Represents a single QoS observation for a UE.

    Attributes
    ----------
    timestamp: float
        The observation timestamp (seconds since monotonic clock).
    latency_ms: float
        End-to-end latency in milliseconds.
    jitter_ms: float
        Jitter in milliseconds.
    throughput_mbps: float
        Throughput in megabits per second.
    packet_loss_rate: float
        Packet loss as a percentage (0.0 - 100.0).
    """

    timestamp: float
    latency_ms: float
    jitter_ms: float
    throughput_mbps: float
    packet_loss_rate: float


class QoSMonitor:
    """Store and aggregate recent QoS measurements per UE.

    Parameters
    ----------
    window_seconds: float, optional
        Size of the sliding window used to retain measurements. Older
        entries are pruned lazily on update and retrieval. Defaults to 30s.
    min_samples: int, optional
        Minimum number of samples to retain even if they fall outside the
        time window (useful for very low frequency updates). Defaults to 1.
    max_samples: int, optional
        Hard cap on the number of samples retained per UE. Defaults to 120
        (sufficient for 4Hz sampling over 30 seconds).
    """

    REQUIRED_FIELDS = {"latency_ms", "jitter_ms", "throughput_mbps", "packet_loss_rate"}

    def __init__(
        self,
        *,
        window_seconds: float = 30.0,
        min_samples: int = 1,
        max_samples: int = 120,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if min_samples <= 0:
            raise ValueError("min_samples must be positive")
        if max_samples <= 0:
            raise ValueError("max_samples must be positive")
        if min_samples > max_samples:
            raise ValueError("min_samples cannot exceed max_samples")

        self.window_seconds = float(window_seconds)
        self.min_samples = int(min_samples)
        self.max_samples = int(max_samples)

        self._lock = threading.RLock()
        self._measurements: Dict[str, Deque[QoSMeasurement]] = defaultdict(deque)

    # ------------------------------------------------------------------
    # Update helpers
    # ------------------------------------------------------------------
    def update_qos_metrics(self, ue_id: str, metrics: Dict[str, float]) -> QoSMeasurement:
        """Record a new QoS measurement for ``ue_id``.

        Parameters
        ----------
        ue_id: str
            Identifier of the UE the metrics belong to.
        metrics: Dict[str, float]
            Dictionary containing the required QoS fields.

        Returns
        -------
        QoSMeasurement
            The normalized measurement that was stored.

        Raises
        ------
        KeyError
            If any required metric is missing.
        ValueError
            If metric values are not finite numbers.
        """

        missing = self.REQUIRED_FIELDS.difference(metrics)
        if missing:
            raise KeyError(f"Missing QoS fields for {ue_id!r}: {sorted(missing)}")

        timestamp = time.monotonic()
        measurement = QoSMeasurement(
            timestamp=timestamp,
            latency_ms=self._as_float(metrics["latency_ms"], "latency_ms"),
            jitter_ms=self._as_float(metrics["jitter_ms"], "jitter_ms"),
            throughput_mbps=self._as_float(metrics["throughput_mbps"], "throughput_mbps"),
            packet_loss_rate=self._as_float(metrics["packet_loss_rate"], "packet_loss_rate"),
        )

        with self._lock:
            bucket = self._measurements[ue_id]
            bucket.append(measurement)
            if len(bucket) > self.max_samples:
                # Trim oldest entries conservatively.
                while len(bucket) > self.max_samples:
                    bucket.popleft()
            self._prune_locked(bucket)

        return measurement

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------
    def get_qos_metrics(self, ue_id: str) -> Optional[Dict[str, float]]:
        """Return aggregate QoS metrics for a UE.

        The result contains the latest sample and aggregated statistics for
        the configured window. ``None`` is returned if no samples are
        available.
        """

        with self._lock:
            bucket = self._measurements.get(ue_id)
            if not bucket:
                return None
            self._prune_locked(bucket)
            if not bucket:
                return None

            latest = bucket[-1]
            aggregates = self._compute_aggregates(bucket)

        return {
            "sample_count": aggregates["count"],
            "latest": {
                "timestamp": latest.timestamp,
                "latency_ms": latest.latency_ms,
                "jitter_ms": latest.jitter_ms,
                "throughput_mbps": latest.throughput_mbps,
                "packet_loss_rate": latest.packet_loss_rate,
            },
            "avg": aggregates["avg"],
            "min": aggregates["min"],
            "max": aggregates["max"],
        }

    def get_recent_samples(self, ue_id: str) -> List[QoSMeasurement]:
        """Return a copy of the recent QoS measurements for ``ue_id``."""

        with self._lock:
            bucket = self._measurements.get(ue_id)
            if not bucket:
                return []
            self._prune_locked(bucket)
            return list(bucket)

    def get_all_ue_ids(self) -> List[str]:
        """Return the list of UE identifiers with recorded metrics."""

        with self._lock:
            return [ue_id for ue_id, bucket in self._measurements.items() if bucket]

    def clear(self, ue_id: Optional[str] = None) -> None:
        """Clear stored measurements.

        If ``ue_id`` is provided only that UE is cleared, otherwise all
        measurements are flushed.
        """

        with self._lock:
            if ue_id is None:
                self._measurements.clear()
            else:
                self._measurements.pop(ue_id, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _prune_locked(self, bucket: Deque[QoSMeasurement]) -> None:
        """Remove samples that fall outside the sliding window."""

        if not bucket:
            return

        cutoff = time.monotonic() - self.window_seconds
        # Retain at least ``min_samples`` to ensure low-frequency updates
        # still return some information.
        while len(bucket) > self.min_samples and bucket[0].timestamp < cutoff:
            bucket.popleft()

    @staticmethod
    def _compute_aggregates(bucket: Iterable[QoSMeasurement]) -> Dict[str, Dict[str, float]]:
        """Compute aggregate statistics for a bucket of measurements."""

        count = 0
        sum_latency = sum_jitter = sum_throughput = sum_loss = 0.0
        min_latency = min_jitter = float("inf")
        min_throughput = min_loss = float("inf")
        max_latency = max_jitter = float("-inf")
        max_throughput = max_loss = float("-inf")

        for measurement in bucket:
            count += 1
            sum_latency += measurement.latency_ms
            sum_jitter += measurement.jitter_ms
            sum_throughput += measurement.throughput_mbps
            sum_loss += measurement.packet_loss_rate

            min_latency = min(min_latency, measurement.latency_ms)
            min_jitter = min(min_jitter, measurement.jitter_ms)
            min_throughput = min(min_throughput, measurement.throughput_mbps)
            min_loss = min(min_loss, measurement.packet_loss_rate)

            max_latency = max(max_latency, measurement.latency_ms)
            max_jitter = max(max_jitter, measurement.jitter_ms)
            max_throughput = max(max_throughput, measurement.throughput_mbps)
            max_loss = max(max_loss, measurement.packet_loss_rate)

        if count == 0:
            return {
                "count": 0,
                "avg": {},
                "min": {},
                "max": {},
            }

        avg_latency = sum_latency / count
        avg_jitter = sum_jitter / count
        avg_throughput = sum_throughput / count
        avg_loss = sum_loss / count

        return {
            "count": count,
            "avg": {
                "latency_ms": avg_latency,
                "jitter_ms": avg_jitter,
                "throughput_mbps": avg_throughput,
                "packet_loss_rate": avg_loss,
            },
            "min": {
                "latency_ms": min_latency,
                "jitter_ms": min_jitter,
                "throughput_mbps": min_throughput,
                "packet_loss_rate": min_loss,
            },
            "max": {
                "latency_ms": max_latency,
                "jitter_ms": max_jitter,
                "throughput_mbps": max_throughput,
                "packet_loss_rate": max_loss,
            },
        }

    @staticmethod
    def _as_float(value: float, field: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:  # noqa: PERF203 - explicit exception
            raise ValueError(f"Invalid value for {field}: {value!r}") from exc

        if result != result:  # NaN check
            raise ValueError(f"Invalid value for {field}: NaN is not allowed")

        return result


__all__ = ["QoSMonitor", "QoSMeasurement"]

