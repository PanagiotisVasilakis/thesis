"""Integration layer for state management with existing ML service components."""

import logging
import time
from typing import Dict, Any, Optional, List
import threading

from .state_management import (
    get_global_state_registry,
    get_ue_state_manager,
    get_model_state_manager,
    get_app_state_manager
)
from .state_observers import create_default_observer_chain
from ..core.dependency_injection import get_container
from ..core.interfaces import ModelInterface, CacheInterface, MetricsCollectorInterface
from ..utils.exception_handler import safe_execute
from ..config.constants import env_constants

logger = logging.getLogger(__name__)


class StateIntegrationManager:
    """Manager for integrating state management with existing system components."""
    
    def __init__(self):
        """Initialize state integration manager."""
        self._initialized = False
        self._observers_configured = False
        self._lock = threading.Lock()
        
        # Get state managers
        self._registry = get_global_state_registry()
        self._ue_state = get_ue_state_manager()
        self._model_state = get_model_state_manager()
        self._app_state = get_app_state_manager()
        
        logger.info("StateIntegrationManager initialized")
    
    def initialize(self) -> None:
        """Initialize state management integration."""
        with self._lock:
            if self._initialized:
                logger.warning("State integration already initialized")
                return
            
            try:
                # Configure observers
                self._configure_observers()
                
                # Initialize application state
                self._initialize_app_state()
                
                # Set up periodic state updates
                self._setup_periodic_updates()
                
                self._initialized = True
                logger.info("State management integration initialized successfully")
                
            except Exception as exc:
                logger.error(f"Failed to initialize state integration: {exc}")
                raise
    
    def _configure_observers(self) -> None:
        """Configure state observers for all state managers."""
        if self._observers_configured:
            return
        
        # Create default observer chain
        observer_chain = create_default_observer_chain()
        
        # Add observers to all state managers
        managers = self._registry.get_all_managers()
        for name, manager in managers.items():
            manager.add_observer(observer_chain)
            logger.debug(f"Added observer chain to state manager: {name}")
        
        self._observers_configured = True
        logger.info("State observers configured")
    
    def _initialize_app_state(self) -> None:
        """Initialize application-level state."""
        app_state_updates = {
            "startup_time": time.time(),
            "version": "1.0.0",
            "environment": "production",  # Could be read from config
            "state_management_enabled": True,
            "observers_enabled": True
        }
        
        self._app_state.update(app_state_updates, metadata={"action": "app_initialization"})
        logger.debug("Application state initialized")
    
    def _setup_periodic_updates(self) -> None:
        """Set up periodic state updates."""
        # This could be enhanced with a proper scheduler
        def update_system_stats():
            """Update system statistics in app state."""
            try:
                import psutil
                
                # Get system metrics
                memory_info = psutil.virtual_memory()
                cpu_percent = psutil.cpu_percent(interval=1)
                
                system_stats = {
                    "memory_usage_mb": memory_info.used / 1024 / 1024,
                    "memory_percent": memory_info.percent,
                    "cpu_percent": cpu_percent,
                    "timestamp": time.time()
                }
                
                self._app_state.update(system_stats, metadata={"action": "system_stats_update"})
                
            except ImportError:
                # psutil not available, use basic stats
                basic_stats = {
                    "timestamp": time.time(),
                    "system_monitoring": "limited"
                }
                self._app_state.update(basic_stats, metadata={"action": "basic_stats_update"})
            except Exception as exc:
                logger.error(f"Error updating system stats: {exc}")
        
        # Start background thread for periodic updates
        def periodic_update_worker():
            """Background worker for periodic state updates."""
            while self._initialized:
                try:
                    update_system_stats()
                    time.sleep(60)  # Update every minute
                except Exception as exc:
                    logger.error(f"Error in periodic update worker: {exc}")
                    time.sleep(60)
        
        update_thread = threading.Thread(target=periodic_update_worker, daemon=True)
        update_thread.start()
        
        logger.debug("Periodic state updates configured")
    
    def track_model_operation(self, operation_type: str, **kwargs) -> None:
        """Track model operation in state."""
        if not self._initialized:
            return
        
        metadata = {
            "action": "model_operation",
            "operation_type": operation_type,
            **kwargs
        }
        
        if operation_type == "prediction":
            self._model_state.increment_prediction_count(metadata)
        elif operation_type == "training":
            samples = kwargs.get("samples", 0)
            accuracy = kwargs.get("accuracy")
            self._model_state.update_training_completed(samples, accuracy, metadata)
        elif operation_type == "model_loaded":
            model_path = kwargs.get("model_path", "unknown")
            version = kwargs.get("version", "unknown")
            self._model_state.update_model_loaded(model_path, version, metadata)
    
    def track_ue_activity(self, ue_id: str, ue_data: Dict[str, Any], **kwargs) -> None:
        """Track UE activity in state."""
        if not self._initialized:
            return
        
        metadata = {
            "action": "ue_activity",
            **kwargs
        }
        
        self._ue_state.update_ue(ue_id, ue_data, metadata)
    
    def get_comprehensive_state_summary(self) -> Dict[str, Any]:
        """Get comprehensive state summary across all managers."""
        if not self._initialized:
            return {"error": "State management not initialized"}
        
        try:
            registry_summary = self._registry.get_registry_summary()
            ue_stats = self._ue_state.get_ue_stats() if self._ue_state else {}
            model_summary = self._model_state.get_model_summary() if self._model_state else {}
            app_state = self._app_state.get_all() if self._app_state else {}
            
            return {
                "registry": registry_summary,
                "ue_state": ue_stats,
                "model_state": model_summary,
                "app_state": app_state,
                "integration_status": {
                    "initialized": self._initialized,
                    "observers_configured": self._observers_configured
                }
            }
            
        except Exception as exc:
            logger.error(f"Error getting state summary: {exc}")
            return {"error": str(exc)}
    
    def shutdown(self) -> None:
        """Shutdown state management integration."""
        with self._lock:
            if not self._initialized:
                return
            
            try:
                # Persist all state
                persist_results = self._registry.persist_all_state()
                logger.info(f"State persistence results: {persist_results}")
                
                # Cleanup all managers
                self._registry.cleanup_all_managers()
                
                self._initialized = False
                logger.info("State management integration shutdown complete")
                
            except Exception as exc:
                logger.error(f"Error during state management shutdown: {exc}")


# Global integration manager instance
_integration_manager: Optional[StateIntegrationManager] = None
_manager_lock = threading.Lock()


def get_state_integration_manager() -> StateIntegrationManager:
    """Get the global state integration manager."""
    global _integration_manager
    
    if _integration_manager is None:
        with _manager_lock:
            if _integration_manager is None:
                _integration_manager = StateIntegrationManager()
    
    return _integration_manager


def initialize_state_management() -> None:
    """Initialize state management for the application."""
    manager = get_state_integration_manager()
    manager.initialize()


def shutdown_state_management() -> None:
    """Shutdown state management for the application."""
    global _integration_manager
    
    if _integration_manager:
        _integration_manager.shutdown()


# Enhanced wrapper functions for existing components
class StateAwareModelWrapper:
    """Wrapper for model interface that tracks state."""
    
    def __init__(self, model: ModelInterface):
        """Initialize with model instance."""
        self._model = model
        self._integration_manager = get_state_integration_manager()
    
    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Predict with state tracking."""
        result = self._model.predict(features)
        
        # Track prediction in state
        self._integration_manager.track_model_operation(
            "prediction",
            antenna_id=result.get("antenna_id"),
            confidence=result.get("confidence"),
            feature_count=len(features)
        )
        
        return result
    
    async def predict_async(self, features: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Async predict with state tracking."""
        result = await self._model.predict_async(features, **kwargs)
        
        # Track async prediction in state
        self._integration_manager.track_model_operation(
            "prediction",
            antenna_id=result.get("antenna_id"),
            confidence=result.get("confidence"),
            feature_count=len(features),
            async_operation=True
        )
        
        return result
    
    def train(self, training_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Train with state tracking."""
        result = self._model.train(training_data)
        
        # Track training in state
        self._integration_manager.track_model_operation(
            "training",
            samples=result.get("samples", len(training_data)),
            classes=result.get("classes"),
            feature_importance=result.get("feature_importance")
        )
        
        return result
    
    async def train_async(self, training_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """Async train with state tracking."""
        result = await self._model.train_async(training_data, **kwargs)
        
        # Track async training in state
        self._integration_manager.track_model_operation(
            "training",
            samples=result.get("samples", len(training_data)),
            classes=result.get("classes"),
            async_operation=True
        )
        
        return result
    
    def extract_features(self, data: Dict[str, Any], include_neighbors: bool = True) -> Dict[str, Any]:
        """Extract features (pass through)."""
        return self._model.extract_features(data, include_neighbors)
    
    def save(self, path: Optional[str] = None, **kwargs) -> bool:
        """Save with state tracking."""
        result = self._model.save(path, **kwargs)
        
        if result:
            self._integration_manager.track_model_operation(
                "model_saved",
                model_path=path,
                version=kwargs.get("version", "unknown")
            )
        
        return result
    
    def load(self, path: Optional[str] = None) -> bool:
        """Load with state tracking."""
        result = self._model.load(path)
        
        if result:
            self._integration_manager.track_model_operation(
                "model_loaded",
                model_path=path
            )
        
        return result


class StateAwareUEProcessor:
    """Processor for UE data that tracks state."""
    
    def __init__(self):
        """Initialize UE processor."""
        self._integration_manager = get_state_integration_manager()
    
    def process_ue_data(self, ue_id: str, ue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process UE data with state tracking."""
        # Track UE activity
        self._integration_manager.track_ue_activity(
            ue_id,
            ue_data,
            processing_time=time.time(),
            data_fields=list(ue_data.keys())
        )
        
        # Return processed data (could include additional processing)
        return {
            "ue_id": ue_id,
            "processed_at": time.time(),
            "state_tracked": True,
            **ue_data
        }
    
    def get_ue_state(self, ue_id: str) -> Optional[Dict[str, Any]]:
        """Get current UE state."""
        ue_manager = get_ue_state_manager()
        return ue_manager.get_ue(ue_id) if ue_manager else None
    
    def get_active_ues(self) -> List[str]:
        """Get list of active UEs."""
        ue_manager = get_ue_state_manager()
        return ue_manager.get_active_ues() if ue_manager else []


# Convenience functions for state management integration
def track_prediction(ue_id: str, features: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Track prediction with state management."""
    manager = get_state_integration_manager()
    
    # Track model operation
    manager.track_model_operation(
        "prediction",
        ue_id=ue_id,
        antenna_id=result.get("antenna_id"),
        confidence=result.get("confidence"),
        feature_count=len(features)
    )
    
    # Track UE activity
    manager.track_ue_activity(
        ue_id,
        {
            "last_prediction": time.time(),
            "predicted_antenna": result.get("antenna_id"),
            "confidence": result.get("confidence")
        },
        activity_type="prediction"
    )


def track_training(training_data: List[Dict[str, Any]], result: Dict[str, Any]) -> None:
    """Track training with state management."""
    manager = get_state_integration_manager()
    
    manager.track_model_operation(
        "training",
        samples=len(training_data),
        classes=result.get("classes"),
        accuracy=result.get("accuracy"),
        training_duration=result.get("training_duration")
    )


def get_system_state_summary() -> Dict[str, Any]:
    """Get comprehensive system state summary."""
    manager = get_state_integration_manager()
    return manager.get_comprehensive_state_summary()


def is_state_management_ready() -> bool:
    """Check if state management is ready."""
    try:
        manager = get_state_integration_manager()
        return manager._initialized
    except Exception:
        return False