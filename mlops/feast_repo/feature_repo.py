"""Feast repository entry point referencing the shared feature store package."""

from feast import FeatureStore

from mlops.feature_store.feature_repo import ue, ue_metrics_view


def apply() -> None:
    """Apply the entity and feature view definitions to the Feast registry."""

    fs = FeatureStore(".")
    fs.apply([ue, ue_metrics_view])


if __name__ == "__main__":
    apply()
