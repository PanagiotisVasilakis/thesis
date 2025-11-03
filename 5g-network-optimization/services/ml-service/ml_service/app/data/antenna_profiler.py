"""Per-antenna QoS profiling utilities.

This module aggregates QoS feedback per antenna / service-type pair so that the
prediction pipeline can bias away from antennas with a poor QoS track record.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import mean
from typing import Deque, Dict, Optional

import time


QoSMetricDict = Dict[str, float]


@dataclass
class AntennaQoSRecord:
    timestamp: float
    metrics: QoSMetricDict
    passed: bool


class AntennaQoSProfiler:
    """Track QoS performance per antenna and service type."""

    def __init__(self, window_seconds: float = 1800.0, max_samples: int = 500) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_samples <= 0:
            raise ValueError("max_samples must be positive")

        self.window_seconds = float(window_seconds)
        self.max_samples = int(max_samples)
        self._profiles: Dict[tuple[str, str], Deque[AntennaQoSRecord]] = {}

    def record(
        self,
        antenna_id: str,
        service_type: str,
        metrics: QoSMetricDict,
        passed: bool,
        *,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record a QoS measurement for an antenna/service combination."""

        now = time.time() if timestamp is None else float(timestamp)
        key = (antenna_id, service_type.lower())
        history = self._profiles.setdefault(key, deque(maxlen=self.max_samples))
        history.append(AntennaQoSRecord(now, dict(metrics), bool(passed)))
        self._prune(history, now)

    def get_profile(self, antenna_id: str, service_type: str) -> Dict[str, object]:
        key = (antenna_id, service_type.lower())
        history = self._profiles.get(key)
        if not history:
            return {
                "antenna_id": antenna_id,
                "service_type": service_type,
                "sample_count": 0,
                "success_rate": None,
                "violation_count": 0,
                "metrics": {},
                "last_timestamp": None,
            }

        cutoff = time.time() - self.window_seconds
        samples = [rec for rec in history if rec.timestamp >= cutoff]

        if not samples:
            return {
                "antenna_id": antenna_id,
                "service_type": service_type,
                "sample_count": 0,
                "success_rate": None,
                "violation_count": 0,
                "metrics": {},
                "last_timestamp": history[-1].timestamp,
            }

        passed_samples = [rec for rec in samples if rec.passed]
        success_rate = len(passed_samples) / len(samples) if samples else None
        metrics_summary = self._summarise_metrics(samples)

        return {
            "antenna_id": antenna_id,
            "service_type": service_type,
            "sample_count": len(samples),
            "success_rate": success_rate,
            "violation_count": len(samples) - len(passed_samples),
            "metrics": metrics_summary,
            "last_timestamp": samples[-1].timestamp,
        }

    def get_antenna_qos_score(
        self,
        antenna_id: str,
        service_type: str,
        *,
        default: float = 1.0,
    ) -> float:
        profile = self.get_profile(antenna_id, service_type)
        success_rate = profile.get("success_rate")
        if success_rate is None:
            return float(default)

        score = float(success_rate)
        metrics = profile.get("metrics", {})
        latency = metrics.get("latency_ms", {})
        throughput = metrics.get("throughput_mbps", {})
        jitter = metrics.get("jitter_ms", {})

        if latency:
            avg = latency.get("avg")
            if avg and avg > 100:
                score *= 0.8
            elif avg and avg > 50:
                score *= 0.9

        if throughput:
            avg_tp = throughput.get("avg")
            if avg_tp and avg_tp < 50:
                score *= 0.85

        if jitter:
            avg_jitter = jitter.get("avg")
            if avg_jitter and avg_jitter > 20:
                score *= 0.9

        return max(0.0, min(1.0, score))

    def is_poor_performer(
        self,
        antenna_id: str,
        service_type: str,
        *,
        threshold: float = 0.75,
        min_samples: int = 10,
    ) -> bool:
        profile = self.get_profile(antenna_id, service_type)
        success_rate = profile.get("success_rate")
        sample_count = profile.get("sample_count", 0)
        if success_rate is None:
            return False
        return sample_count >= min_samples and success_rate < threshold

    def reset(self, antenna_id: Optional[str] = None, service_type: Optional[str] = None) -> None:
        if antenna_id is None and service_type is None:
            self._profiles.clear()
            return

        if antenna_id is not None and service_type is not None:
            self._profiles.pop((antenna_id, service_type.lower()), None)
        else:
            keys_to_remove = [
                key
                for key in self._profiles
                if (antenna_id is None or key[0] == antenna_id)
                and (service_type is None or key[1] == service_type.lower())
            ]
            for key in keys_to_remove:
                self._profiles.pop(key, None)

    def _prune(self, history: Deque[AntennaQoSRecord], now: float) -> None:
        cutoff = now - self.window_seconds
        while history and history[0].timestamp < cutoff:
            history.popleft()

    @staticmethod
    def _summarise_metrics(samples: list[AntennaQoSRecord]) -> Dict[str, Dict[str, float]]:
        aggregates: Dict[str, list[float]] = {}
        for sample in samples:
            for metric, value in sample.metrics.items():
                if not isinstance(value, (int, float)):
                    continue
                aggregates.setdefault(metric, []).append(float(value))

        summary: Dict[str, Dict[str, float]] = {}
        for metric, values in aggregates.items():
            if not values:
                continue
            summary[metric] = {
                "avg": mean(values),
                "min": min(values),
                "max": max(values),
            }
        return summary


