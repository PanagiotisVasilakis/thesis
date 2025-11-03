"""Central schema definitions for UE metric features."""

from __future__ import annotations

from ._feast_compat import Field, Float32, String

# Ordered mapping of feature names to Feast data types. The QoS metrics are kept
# alongside the existing mobility telemetry so that both the offline Parquet
# source and online SQLite store evolve in lockstep.
UE_METRIC_FIELDS: list[tuple[str, object]] = [
    ("speed", Float32),
    ("velocity", Float32),
    ("acceleration", Float32),
    ("cell_load", Float32),
    ("handover_count", Float32),
    ("time_since_handover", Float32),
    ("signal_trend", Float32),
    ("environment", Float32),
    ("heading_change_rate", Float32),
    ("path_curvature", Float32),
    ("rsrp_stddev", Float32),
    ("sinr_stddev", Float32),
    # QoS metrics exposed to the feature store.
    ("latency_ms", Float32),
    ("throughput_mbps", Float32),
    ("packet_loss_rate", Float32),
    ("altitude", Float32),
    ("latitude", Float32),
    ("longitude", Float32),
    ("connected_to", String),
    ("optimal_antenna", String),
]

# Convenience list of feature names consumed by retrieval utilities and tests.
UE_METRIC_FEATURE_NAMES = [name for name, _ in UE_METRIC_FIELDS]


def feast_fields() -> list[Field]:
    """Return Feast :class:`Field` definitions for the UE metrics schema."""

    return [Field(name=name, dtype=dtype) for name, dtype in UE_METRIC_FIELDS]
