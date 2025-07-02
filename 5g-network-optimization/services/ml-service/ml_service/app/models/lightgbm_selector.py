"""LightGBM-based antenna selection model."""

from .antenna_selector import AntennaSelector, DEFAULT_TEST_FEATURES
import lightgbm as lgb


class LightGBMSelector(AntennaSelector):
    """Antenna selector using a LightGBM classifier."""

    def __init__(
        self,
        model_path: str | None = None,
        *,
        n_estimators: int = 100,
        max_depth: int = 10,
        num_leaves: int = 31,
        learning_rate: float = 0.1,
        feature_fraction: float = 1.0,
        **kwargs,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.num_leaves = num_leaves
        self.learning_rate = learning_rate
        self.feature_fraction = feature_fraction
        self.extra_params = kwargs
        super().__init__(model_path=model_path)


    def _initialize_model(self):
        """Initialize a new LightGBM model."""
        params = {
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "num_leaves": self.num_leaves,
            "learning_rate": self.learning_rate,
            "feature_fraction": self.feature_fraction,
            "random_state": 42,
        }
        params.update(self.extra_params)
        self.model = lgb.LGBMClassifier(**params)

