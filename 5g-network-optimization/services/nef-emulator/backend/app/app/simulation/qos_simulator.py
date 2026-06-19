"""Synthetic QoS metric generator for the NEF emulator."""

from __future__ import annotations

import os
from typing import Dict, Optional


class QoSSimulator:
    """Generate deterministic QoS proxies from SINR, bandwidth, and load.

    The simulator is conservative: poor RF quality or congested antennas
    degrade latency/throughput and increase jitter / packet loss. The goal is
    not to be physically perfect, but to provide metrics that react sensibly to
    changes so the ML vs A3 comparison can reason about QoS trade-offs.
    """

    def __init__(
        self,
        *,
        base_latency_ms: float = 12.0,
        min_latency_ms: float = 4.0,
        max_latency_ms: float = 80.0,
        max_throughput_mbps: float = 400.0,
    ) -> None:
        def _env_float(name: str, default: float) -> float:
            value = os.getenv(name)
            if value is None:
                return default
            try:
                return float(value)
            except ValueError:
                return default

        base_latency_ms = _env_float("QOS_BASE_LATENCY_MS", base_latency_ms)
        min_latency_ms = _env_float("QOS_MIN_LATENCY_MS", min_latency_ms)
        max_latency_ms = _env_float("QOS_MAX_LATENCY_MS", max_latency_ms)
        max_throughput_mbps = _env_float("QOS_MAX_THROUGHPUT_MBPS", max_throughput_mbps)

        self.base_latency_ms = base_latency_ms
        self.min_latency_ms = min_latency_ms
        self.max_latency_ms = max_latency_ms
        self.max_throughput_mbps = max_throughput_mbps
        self.model_version = "sinr_cqi_v1"

    _CQI = (
        (-6.7, 0.1523), (-4.7, 0.2344), (-2.3, 0.3770),
        (0.2, 0.6016), (2.4, 0.8770), (4.3, 1.1758),
        (5.9, 1.4766), (8.1, 1.9141), (10.3, 2.4063),
        (11.7, 2.7305), (14.1, 3.3223), (16.3, 3.9023),
        (18.7, 4.5234), (21.0, 5.1152), (22.7, 5.5547),
    )

    @classmethod
    def spectral_efficiency(cls, sinr_db: float) -> float:
        efficiency = 0.0
        for threshold, candidate in cls._CQI:
            if sinr_db < threshold:
                break
            efficiency = candidate
        return efficiency

    # ------------------------------------------------------------------
    def estimate(self, context: Dict[str, object]) -> Optional[Dict[str, float]]:
        """Return QoS metrics for the provided UE context.

        Expected keys inside ``context``:
          * ``position``: (x, y, z) meters
          * ``speed``: float (m/s)
          * ``connected_to``: antenna id (str) or ``None``
          * ``neighbor_sinrs``: dict[antenna_id -> SINR dB]
          * ``neighbor_cell_loads``: dict[antenna_id -> load count]
        """

        serving_id = context.get("connected_to")
        if not serving_id:
            return None

        sinr_map = context.get("neighbor_sinrs") or {}
        loads = context.get("neighbor_cell_loads") or {}
        serving_sinr = sinr_map.get(serving_id)
        if serving_sinr is None:
            return None
        serving_sinr = float(serving_sinr)
        load = float(loads.get(serving_id, 0))
        bandwidth_hz = float(context.get("bandwidth_hz", 100e6) or 100e6)
        speed = float(context.get("speed", 0.0) or 0.0)
        efficiency = self.spectral_efficiency(serving_sinr)
        resource_share = 1.0 / max(1.0, 1.0 + load)
        throughput = bandwidth_hz / 1e6 * efficiency * 0.75 * resource_share
        throughput = max(0.0, min(self.max_throughput_mbps, throughput))
        retransmission_penalty = max(0.0, -5.0 - serving_sinr)
        latency = 5.0 + 1.5 * load + 1.2 * retransmission_penalty + speed / 40.0
        latency = max(self.min_latency_ms, min(self.max_latency_ms, latency))
        jitter = 0.5 + 0.15 * latency + 0.5 * load
        jitter = max(0.5, min(50.0, jitter))
        packet_loss = min(20.0, 0.1 + 1.5 * retransmission_penalty)

        return {
            "latency_ms": float(latency),
            "jitter_ms": float(jitter),
            "throughput_mbps": float(throughput),
            "packet_loss_rate": float(packet_loss),
        }
