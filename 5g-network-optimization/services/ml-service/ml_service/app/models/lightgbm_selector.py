"""LightGBM-based antenna selection model."""

from .antenna_selector import AntennaSelector
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score
import numpy as np


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

    def train(
        self,
        training_data: list,
        *,
        validation_split: float = 0.2,
        early_stopping_rounds: int | None = 20,
    ) -> dict:
        """Train the model with optional validation and early stopping."""

        X = []
        y = []
        for sample in training_data:
            features = self.extract_features(sample)
            X.append([features[name] for name in self.feature_names])
            y.append(sample.get("optimal_antenna"))

        X_arr = np.array(X)
        y_arr = np.array(y)

        X_val = None
        y_val = None
        if validation_split > 0 and len(X_arr) > 1:
            from collections import Counter

            counts = Counter(y_arr)
            stratify = y_arr if all(c >= 2 for c in counts.values()) else None
            try:
                X_train, X_val, y_train, y_val = train_test_split(
                    X_arr,
                    y_arr,
                    test_size=validation_split,
                    random_state=42,
                    stratify=stratify,
                )
            except ValueError:
                X_train, X_val, y_train, y_val = train_test_split(
                    X_arr,
                    y_arr,
                    test_size=validation_split,
                    random_state=42,
                    stratify=None,
                )
        else:
            X_train, y_train = X_arr, y_arr

        eval_set = [(X_val, y_val)] if X_val is not None else None

        fit_params = {}
        if eval_set:
            fit_params["eval_set"] = eval_set
            if early_stopping_rounds:
                fit_params["early_stopping_rounds"] = early_stopping_rounds
            fit_params["verbose"] = False

        self.model.fit(X_train, y_train, **fit_params)

        metrics = {
            "samples": len(X_arr),
            "classes": len(set(y_arr)),
            "feature_importance": dict(
                zip(self.feature_names, self.model.feature_importances_)
            ),
        }

        if eval_set:
            y_pred = self.model.predict(X_val)
            metrics["val_accuracy"] = float(accuracy_score(y_val, y_pred))
            metrics["val_f1"] = float(
                f1_score(y_val, y_pred, average="weighted", zero_division=0)
            )

        return metrics
