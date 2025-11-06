from __future__ import annotations

"""Utility helpers for interacting with the Feast feature store."""
from pathlib import Path
from typing import Iterable
import os

import pandas as pd

try:
    from feast import FeatureStore  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised in environments without Feast
    class FeatureStore:  # type: ignore
        """Minimal stand-in used when Feast is not installed."""

        def __init__(self, path: str) -> None:
            self.path = path

        def ingest(self, *args, **kwargs):  # noqa: D401 - intentionally raises
            raise RuntimeError("Feast FeatureStore is not available in this environment")

        def get_historical_features(self, *args, **kwargs):  # noqa: D401 - intentionally raises
            raise RuntimeError("Feast FeatureStore is not available in this environment")

from mlops.feast_repo.constants import UE_METRIC_FEATURE_NAMES


ENV_REPO_PATH = "FEAST_REPO_PATH"
# Use the local Feast repository unless ``FEAST_REPO_PATH`` is explicitly set.
DEFAULT_REPO_PATH = Path(__file__).resolve().parents[6] / "mlops" / "feast_repo"
REPO_PATH = Path(os.getenv(ENV_REPO_PATH, DEFAULT_REPO_PATH))


def _store() -> FeatureStore:
    """Return a ``FeatureStore`` instance for the configured repo."""
    repo = Path(os.getenv(ENV_REPO_PATH, str(REPO_PATH)))
    return FeatureStore(str(repo))


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
    feature_list = [f"ue_metrics:{name}" for name in UE_METRIC_FEATURE_NAMES]
    df = fs.get_historical_features(entity_df=entity_df, features=feature_list).to_df()
    df = df.drop(columns=["event_timestamp"])
    return df.to_dict(orient="records")
