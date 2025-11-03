"""LightGBM-based antenna selection model."""

import os
import logging
from .antenna_selector import AntennaSelector
from .base_model_mixin import BaseModelMixin
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score
from sklearn.calibration import CalibratedClassifierCV
import numpy as np

logger = logging.getLogger(__name__)


class LightGBMSelector(BaseModelMixin, AntennaSelector):
    """Antenna selector using a LightGBM classifier."""

    def __init__(
        self,
        model_path: str | None = None,
        *,
        neighbor_count: int | None = None,
        config_path: str | None = None,
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
        
        # Confidence calibration configuration
        self.calibrate_confidence = os.getenv("CALIBRATE_CONFIDENCE", "1").lower() in ("1", "true", "yes")
        self.calibration_method = os.getenv("CALIBRATION_METHOD", "isotonic")  # or 'sigmoid'
        self.calibrated_model = None  # Will be set during training if enabled
        
        super().__init__(
            model_path=model_path,
            neighbor_count=neighbor_count,
            config_path=config_path,
        )

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
        """Train the model with optional validation, early stopping, and confidence calibration.
        
        This method is thread-safe and acquires the model lock during training.
        
        Confidence calibration improves the quality of probability estimates,
        making confidence values more reliable for QoS-aware decisions.
        """
        if not training_data:
            raise ValueError("Training data cannot be empty")
        
        # Use the mixin's build_dataset method and scale features
        X_arr, y_arr = self.build_dataset(training_data)
        self.scaler.fit(X_arr)
        X_arr = self.scaler.transform(X_arr)
        X_train, X_val, y_train, y_val = self._split_dataset(
            X_arr, y_arr, validation_split
        )

        eval_set = [(X_val, y_val)] if X_val is not None else None
        fit_params = {}
        if eval_set:
            fit_params["eval_set"] = eval_set
            if early_stopping_rounds:
                fit_params["callbacks"] = [lgb.early_stopping(early_stopping_rounds)]

        # Thread-safe training with lock
        with self._model_lock:
            self.model.fit(X_train, y_train, **fit_params)
            
            # Apply confidence calibration if enabled and we have validation data
            if self.calibrate_confidence and X_val is not None and len(X_val) >= 30:
                try:
                    logger.info(f"Calibrating confidence estimates using {self.calibration_method} method...")
                    
                    # Use CalibratedClassifierCV with pre-split data
                    # We pass cv='prefit' since model is already trained
                    self.calibrated_model = CalibratedClassifierCV(
                        self.model,
                        method=self.calibration_method,
                        cv='prefit'
                    )
                    
                    # Fit calibration on validation set
                    self.calibrated_model.fit(X_val, y_val)
                    
                    logger.info("Confidence calibration completed successfully")
                    
                    # Test calibrated vs uncalibrated
                    uncal_probs = self.model.predict_proba(X_val)
                    cal_probs = self.calibrated_model.predict_proba(X_val)
                    
                    # Log calibration impact
                    uncal_conf_avg = np.mean(np.max(uncal_probs, axis=1))
                    cal_conf_avg = np.mean(np.max(cal_probs, axis=1))
                    
                    logger.info(f"Avg confidence before calibration: {uncal_conf_avg:.3f}")
                    logger.info(f"Avg confidence after calibration: {cal_conf_avg:.3f}")
                    
                except Exception as e:
                    logger.warning(f"Confidence calibration failed: {e}, using uncalibrated model")
                    self.calibrated_model = None
            else:
                self.calibrated_model = None
                if self.calibrate_confidence:
                    if X_val is None:
                        logger.info("Skipping calibration: no validation data")
                    elif len(X_val) < 30:
                        logger.info(f"Skipping calibration: insufficient validation samples ({len(X_val)} < 30)")
            
            metrics = {
                "samples": len(X_arr),
                "classes": len(set(y_arr)),
                "feature_importance": {
                    name: float(val)
                    for name, val in zip(
                        self.feature_names, self.model.feature_importances_
                    )
                },
                "confidence_calibrated": self.calibrated_model is not None,
                "calibration_method": self.calibration_method if self.calibrated_model else None
            }

            if eval_set:
                # Use calibrated model for validation metrics if available
                prediction_model = self.calibrated_model if self.calibrated_model else self.model
                y_pred = prediction_model.predict(X_val)
                metrics["val_accuracy"] = float(accuracy_score(y_val, y_pred))
                metrics["val_f1"] = float(
                    f1_score(y_val, y_pred, average="weighted", zero_division=0)
                )
                
                # Add calibration metrics if calibrated
                if self.calibrated_model:
                    y_pred_uncal = self.model.predict(X_val)
                    metrics["val_accuracy_uncalibrated"] = float(accuracy_score(y_val, y_pred_uncal))
                    metrics["confidence_improvement"] = float(
                        metrics["val_accuracy"] - metrics["val_accuracy_uncalibrated"]
                    )

            return metrics



    def _split_dataset(
        self, X: np.ndarray, y: np.ndarray, validation_split: float
    ) -> tuple[np.ndarray, np.ndarray | None, np.ndarray, np.ndarray | None]:
        """Split dataset into train and validation parts."""
        if validation_split <= 0 or len(X) <= 1:
            return X, None, y, None

        from collections import Counter

        counts = Counter(y)
        stratify = y if all(c >= 2 for c in counts.values()) else None
        try:
            return train_test_split(
                X,
                y,
                test_size=validation_split,
                random_state=42,
                stratify=stratify,
            )
        except ValueError:
            return train_test_split(
                X,
                y,
                test_size=validation_split,
                random_state=42,
                stratify=None,
            )
