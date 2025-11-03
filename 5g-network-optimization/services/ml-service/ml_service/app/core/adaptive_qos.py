"""Adaptive QoS threshold management."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Dict

import os
import time


def _confidence_threshold(priority: int) -> float:
    priority = max(1, min(priority, 10))
    return 0.5 + (priority - 1) * (0.45 / 9)


@dataclass
class ServiceQoSStats:
    breach_rate: float = 0.0
    last_update: float = 0.0


class AdaptiveQoSThresholds:
    """Track QoS outcomes and adapt required confidence per service type."""

    def __init__(self) -> None:
        self._stats: Dict[str, ServiceQoSStats] = {}
        self._lock = Lock()

        self.alpha = float(os.getenv("QOS_ADAPTIVE_SMOOTHING", "0.2"))
        self.boost_factor = float(os.getenv("QOS_ADAPTIVE_BOOST_FACTOR", "0.3"))
        self.relax_factor = float(os.getenv("QOS_ADAPTIVE_RELAX_FACTOR", "0.2"))
        self.max_boost = float(os.getenv("QOS_ADAPTIVE_MAX_BOOST", "0.2"))
        self.max_relax = float(os.getenv("QOS_ADAPTIVE_MAX_RELAX", "0.1"))
        self.high_breach_threshold = float(os.getenv("QOS_ADAPTIVE_HIGH_RATE", "0.3"))
        self.low_breach_threshold = float(os.getenv("QOS_ADAPTIVE_LOW_RATE", "0.1"))

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()

    def observe_feedback(self, service_type: str, passed: bool) -> None:
        service = (service_type or "default").lower()
        sample = 0.0 if passed else 1.0

        with self._lock:
            stats = self._stats.get(service)
            now = time.time()
            if stats is None:
                self._stats[service] = ServiceQoSStats(breach_rate=sample, last_update=now)
                return

            alpha = min(max(self.alpha, 0.01), 1.0)
            stats.breach_rate = (1 - alpha) * stats.breach_rate + alpha * sample
            stats.last_update = now

    def get_required_confidence(self, service_type: str, priority: int) -> float:
        base = _confidence_threshold(priority)
        service = (service_type or "default").lower()

        with self._lock:
            stats = self._stats.get(service)
            if not stats:
                return base

            rate = stats.breach_rate

        if rate >= self.high_breach_threshold:
            boost = min(self.max_boost, rate * self.boost_factor)
            return min(0.99, base + boost)

        if rate <= self.low_breach_threshold:
            relax = min(self.max_relax, (self.low_breach_threshold - rate) * self.relax_factor)
            return max(0.5, base - relax)

        return base


adaptive_qos_manager = AdaptiveQoSThresholds()
