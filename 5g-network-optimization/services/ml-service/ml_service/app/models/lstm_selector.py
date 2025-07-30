"""LSTM-based antenna selection model."""

from .antenna_selector import (
    AntennaSelector,
    FALLBACK_ANTENNA_ID,
    FALLBACK_CONFIDENCE,
)
import numpy as np
import tensorflow as tf
import os
import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score


class LSTMSelector(AntennaSelector):
    """Antenna selector using a simple LSTM network."""

    def __init__(self, model_path: str | None = None, *, neighbor_count: int | None = None, epochs: int = 5, units: int = 16) -> None:
        self.epochs = epochs
        self.units = units
        self.classes_: list[str] | None = None
        super().__init__(model_path=model_path, neighbor_count=neighbor_count)

    def _initialize_model(self):
        """Initialize an uncompiled Keras model."""
        self.model = None

    def _build_dataset(self, training_data: list) -> tuple[np.ndarray, np.ndarray]:
        """Convert samples to arrays for training."""
        X, y = [], []
        for sample in training_data:
            features = self.extract_features(sample)
            X.append([features[name] for name in self.feature_names])
            y.append(sample.get("optimal_antenna"))
        return np.array(X, dtype=float), np.array(y)

    def _compile(self, num_classes: int):
        """Create and compile the underlying Keras model."""
        model = tf.keras.Sequential(
            [
                tf.keras.layers.Input(shape=(1, len(self.feature_names))),
                tf.keras.layers.LSTM(self.units),
                tf.keras.layers.Dense(num_classes, activation="softmax"),
            ]
        )
        model.compile(
            optimizer="adam",
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )
        self.model = model

    def train(self, training_data: list, *, validation_split: float = 0.2) -> dict:
        """Train the LSTM model."""
        X, y = self._build_dataset(training_data)
        classes, y_idx = np.unique(y, return_inverse=True)
        self.classes_ = list(classes)
        self._compile(len(classes))

        X = X.reshape((len(X), 1, len(self.feature_names)))
        if validation_split > 0 and len(X) > 1:
            X_train, X_val, y_train, y_val = train_test_split(
                X, y_idx, test_size=validation_split, random_state=42
            )
        else:
            X_train, X_val, y_train, y_val = X, None, y_idx, None

        history = self.model.fit(
            X_train,
            y_train,
            epochs=self.epochs,
            batch_size=32,
            verbose=0,
            validation_data=(X_val, y_val) if X_val is not None else None,
        )

        metrics = {
            "samples": len(X),
            "classes": len(classes),
            "history": history.history,
        }
        if X_val is not None and len(X_val):
            y_pred = np.argmax(self.model.predict(X_val, verbose=0), axis=1)
            metrics["val_accuracy"] = float(accuracy_score(y_val, y_pred))
        return metrics

    def predict(self, features: dict) -> dict:
        """Predict using the trained LSTM model."""
        if self.model is None or self.classes_ is None:
            return {
                "antenna_id": FALLBACK_ANTENNA_ID,
                "confidence": FALLBACK_CONFIDENCE,
            }
        X = np.array([[features[name] for name in self.feature_names]], dtype=float)
        X = X.reshape((1, 1, len(self.feature_names)))
        probs = self.model.predict(X, verbose=0)[0]
        idx = int(np.argmax(probs))
        return {"antenna_id": self.classes_[idx], "confidence": float(probs[idx])}

    def save(self, path=None):
        """Save model and metadata."""
        save_path = path or self.model_path
        if save_path:
            save_path = os.fspath(save_path)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            self.model.save(save_path)
            joblib.dump(
                {
                    "feature_names": self.feature_names,
                    "neighbor_count": self.neighbor_count,
                    "classes": self.classes_,
                },
                save_path + ".meta",
            )
            return True
        return False

    def load(self, path=None):
        """Load model and metadata."""
        load_path = path or self.model_path
        if load_path and os.path.exists(load_path):
            load_path = os.fspath(load_path)
            self.model = tf.keras.models.load_model(load_path)
            meta_path = load_path + ".meta"
            if os.path.exists(meta_path):
                meta = joblib.load(meta_path)
                self.feature_names = meta.get("feature_names", self.feature_names)
                self.neighbor_count = meta.get("neighbor_count", self.neighbor_count)
                self.classes_ = meta.get("classes")
            return True
        return False

