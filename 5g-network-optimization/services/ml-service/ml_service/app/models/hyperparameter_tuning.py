"""Hyperparameter tuning utilities using Optuna.

This module provides automated hyperparameter optimization for the LightGBM
model, enabling systematic search for optimal parameters.

Usage:
    from ml_service.app.models.hyperparameter_tuning import optimize_hyperparameters
    
    best_params, study = optimize_hyperparameters(training_data, n_trials=50)
    
Thesis Value:
    - Documents systematic parameter search
    - Provides optimization history for analysis
    - Enables reproducible model selection
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import accuracy_score, f1_score
from sklearn.utils.class_weight import compute_class_weight
from sklearn.preprocessing import StandardScaler
from collections import Counter

logger = logging.getLogger(__name__)

# Optuna is optional
try:
    import optuna
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    logger.warning("Optuna not installed. Hyperparameter tuning unavailable.")


class HyperparameterTuner:
    """Automated hyperparameter optimization for antenna selection models.
    
    Uses Optuna for Bayesian optimization to find optimal LightGBM parameters.
    """
    
    DEFAULT_SEARCH_SPACE = {
        "n_estimators": (50, 300),
        "max_depth": (3, 15),
        "num_leaves": (15, 63),
        "learning_rate": (0.01, 0.3),
        "feature_fraction": (0.5, 1.0),
        "reg_alpha": (0.0, 1.0),
        "reg_lambda": (0.0, 1.0),
        "min_child_samples": (5, 100),
    }
    
    def __init__(
        self,
        feature_names: List[str],
        search_space: Optional[Dict[str, Tuple[float, float]]] = None,
        n_cv_folds: int = 3,
        metric: str = "f1",
    ):
        """Initialize the tuner.
        
        Args:
            feature_names: List of feature names
            search_space: Custom search space (optional)
            n_cv_folds: Number of CV folds for evaluation
            metric: Optimization metric ('accuracy' or 'f1')
        """
        self.feature_names = feature_names
        self.search_space = search_space or self.DEFAULT_SEARCH_SPACE
        self.n_cv_folds = n_cv_folds
        self.metric = metric
        self.scaler = StandardScaler()
        self.best_params: Optional[Dict[str, Any]] = None
        self.study: Optional["optuna.Study"] = None
    
    def is_available(self) -> bool:
        """Check if Optuna is available."""
        return OPTUNA_AVAILABLE
    
    def _build_dataset(
        self,
        training_data: List[Dict],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Convert training data to numpy arrays."""
        X, y = [], []
        
        for sample in training_data:
            features = []
            for name in self.feature_names:
                val = sample.get(name)
                if val is None:
                    val = 0.0
                elif isinstance(val, str):
                    # Handle categorical features
                    val = hash(val) % 1000 / 1000.0
                else:
                    try:
                        val = float(val)
                    except (TypeError, ValueError):
                        val = 0.0
                features.append(val)
            
            X.append(features)
            y.append(sample.get("optimal_antenna", "unknown"))
        
        return np.array(X, dtype=float), np.array(y)
    
    def _create_objective(
        self,
        X: np.ndarray,
        y: np.ndarray,
    ):
        """Create Optuna objective function."""
        import lightgbm as lgb
        
        def objective(trial: "optuna.Trial") -> float:
            params = {
                "n_estimators": trial.suggest_int(
                    "n_estimators",
                    *self.search_space.get("n_estimators", (50, 300))
                ),
                "max_depth": trial.suggest_int(
                    "max_depth",
                    *self.search_space.get("max_depth", (3, 15))
                ),
                "num_leaves": trial.suggest_int(
                    "num_leaves",
                    *self.search_space.get("num_leaves", (15, 63))
                ),
                "learning_rate": trial.suggest_float(
                    "learning_rate",
                    *self.search_space.get("learning_rate", (0.01, 0.3)),
                    log=True
                ),
                "feature_fraction": trial.suggest_float(
                    "feature_fraction",
                    *self.search_space.get("feature_fraction", (0.5, 1.0))
                ),
                "reg_alpha": trial.suggest_float(
                    "reg_alpha",
                    *self.search_space.get("reg_alpha", (0.0, 1.0))
                ),
                "reg_lambda": trial.suggest_float(
                    "reg_lambda",
                    *self.search_space.get("reg_lambda", (0.0, 1.0))
                ),
                "min_child_samples": trial.suggest_int(
                    "min_child_samples",
                    *self.search_space.get("min_child_samples", (5, 100))
                ),
                "random_state": 42,
                "verbosity": -1,
            }
            
            # Cross-validation
            skf = StratifiedKFold(n_splits=self.n_cv_folds, shuffle=True, random_state=42)
            scores = []
            
            for train_idx, val_idx in skf.split(X, y):
                X_train, X_val = X[train_idx], X[val_idx]
                y_train, y_val = y[train_idx], y[val_idx]
                
                # Compute class weights
                classes = np.array(sorted(set(y_train)))
                weights = compute_class_weight("balanced", classes=classes, y=y_train)
                class_weights = {str(c): float(w) for c, w in zip(classes, weights)}
                
                model = lgb.LGBMClassifier(**params, class_weight=class_weights)
                
                model.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    callbacks=[lgb.early_stopping(10, verbose=False)],
                )
                
                y_pred = model.predict(X_val)
                
                if self.metric == "f1":
                    score = f1_score(y_val, y_pred, average="weighted", zero_division=0)
                else:
                    score = accuracy_score(y_val, y_pred)
                
                scores.append(score)
            
            return float(np.mean(scores))
        
        return objective
    
    def optimize(
        self,
        training_data: List[Dict],
        n_trials: int = 50,
        timeout: Optional[int] = None,
        show_progress: bool = True,
    ) -> Dict[str, Any]:
        """Run hyperparameter optimization.
        
        Args:
            training_data: Training samples
            n_trials: Number of optimization trials
            timeout: Maximum time in seconds (optional)
            show_progress: Whether to log progress
            
        Returns:
            Dictionary with optimization results
        """
        if not OPTUNA_AVAILABLE:
            return {
                "error": "Optuna not installed. Run: pip install optuna",
                "best_params": None,
            }
        
        # Build dataset
        X, y = self._build_dataset(training_data)
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)
        
        # Check class distribution
        class_counts = Counter(y)
        if len(class_counts) < 2:
            return {
                "error": "Need at least 2 classes for optimization",
                "best_params": None,
            }
        
        # Create study
        optuna.logging.set_verbosity(
            optuna.logging.INFO if show_progress else optuna.logging.WARNING
        )
        
        self.study = optuna.create_study(
            direction="maximize",
            study_name="antenna_selector_optimization",
        )
        
        objective = self._create_objective(X_scaled, y)
        
        logger.info(f"Starting hyperparameter optimization with {n_trials} trials...")
        
        self.study.optimize(
            objective,
            n_trials=n_trials,
            timeout=timeout,
            show_progress_bar=show_progress,
        )
        
        self.best_params = self.study.best_params
        
        results = {
            "best_params": self.best_params,
            "best_score": float(self.study.best_value),
            "metric": self.metric,
            "n_trials": len(self.study.trials),
            "optimization_history": [
                {
                    "trial": t.number,
                    "value": float(t.value) if t.value else None,
                    "params": t.params,
                }
                for t in self.study.trials[:20]  # Limit to first 20 for API response
            ],
            "importance": self._get_param_importance() if len(self.study.trials) >= 10 else None,
        }
        
        logger.info(
            f"Optimization complete. Best {self.metric}: {results['best_score']:.4f}"
        )
        logger.info(f"Best parameters: {self.best_params}")
        
        return results
    
    def _get_param_importance(self) -> Dict[str, float]:
        """Get hyperparameter importance scores."""
        if self.study is None or len(self.study.trials) < 10:
            return {}
        
        try:
            importance = optuna.importance.get_param_importances(self.study)
            return {k: float(v) for k, v in importance.items()}
        except Exception as e:
            logger.warning(f"Failed to compute param importance: {e}")
            return {}


def optimize_hyperparameters(
    training_data: List[Dict],
    feature_names: List[str],
    n_trials: int = 50,
    metric: str = "f1",
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Convenience function for hyperparameter optimization.
    
    Args:
        training_data: Training samples
        feature_names: Feature names
        n_trials: Number of trials
        metric: Optimization metric
        
    Returns:
        Tuple of (best_params, full_results)
    """
    tuner = HyperparameterTuner(feature_names, metric=metric)
    results = tuner.optimize(training_data, n_trials=n_trials)
    return results.get("best_params"), results
