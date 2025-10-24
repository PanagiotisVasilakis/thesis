"""Feast data sources for UE metrics features."""

from feast import FileSource

# Offline file source reading from the canonical Parquet dataset. Feast tracks
# event timestamps via the ``timestamp`` column to support both historical
# retrieval and online materialisation.
ue_metrics_source = FileSource(
    path="data/training_data.parquet",
    timestamp_field="timestamp",
    description="Parquet dataset containing UE telemetry and QoS metrics",
)

__all__ = ["ue_metrics_source"]
