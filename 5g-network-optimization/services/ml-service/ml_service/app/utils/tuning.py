"""Hyperparameter tuning helpers for LightGBM models."""

from typing import Any, Dict, List, Tuple

import numpy as np
from sklearn.model_selection import RandomizedSearchCV
import lightgbm as lgb

from ..models.lightgbm_selector import LightGBMSelector


def tune_lightgbm(
    X: np.ndarray,
    y: np.ndarray,
    n_iter: int = 20,
    cv: int = 3,
    random_state: int | None = 42,
) -> Tuple[lgb.LGBMClassifier, Dict[str, Any]]:
    """Return a tuned LightGBM classifier and best parameters."""

    estimator = lgb.LGBMClassifier(random_state=random_state)
    param_dist = {
        "num_leaves": range(20, 150),
        "learning_rate": np.linspace(0.01, 0.2, 20),
        "feature_fraction": np.linspace(0.6, 1.0, 5),
        "n_estimators": range(50, 200),
        "max_depth": range(-1, 16),
    }

    search = RandomizedSearchCV(
        estimator,
        param_distributions=param_dist,
        n_iter=n_iter,
        cv=cv,
        random_state=random_state,
        refit=True,
    )
    search.fit(X, y)
    return search.best_estimator_, search.best_params_


def tune_and_train(
    model: LightGBMSelector,
    training_data: List[dict],
    n_iter: int = 20,
    cv: int = 3,
) -> Dict[str, Any]:
    """Tune LightGBM hyperparameters and update ``model`` with the result."""

    X_arr, y_arr = model.build_dataset(training_data)

    best_estimator, best_params = tune_lightgbm(
        X_arr, y_arr, n_iter=n_iter, cv=cv
    )
    model.model = best_estimator

    return {
    "samples": len(X_arr),
        "best_params": best_params,
        "feature_importance": dict(
            zip(model.feature_names, model.model.feature_importances_)
        ),
    }
