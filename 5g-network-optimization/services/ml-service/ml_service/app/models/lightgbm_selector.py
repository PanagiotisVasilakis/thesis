"""LightGBM-based antenna selection model."""

import os
import logging
from collections import Counter

import lightgbm as lgb
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, classification_report
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.utils.class_weight import compute_class_weight

from .antenna_selector import AntennaSelector
from .base_model_mixin import BaseModelMixin
from ..utils.exception_handler import ModelError

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

        # Compute class distribution and weights for imbalance protection
        class_counts = Counter(y_arr)
        classes = np.array(sorted(class_counts.keys()))
        min_count = min(class_counts.values()) if class_counts else 0
        max_count = max(class_counts.values()) if class_counts else 0
        imbalance_ratio = float(max_count / min_count) if min_count else float("inf")

        if imbalance_ratio > 2.0:
            logger.warning(
                "High class imbalance detected during training: %.2f | distribution=%s",
                imbalance_ratio,
                dict(class_counts),
            )

        if len(classes) < 2:
            raise ModelError(
                "Training data must contain at least two classes, got %d" % len(classes)
            )

        if len(classes) > 0:
            weights = compute_class_weight(
                class_weight="balanced",
                classes=classes,
                y=y_arr,
            )
            class_weights = {str(cls): float(weight) for cls, weight in zip(classes, weights)}
            self.model.set_params(class_weight=class_weights)
        else:
            class_weights = {}

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

            # Detect collapsed predictors by inspecting training predictions
            train_predictions = self.model.predict(X_arr)
            unique_predictions = len({str(pred) for pred in train_predictions})
            expected_classes = len(classes) if len(classes) else unique_predictions
            diversity_threshold = max(1, int(np.ceil(expected_classes * 0.75)))

            if unique_predictions < diversity_threshold:
                msg = (
                    "Model collapse detected: only %d unique predictions (threshold=%d, classes=%d)"
                    % (unique_predictions, diversity_threshold, expected_classes)
                )
                logger.error(msg)
                raise ModelError(msg)

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
                "calibration_method": self.calibration_method if self.calibrated_model else None,
                "class_distribution": {str(cls): int(count) for cls, count in class_counts.items()},
                "class_weights": class_weights,
                "imbalance_ratio": imbalance_ratio,
                "unique_predictions": unique_predictions,
                "collapse_threshold": diversity_threshold,
            }

            if eval_set:
                # Use calibrated model for validation metrics if available
                prediction_model = self.calibrated_model if self.calibrated_model else self.model
                y_pred = prediction_model.predict(X_val)
                metrics["val_accuracy"] = float(accuracy_score(y_val, y_pred))
                metrics["val_f1"] = float(
                    f1_score(y_val, y_pred, average="weighted", zero_division=0)
                )
                
                # Add confusion matrix for thesis analysis
                try:
                    unique_classes = sorted(set(y_val) | set(y_pred))
                    cm = confusion_matrix(y_val, y_pred, labels=unique_classes)
                    metrics["confusion_matrix"] = cm.tolist()
                    metrics["confusion_matrix_labels"] = [str(c) for c in unique_classes]
                    
                    # Per-class metrics from classification report
                    report = classification_report(
                        y_val, y_pred, 
                        labels=unique_classes,
                        output_dict=True, 
                        zero_division=0
                    )
                    per_class = {}
                    for class_label in unique_classes:
                        class_key = str(class_label)
                        if class_key in report:
                            per_class[class_key] = {
                                "precision": float(report[class_key]["precision"]),
                                "recall": float(report[class_key]["recall"]),
                                "f1": float(report[class_key]["f1-score"]),
                                "support": int(report[class_key]["support"]),
                            }
                    metrics["per_class_metrics"] = per_class
                    
                    # Macro and weighted averages
                    if "macro avg" in report:
                        metrics["macro_precision"] = float(report["macro avg"]["precision"])
                        metrics["macro_recall"] = float(report["macro avg"]["recall"])
                        metrics["macro_f1"] = float(report["macro avg"]["f1-score"])
                    
                except Exception as e:
                    logger.warning(f"Failed to compute confusion matrix metrics: {e}")
                
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

    def train_with_cv(
        self,
        training_data: list,
        *,
        n_folds: int = 5,
        early_stopping_rounds: int | None = 20,
    ) -> dict:
        """Train with K-fold cross-validation for thesis-grade evaluation.
        
        This method reports mean ± std metrics across folds, which is the
        standard for academic ML evaluation. The final model is trained on
        all data after CV evaluation.
        
        Args:
            training_data: List of training samples
            n_folds: Number of cross-validation folds (default: 5)
            early_stopping_rounds: Early stopping patience
            
        Returns:
            Dictionary containing:
                - cv_scores: Per-fold accuracy scores
                - cv_mean_accuracy: Mean accuracy across folds
                - cv_std_accuracy: Standard deviation of accuracy
                - cv_mean_f1: Mean F1 across folds
                - cv_std_f1: Standard deviation of F1
                - final_model_metrics: Metrics from final training on all data
        """
        if not training_data:
            raise ValueError("Training data cannot be empty")
        
        if n_folds < 2:
            raise ValueError("n_folds must be at least 2")
        
        # Build and scale dataset
        X_arr, y_arr = self.build_dataset(training_data)
        self.scaler.fit(X_arr)
        X_scaled = self.scaler.transform(X_arr)
        
        # Check if we have enough samples for CV
        class_counts = Counter(y_arr)
        min_class_count = min(class_counts.values())
        
        if min_class_count < n_folds:
            logger.warning(
                f"Reducing n_folds from {n_folds} to {min_class_count} "
                f"due to small class size"
            )
            n_folds = max(2, min_class_count)
        
        # Perform stratified K-fold cross-validation
        skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
        
        fold_accuracies = []
        fold_f1_scores = []
        fold_details = []
        
        logger.info(f"Starting {n_folds}-fold cross-validation...")
        
        for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X_scaled, y_arr)):
            X_train_fold = X_scaled[train_idx]
            X_val_fold = X_scaled[val_idx]
            y_train_fold = y_arr[train_idx]
            y_val_fold = y_arr[val_idx]
            
            # Create fresh model for each fold
            fold_model = lgb.LGBMClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                num_leaves=self.num_leaves,
                learning_rate=self.learning_rate,
                feature_fraction=self.feature_fraction,
                random_state=42,
            )
            
            # Compute class weights for this fold
            classes = np.array(sorted(set(y_train_fold)))
            weights = compute_class_weight("balanced", classes=classes, y=y_train_fold)
            class_weights = {str(cls): float(w) for cls, w in zip(classes, weights)}
            fold_model.set_params(class_weight=class_weights)
            
            # Fit with early stopping
            fit_params = {}
            if early_stopping_rounds:
                fit_params["eval_set"] = [(X_val_fold, y_val_fold)]
                fit_params["callbacks"] = [lgb.early_stopping(early_stopping_rounds)]
            
            fold_model.fit(X_train_fold, y_train_fold, **fit_params)
            
            # Evaluate fold
            y_pred = fold_model.predict(X_val_fold)
            fold_acc = accuracy_score(y_val_fold, y_pred)
            fold_f1 = f1_score(y_val_fold, y_pred, average="weighted", zero_division=0)
            
            fold_accuracies.append(fold_acc)
            fold_f1_scores.append(fold_f1)
            fold_details.append({
                "fold": fold_idx + 1,
                "train_size": len(train_idx),
                "val_size": len(val_idx),
                "accuracy": float(fold_acc),
                "f1": float(fold_f1),
            })
            
            logger.info(f"Fold {fold_idx + 1}/{n_folds}: accuracy={fold_acc:.4f}, F1={fold_f1:.4f}")
        
        # Calculate CV statistics
        cv_metrics = {
            "n_folds": n_folds,
            "cv_scores": [float(s) for s in fold_accuracies],
            "cv_f1_scores": [float(s) for s in fold_f1_scores],
            "cv_mean_accuracy": float(np.mean(fold_accuracies)),
            "cv_std_accuracy": float(np.std(fold_accuracies)),
            "cv_mean_f1": float(np.mean(fold_f1_scores)),
            "cv_std_f1": float(np.std(fold_f1_scores)),
            "fold_details": fold_details,
            # Thesis-ready formatted strings
            "accuracy_report": f"{np.mean(fold_accuracies):.4f} ± {np.std(fold_accuracies):.4f}",
            "f1_report": f"{np.mean(fold_f1_scores):.4f} ± {np.std(fold_f1_scores):.4f}",
        }
        
        logger.info(
            f"Cross-validation complete: "
            f"Accuracy = {cv_metrics['accuracy_report']}, "
            f"F1 = {cv_metrics['f1_report']}"
        )
        
        # Train final model on all data
        logger.info("Training final model on all data...")
        final_metrics = self.train(training_data, validation_split=0.1)
        
        cv_metrics["final_model_metrics"] = final_metrics
        
        return cv_metrics

