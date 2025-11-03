"""Synthetic QoS metric generator for the NEF emulator."""

from __future__ import annotations

import math
import random
from typing import Dict, Optional


class QoSSimulator:
    """Generate realistic-ish QoS metrics from RF conditions.

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
        self.base_latency_ms = base_latency_ms
        self.min_latency_ms = min_latency_ms
        self.max_latency_ms = max_latency_ms
        self.max_throughput_mbps = max_throughput_mbps
        self._rng = random.Random(42)

    # ------------------------------------------------------------------
    def estimate(self, context: Dict[str, object]) -> Optional[Dict[str, float]]:
        """Return QoS metrics for the provided UE context.

        Expected keys inside ``context``:
          * ``position``: (x, y, z) meters
          * ``speed``: float (m/s)
          * ``connected_to``: antenna id (str) or ``None``
          * ``neighbor_rsrp_dbm``: dict[antenna_id -> rsrp dBm]
          * ``neighbor_cell_loads``: dict[antenna_id -> load count]
        """

        serving_id = context.get("connected_to")
        if not serving_id:
            return None

        rsrp_map = context.get("neighbor_rsrp_dbm") or {}
        loads = context.get("neighbor_cell_loads") or {}
        serving_rsrp = rsrp_map.get(serving_id)
        if serving_rsrp is None:
            return None

        # Normalize RSRP (-120 dBm worst, -50 best) to [0, 1]
        quality = max(0.0, min(1.0, (serving_rsrp + 120.0) / 70.0))

        # Congestion penalty: assume load >= 10 indicates heavy usage.
        load = float(loads.get(serving_id, 0))
        load_penalty = min(load / 10.0, 2.0)  # capped penalty

        speed = float(context.get("speed", 0.0) or 0.0)
        speed_penalty = min(speed / 30.0, 1.5)

        # Latency decreases with quality but increases with penalties
        latency = self.base_latency_ms - quality * 6.0 + load_penalty * 5.0 + speed_penalty * 3.0
        latency = max(self.min_latency_ms, min(self.max_latency_ms, latency))

        # Throughput scales with quality and inversely with load
        throughput = self.max_throughput_mbps * quality / (1.0 + load_penalty)
        throughput = max(5.0, throughput)

        # Jitter grows when latency is high or quality poor
        jitter = 1.0 + (1.0 - quality) * 8.0 + load_penalty * 2.0
        jitter = max(0.5, min(50.0, jitter))

        # Packet loss primarily driven by quality; keep modest (<5%) in normal ops
        packet_loss = max(0.0, (1.0 - quality) * 4.0 + load_penalty * 1.5)
        packet_loss = min(20.0, packet_loss)

        # Add gentle randomness so metrics are not perfectly static.
        jitter *= 1.0 + self._rng.uniform(-0.1, 0.1)
        latency *= 1.0 + self._rng.uniform(-0.05, 0.05)
        throughput *= 1.0 + self._rng.uniform(-0.05, 0.05)
        packet_loss = max(0.0, packet_loss * (1.0 + self._rng.uniform(-0.1, 0.1)))

        return {
            "latency_ms": float(latency),
            "jitter_ms": float(jitter),
            "throughput_mbps": float(throughput),
            "packet_loss_rate": float(packet_loss),
        }

