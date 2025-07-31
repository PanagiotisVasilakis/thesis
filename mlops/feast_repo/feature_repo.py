from datetime import timedelta
from feast import (
    Entity,
    FeatureView,
    FileSource,
    FeatureStore,
)

from .constants import feast_fields

ue = Entity(name="ue_id", join_keys=["ue_id"])

source = FileSource(
    path="data/training_data.parquet",
    timestamp_field="timestamp",
)

ue_metrics_view = FeatureView(
    name="ue_metrics_view",
    entities=[ue],
    ttl=timedelta(days=1),
    schema=feast_fields(),
    online=True,
    source=source,
)

def apply():
    fs = FeatureStore(".")
    fs.apply([ue, ue_metrics_view])

if __name__ == "__main__":
    apply()
