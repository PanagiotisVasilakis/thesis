from __future__ import annotations

"""Utility helpers for interacting with the Feast feature store."""
from pathlib import Path
from typing import Iterable

import pandas as pd
from feast import FeatureStore


REPO_PATH = Path(__file__).resolve().parents[6] / "mlops" / "feast_repo"


def _store() -> FeatureStore:
    """Return a ``FeatureStore`` instance for the local repo."""
    return FeatureStore(str(REPO_PATH))


def ingest_samples(samples: Iterable[dict]) -> None:
    """Ingest collected samples into the feature store."""
    data = list(samples)
    if not data:
        return
    fs = _store()
    df = pd.DataFrame(data)
    fs.ingest("ue_metrics_view", df)


def fetch_training_data(samples: Iterable[dict]) -> list[dict]:
    """Retrieve feature rows for the given samples."""
    data = list(samples)
    if not data:
        return []
    fs = _store()
    entity_df = pd.DataFrame(
        {
            "ue_id": [s["ue_id"] for s in data],
            "timestamp": pd.to_datetime([s["timestamp"] for s in data]),
        }
    )
    feature_list = [
        "ue_metrics:speed",
        "ue_metrics:velocity",
        "ue_metrics:acceleration",
        "ue_metrics:cell_load",
        "ue_metrics:handover_count",
        "ue_metrics:signal_trend",
        "ue_metrics:environment",
        "ue_metrics:latitude",
        "ue_metrics:longitude",
        "ue_metrics:connected_to",
        "ue_metrics:optimal_antenna",
    ]
    df = fs.get_historical_features(entity_df=entity_df, features=feature_list).to_df()
    df = df.drop(columns=["event_timestamp"])
    return df.to_dict(orient="records")
