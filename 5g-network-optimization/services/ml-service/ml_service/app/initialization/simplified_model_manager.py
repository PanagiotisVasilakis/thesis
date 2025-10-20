"""Simplified model manager with reduced threading complexity."""
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime
from packaging.version import Version, InvalidVersion
from typing import Optional, Dict, List, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Semantic version of the expected model format
MODEL_VERSION = "1.0.0"
FEEDBACK_BUFFER_LIMIT = 1000

from ..errors import ModelError
from ..models import (EnsembleSelector, LightGBMSelector, LSTMSelector,
                      OnlineHandoverModel)

MODEL_CLASSES = {
    "lightgbm": LightGBMSelector,
    "lstm": LSTMSelector,
    "ensemble": EnsembleSelector,
    "online": OnlineHandoverModel,
}

from ..utils.env_utils import get_neighbor_count_from_env
from ..utils.synthetic_data import generate_synthetic_training_data
from ..utils.tuning import tune_and_train


def _load_metadata(path: str) -> dict:
    """Load metadata file with proper error handling."""
    meta_path = path + ".meta.json"
    if not os.path.exists(meta_path):
        return {}
    
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                ts = data.get("trained_at")
                if ts is not None:
                    try:
                        data["trained_at"] = datetime.fromisoformat(ts)
                    except ValueError:
                        logging.getLogger(__name__).warning(
                            "Invalid trained_at timestamp %s in %s", ts, meta_path
                        )
                        data["trained_at"] = None
                return data
    except (json.JSONDecodeError, ValueError) as exc:
        logging.getLogger(__name__).warning(
            "Failed to parse metadata from %s: %s", meta_path, exc
        )
    except (IOError, OSError) as exc:
        logging.getLogger(__name__).warning(
            "Failed to read metadata file %s: %s", meta_path, exc
        )
    return {}


def _parse_version_from_path(path: str) -> Optional[str]:
    """Extract semantic version from model filename."""
    base = os.path.basename(path)
    if "_v" in base:
        ver = base.rsplit("_v", 1)[-1].split(".joblib", 1)[0]
        if ver:
            return ver
    return None


class SimplifiedModelManager:
    """Simplified model manager with reduced threading complexity."""
    
    def __init__(self):
        self._model = None
        self._model_path: Optional[str] = None
        self._model_paths: Dict[str, str] = {}
        self._feedback_data: deque = deque(maxlen=FEEDBACK_BUFFER_LIMIT)
        self._lock = threading.RLock()  # Reentrant lock for simpler logic
        self._is_ready = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="model-")
        self._logger = logging.getLogger(__name__)
        
    def discover_versions(self, base_path: str) -> None:
        """Discover available model versions."""
        if not os.path.isdir(base_path):
            return
            
        discovered = {}
        try:
            for name in os.listdir(base_path):
                if not name.endswith(".joblib"):
                    continue
                path = os.path.join(base_path, name)
                if ver := _parse_version_from_path(path):
                    discovered[ver] = path
        except OSError as exc:
            self._logger.warning("Failed to discover model versions: %s", exc)
            return
            
        with self._lock:
            self._model_paths.update(discovered)
    
    def list_versions(self) -> List[str]:
        """Return sorted list of available model versions."""
        with self._lock:
            return sorted(self._model_paths.keys())
    
    def _create_model_instance(self, model_path: Optional[str] = None, 
                             model_type: Optional[str] = None,
                             neighbor_count: Optional[int] = None):
        """Create a model instance with proper configuration."""
        if model_type is None:
            model_type = os.environ.get("MODEL_TYPE", "lightgbm").lower()
            
        if neighbor_count is None:
            neighbor_count = get_neighbor_count_from_env(logger=self._logger)
            
        # Check metadata for model type override
        if model_path:
            meta = _load_metadata(model_path)
            meta_type = meta.get("model_type")
            if meta_type and meta_type != model_type:
                self._logger.warning(
                    "Model type mismatch: metadata has %s but %s was requested. Using metadata type.",
                    meta_type, model_type
                )
                model_type = meta_type
                
        model_cls = MODEL_CLASSES.get(model_type, LightGBMSelector)
        return model_cls(model_path=model_path, neighbor_count=neighbor_count)
    
    def _load_or_train_model(self, model_path: Optional[str], 
                           model_type: Optional[str] = None,
                           neighbor_count: Optional[int] = None):
        """Load existing model or train a new one."""
        model = self._create_model_instance(model_path, model_type, neighbor_count)
        
        # Try to load existing model
        if model_path and os.path.exists(model_path):
            try:
                if model.load(model_path):
                    self._logger.info("Model loaded successfully from %s", model_path)
                    return model
            except Exception as exc:
                self._logger.error("Failed to load model from %s: %s", model_path, exc)
        
        # Train new model
        self._logger.info("Training new model with synthetic data")
        try:
            training_data = generate_synthetic_training_data(500)
            
            if model_type == "lightgbm" and os.getenv("LIGHTGBM_TUNE") == "1":
                n_iter = int(os.getenv("LIGHTGBM_TUNE_N_ITER", "10"))
                cv = int(os.getenv("LIGHTGBM_TUNE_CV", "3"))
                self._logger.info("Tuning hyperparameters with n_iter=%s, cv=%s", n_iter, cv)
                metrics = tune_and_train(model, training_data, n_iter=n_iter, cv=cv)
            else:
                metrics = model.train(training_data)
            
            self._logger.info("Model trained with %d samples", metrics.get('samples', 0))
            
            # Save the trained model
            if model_path:
                try:
                    saved = model.save(
                        model_path,
                        model_type=model_type or os.environ.get("MODEL_TYPE", "lightgbm").lower(),
                        metrics=metrics,
                        version=MODEL_VERSION,
                    )
                    if not saved:
                        raise ModelError(f"Model save returned False for path {model_path}")
                    self._logger.info("Model saved to %s", model_path)
                except Exception as exc:
                    self._logger.error("Failed to save model to %s: %s", model_path, exc)
                    raise ModelError(f"Failed to persist model: {exc}") from exc
            
            return model
            
        except Exception as exc:
            self._logger.error("Model training failed: %s", exc)
            raise ModelError(f"Failed to initialize model: {exc}") from exc
    
    async def initialize_async(self, model_path: Optional[str] = None,
                              model_type: Optional[str] = None,
                              neighbor_count: Optional[int] = None) -> bool:
        """Initialize model asynchronously."""
        loop = asyncio.get_event_loop()
        
        try:
            # Discover model versions if path provided
            if model_path:
                base_dir = os.path.dirname(model_path)
                await loop.run_in_executor(self._executor, self.discover_versions, base_dir)
            
            # Load/train model in executor
            model = await loop.run_in_executor(
                self._executor, 
                self._load_or_train_model, 
                model_path, model_type, neighbor_count
            )
            
            # Update state atomically
            with self._lock:
                self._model = model
                self._model_path = model_path
                if model_path:
                    ver = _parse_version_from_path(model_path)
                    if ver:
                        self._model_paths[ver] = model_path
                self._is_ready.set()
            
            return True
            
        except Exception as exc:
            self._logger.error("Async model initialization failed: %s", exc)
            with self._lock:
                self._is_ready.set()  # Signal completion even on failure
            return False
    
    def initialize_sync(self, model_path: Optional[str] = None,
                       model_type: Optional[str] = None,
                       neighbor_count: Optional[int] = None):
        """Initialize model synchronously."""
        try:
            # Discover model versions
            if model_path:
                self.discover_versions(os.path.dirname(model_path))
            
            model = self._load_or_train_model(model_path, model_type, neighbor_count)
            
            with self._lock:
                self._model = model
                self._model_path = model_path
                if model_path:
                    ver = _parse_version_from_path(model_path)
                    if ver:
                        self._model_paths[ver] = model_path
                self._is_ready.set()
            
            return model
            
        except Exception as exc:
            with self._lock:
                self._is_ready.set()
            raise
    
    def get_model(self, timeout: Optional[float] = None):
        """Get the model instance, waiting for initialization if needed."""
        if not self._is_ready.wait(timeout):
            raise ModelError("Model initialization timeout")
            
        with self._lock:
            if self._model is None:
                raise ModelError("Model initialization failed")
            return self._model
    
    def is_ready(self) -> bool:
        """Check if model is ready."""
        return self._is_ready.is_set()
    
    def switch_version(self, version: str):
        """Switch to a different model version."""
        with self._lock:
            path = self._model_paths.get(version)
            if not path:
                raise ValueError(f"Unknown model version: {version}")
            
            backup_model = self._model
            backup_path = self._model_path
        
        try:
            # Load the requested version
            new_model = self._create_model_instance(path)
            if not new_model.load(path):
                raise ModelError(f"Failed to load model version {version}")
            
            with self._lock:
                self._model = new_model
                self._model_path = path
            
            self._logger.info("Switched to model version %s", version)
            return new_model
            
        except Exception as exc:
            # Restore previous model on failure
            with self._lock:
                self._model = backup_model
                self._model_path = backup_path
            self._logger.error("Failed to switch to version %s: %s", version, exc)
            raise ModelError(f"Version switch failed: {exc}") from exc
    
    def feed_feedback(self, sample: Dict[str, Any], success: bool = True) -> bool:
        """Feed feedback sample to the model."""
        model = self.get_model()
        retrained = False
        
        with self._lock:
            # Update online model if supported
            if hasattr(model, "update"):
                try:
                    model.update(sample, success=success)
                except Exception as exc:
                    self._logger.error("Model update failed: %s", exc)
            
            # Store feedback for potential retraining
            self._feedback_data.append(sample | {"success": success})
            
            # Check for drift and retrain if needed
            if hasattr(model, "drift_detected"):
                try:
                    if model.drift_detected():
                        self._logger.info("Drift detected, retraining model")
                        metrics = model.retrain(list(self._feedback_data))
                        self._feedback_data.clear()
                        self.save_model(metrics)
                        retrained = True
                except Exception as exc:
                    self._logger.error("Drift-triggered retraining failed: %s", exc)
        
        return retrained
    
    def save_model(self, metrics: Optional[Dict[str, Any]] = None) -> bool:
        """Save the current model."""
        with self._lock:
            model = self._model
            path = self._model_path
        
        if not model or not path or not hasattr(model, "save"):
            return False
        
        try:
            # Get model type from metadata or environment
            meta = _load_metadata(path) if path else {}
            model_type = meta.get("model_type") or os.environ.get("MODEL_TYPE", "lightgbm").lower()
            
            model.save(
                path,
                model_type=model_type,
                metrics=metrics,
                version=MODEL_VERSION,
            )
            self._logger.info("Model saved successfully to %s", path)
            return True
            
        except Exception as exc:
            self._logger.error("Failed to save model: %s", exc)
            return False
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get model metadata."""
        with self._lock:
            path = self._model_path or os.environ.get("MODEL_PATH")
        
        if not path:
            return {}
            
        meta = _load_metadata(path)
        ts = meta.get("trained_at")
        if isinstance(ts, datetime):
            meta["trained_at"] = ts.isoformat()
        return meta
    
    def shutdown(self):
        """Clean shutdown of the model manager."""
        self._executor.shutdown(wait=True)


# Global instance for backward compatibility
_manager_instance = None
_manager_lock = threading.Lock()


def get_manager() -> SimplifiedModelManager:
    """Get the global model manager instance."""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = SimplifiedModelManager()
    return _manager_instance