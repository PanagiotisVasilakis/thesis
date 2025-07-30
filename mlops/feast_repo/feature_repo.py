from datetime import timedelta
from feast import (
    Entity,
    FeatureView,
    Field,
    FileSource,
    FeatureStore,
)
from feast.types import Float32, String

ue = Entity(name="ue_id", join_keys=["ue_id"])

source = FileSource(
    path="data/training_data.parquet",
    timestamp_field="timestamp",
)

ue_metrics_view = FeatureView(
    name="ue_metrics_view",
    entities=[ue],
    ttl=timedelta(days=1),
    schema=[
        Field(name="speed", dtype=Float32),
        Field(name="velocity", dtype=Float32),
        Field(name="acceleration", dtype=Float32),
        Field(name="cell_load", dtype=Float32),
        Field(name="handover_count", dtype=Float32),
        Field(name="signal_trend", dtype=Float32),
        Field(name="environment", dtype=Float32),
        Field(name="latitude", dtype=Float32),
        Field(name="longitude", dtype=Float32),
        Field(name="connected_to", dtype=String),
        Field(name="optimal_antenna", dtype=String),
    ],
    online=True,
    source=source,
)

def apply():
    fs = FeatureStore(".")
    fs.apply([ue, ue_metrics_view])

if __name__ == "__main__":
    apply()
