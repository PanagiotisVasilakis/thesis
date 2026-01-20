"""Incremental online model for handover decisions."""

from collections import deque
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
import numpy as np

from .antenna_selector import AntennaSelector


class OnlineHandoverModel(AntennaSelector):
    """Antenna selector that learns incrementally from feedback."""

    def __init__(
        self,
        model_path: str | None = None,
        *,
        neighbor_count: int | None = None,
        config_path: str | None = None,
        drift_window: int = 50,
        drift_threshold: float = 0.2,
    ) -> None:
        self.drift_window = drift_window
        self.drift_threshold = drift_threshold
        self.feedback_window: deque[int] = deque(maxlen=drift_window)
        self._classes: np.ndarray | None = None
        super().__init__(
            model_path=model_path,
            neighbor_count=neighbor_count,
            config_path=config_path,
        )

    def _initialize_model(self):
        """Initialise an SGDClassifier for online updates."""
        self.model = SGDClassifier(loss="log_loss", random_state=42)

    def _build_dataset(self, training_data: list) -> tuple[np.ndarray, np.ndarray]:
        X, y = [], []
        for sample in training_data:
            extracted = self.extract_features(sample)
            features = self._prepare_features_for_model(extracted)
            X.append([features[name] for name in self.feature_names])
            y.append(sample.get("optimal_antenna"))
        return np.array(X, dtype=float), np.array(y)

    def train(self, training_data: list) -> dict:
        """Train using ``partial_fit`` on the entire dataset.
        
        This method is thread-safe and acquires the model lock during training.
        """
        if not training_data:
            raise ValueError("Training data cannot be empty")
        
        X, y = self._build_dataset(training_data)
        self.scaler.fit(X)
        X = self.scaler.transform(X)
        classes = np.unique(y)
        
        # Thread-safe training with lock
        with self._model_lock:
            self._classes = classes
            self.model.partial_fit(X, y, classes=classes)
            return {"samples": len(X), "classes": len(classes)}

    def update(self, sample: dict, success: bool = True) -> None:
        """Update model incrementally from a single feedback sample.
        
        This method is thread-safe and acquires the model lock during update.
        """
        features = self.extract_features(sample)
        features = self._prepare_features_for_model(features)
        label = sample.get("optimal_antenna")
        if label is None:
            return
        
        X = np.array([[features[name] for name in self.feature_names]], dtype=float)
        if self.scaler:
            X = self.scaler.transform(X)
        
        # Thread-safe model update with lock
        with self._model_lock:
            if self._classes is None:
                self._classes = np.array([label])
                self.model.partial_fit(X, [label], classes=self._classes)
            else:
                if label not in self._classes:
                    self._classes = np.unique(np.append(self._classes, label))
                    self.model.partial_fit(X, [label], classes=self._classes)
                else:
                    self.model.partial_fit(X, [label])
            self.feedback_window.append(1 if success else 0)

    def drift_detected(self) -> bool:
        """Return True if recent feedback indicates model drift.
        
        This method is thread-safe as it only reads from the feedback window.
        """
        # Thread-safe read of feedback window (deque is thread-safe for reads)
        with self._model_lock:
            if len(self.feedback_window) < self.feedback_window.maxlen:
                return False
            accuracy = sum(self.feedback_window) / len(self.feedback_window)
            return accuracy < (1.0 - self.drift_threshold)

    def retrain(self, data: list) -> dict:
        """Retrain from the provided dataset.
        
        This method is thread-safe as it delegates to the thread-safe train method.
        """
        return self.train(data)
