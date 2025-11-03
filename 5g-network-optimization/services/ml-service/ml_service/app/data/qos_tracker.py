"""Utilities for tracking post-handover QoS outcomes per UE.

This module maintains a rolling history of QoS measurements observed after
handover decisions. The tracker aggregates statistics (success rates, average
latency/throughput/jitter/loss) that later pipeline stages can use to bias
future predictions or adapt thresholds.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import mean
from typing import Deque, Dict, Iterable, Optional

import time

QoSMetricDict = Dict[str, float]


@dataclass
class QoSRecord:
    """Snapshot of observed QoS for a single UE at a point in time."""

    timestamp: float
    service_type: str
    metrics: QoSMetricDict
    passed: bool


class QoSHistoryTracker:
    """Maintain per-UE QoS history with rolling statistics.

    Parameters
    ----------
    window_seconds:
        Maximum age for data points retained in the rolling window.
    max_samples:
        Per-UE cap on stored measurements to avoid unbounded growth.
    """

    def __init__(self, window_seconds: float = 600.0, max_samples: int = 200) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_samples <= 0:
            raise ValueError("max_samples must be positive")

        self.window_seconds = float(window_seconds)
        self.max_samples = int(max_samples)
        self._history: Dict[str, Deque[QoSRecord]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def record(
        self,
        ue_id: str,
        service_type: str,
        metrics: QoSMetricDict,
        passed: bool,
        *,
        timestamp: Optional[float] = None,
    ) -> None:
        """Append a QoS observation to the UE history."""

        now = time.time() if timestamp is None else float(timestamp)
        history = self._history.setdefault(ue_id, deque(maxlen=self.max_samples))
        history.append(QoSRecord(now, service_type, dict(metrics), bool(passed)))
        self._prune(history, now)

    def get_qos_history(self, ue_id: str, window_seconds: Optional[float] = None) -> Dict[str, object]:
        """Return aggregated QoS statistics for ``ue_id`` within ``window_seconds``.

        The result contains:

        - ``sample_count``: number of measurements considered
        - ``success_rate``: fraction of "passed" measurements
        - ``violation_count``: count of failed checks
        - ``metrics``: per-metric averages and extrema
        - ``last_timestamp``: timestamp of latest observation
        - ``degradation_detected``: flag indicating low success rate
        """

        history = self._history.get(ue_id)
        if not history:
            return {
                "ue_id": ue_id,
                "sample_count": 0,
                "success_rate": None,
                "violation_count": 0,
                "metrics": {},
                "last_timestamp": None,
                "degradation_detected": False,
            }

        window = float(window_seconds) if window_seconds is not None else self.window_seconds
        cutoff = time.time() - window
        samples = [rec for rec in history if rec.timestamp >= cutoff]

        if not samples:
            return {
                "ue_id": ue_id,
                "sample_count": 0,
                "success_rate": None,
                "violation_count": 0,
                "metrics": {},
                "last_timestamp": history[-1].timestamp,
                "degradation_detected": False,
            }

        passed_samples = [rec for rec in samples if rec.passed]
        success_rate = len(passed_samples) / len(samples) if samples else None

        metrics_summary = self._summarise_metrics(sample.metrics for sample in samples)
        degradation = success_rate is not None and len(samples) >= 5 and success_rate < 0.8

        return {
            "ue_id": ue_id,
            "sample_count": len(samples),
            "success_rate": success_rate,
            "violation_count": len(samples) - len(passed_samples),
            "metrics": metrics_summary,
            "last_timestamp": samples[-1].timestamp,
            "degradation_detected": degradation,
        }

    def get_recent_samples(self, ue_id: str, limit: int = 20) -> Iterable[QoSRecord]:
        history = self._history.get(ue_id) or []
        return list(history)[-limit:]

    def has_degradation(self, ue_id: str, *, threshold: float = 0.8, min_samples: int = 5) -> bool:
        stats = self.get_qos_history(ue_id)
        success_rate = stats.get("success_rate")
        sample_count = stats.get("sample_count", 0)
        if success_rate is None:
            return False
        return sample_count >= min_samples and success_rate < threshold

    def reset(self, ue_id: Optional[str] = None) -> None:
        if ue_id is None:
            self._history.clear()
        else:
            self._history.pop(ue_id, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _prune(self, history: Deque[QoSRecord], now: float) -> None:
        cutoff = now - self.window_seconds
        while history and history[0].timestamp < cutoff:
            history.popleft()

    @staticmethod
    def _summarise_metrics(samples: Iterable[QoSMetricDict]) -> Dict[str, Dict[str, float]]:
        aggregates: Dict[str, Dict[str, float]] = {}
        for metrics in samples:
            for metric, value in metrics.items():
                if not isinstance(value, (int, float)):
                    continue
                entry = aggregates.setdefault(metric, {"values": []})
                entry["values"].append(float(value))

        summary: Dict[str, Dict[str, float]] = {}
        for metric, data in aggregates.items():
            values = data["values"]
            if not values:
                continue
            summary[metric] = {
                "avg": mean(values),
                "min": min(values),
                "max": max(values),
            }
        return summary


