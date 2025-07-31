from feast.types import Float32, String
from feast import Field

# Central list of ue_metrics feature names and types.
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
    ("altitude", Float32),
    ("latitude", Float32),
    ("longitude", Float32),
    ("connected_to", String),
    ("optimal_antenna", String),
]

# Ordered list of feature names for retrieval helpers.
UE_METRIC_FEATURE_NAMES = [name for name, _ in UE_METRIC_FIELDS]

# Helper to create Feast Field objects from the schema constant.
def feast_fields() -> list[Field]:
    return [Field(name=name, dtype=dtype) for name, dtype in UE_METRIC_FIELDS]
