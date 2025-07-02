"""LightGBM-based antenna selection model."""

from .antenna_selector import AntennaSelector, DEFAULT_TEST_FEATURES
import lightgbm as lgb


class LightGBMSelector(AntennaSelector):
    """Antenna selector using a LightGBM classifier."""

    def _initialize_model(self):
        """Initialize a new LightGBM model."""
        self.model = lgb.LGBMClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
        )

