"""Feature view definitions for UE metrics."""

from __future__ import annotations

from datetime import timedelta

from feast import FeatureView

from .entities import ue
from .schema import feast_fields
from .sources import ue_metrics_source

# Feature view exposing mobility metrics and QoS observations for each UE. The
# TTL mirrors the previous configuration so existing backfills continue to work.
ue_metrics_view = FeatureView(
    name="ue_metrics_view",
    entities=[ue],
    ttl=timedelta(days=1),
    schema=feast_fields(),
    online=True,
    source=ue_metrics_source,
    description="UE telemetry enriched with QoS metrics",
)

__all__ = ["ue_metrics_view"]
