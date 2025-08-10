"""Standardized state management patterns for the ML service."""

import threading
import time
import logging
from typing import Any, Dict, List, Optional, Callable, TypeVar, Generic
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import weakref

from ..utils.exception_handler import safe_execute, exception_context
from ..utils.resource_manager import global_resource_manager, ResourceType
from ..config.constants import env_constants

T = TypeVar('T')

logger = logging.getLogger(__name__)


class StateChangeType(Enum):
    """Types of state changes."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESET = "reset"


@dataclass
class StateChange:
    """Represents a state change event."""
    change_type: StateChangeType
    key: str
    old_value: Any
    new_value: Any
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "change_type": self.change_type.value,
            "key": self.key,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


class StateObserver(ABC):
    """Abstract observer for state changes."""
    
    @abstractmethod
    def on_state_changed(self, change: StateChange) -> None:
        """Handle state change notification."""
        pass


class StateManager(Generic[T]):
    """Generic state manager with observation and persistence capabilities."""
    
    def __init__(self, 
                 name: str,
                 max_history: int = 1000,
                 enable_persistence: bool = False,
                 persistence_interval: float = 30.0):
        """Initialize state manager.
        
        Args:
            name: Name of the state manager
            max_history: Maximum number of state changes to keep in history
            enable_persistence: Whether to enable state persistence
            persistence_interval: Interval for automatic state persistence
        """
        self.name = name
        self.max_history = max_history
        self.enable_persistence = enable_persistence
        self.persistence_interval = persistence_interval
        
        self._state: Dict[str, T] = {}
        self._observers: List[StateObserver] = []
        self._change_history: List[StateChange] = []
        self._lock = threading.RLock()
        self._last_persistence = time.time()
        
        # Register with resource manager
        self._resource_id = global_resource_manager.register_resource(
            self,
            ResourceType.OTHER,
            cleanup_method=self._cleanup_resources,
            metadata={"component": "StateManager", "name": name}
        )
        
        logger.debug(f"StateManager '{name}' initialized")
    
    def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """Get state value by key."""
        with self._lock:
            return self._state.get(key, default)
    
    def set(self, key: str, value: T, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Set state value."""
        with self._lock:
            old_value = self._state.get(key)
            self._state[key] = value
            
            # Create state change event
            change_type = StateChangeType.UPDATE if old_value is not None else StateChangeType.CREATE
            change = StateChange(
                change_type=change_type,
                key=key,
                old_value=old_value,
                new_value=value,
                timestamp=time.time(),
                metadata=metadata or {}
            )
            
            # Add to history
            self._add_to_history(change)
            
            # Notify observers
            self._notify_observers(change)
            
            # Check for auto-persistence
            self._check_auto_persistence()
    
    def delete(self, key: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Delete state value."""
        with self._lock:
            if key not in self._state:
                return False
            
            old_value = self._state.pop(key)
            
            # Create state change event
            change = StateChange(
                change_type=StateChangeType.DELETE,
                key=key,
                old_value=old_value,
                new_value=None,
                timestamp=time.time(),
                metadata=metadata or {}
            )
            
            # Add to history
            self._add_to_history(change)
            
            # Notify observers
            self._notify_observers(change)
            
            # Check for auto-persistence
            self._check_auto_persistence()
            
            return True
    
    def update(self, updates: Dict[str, T], metadata: Optional[Dict[str, Any]] = None) -> None:
        """Update multiple state values."""
        with self._lock:
            for key, value in updates.items():
                self.set(key, value, metadata)
    
    def reset(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Reset all state."""
        with self._lock:
            old_state = self._state.copy()
            self._state.clear()
            
            # Create reset change event
            change = StateChange(
                change_type=StateChangeType.RESET,
                key="*",
                old_value=old_state,
                new_value={},
                timestamp=time.time(),
                metadata=metadata or {}
            )
            
            # Add to history
            self._add_to_history(change)
            
            # Notify observers
            self._notify_observers(change)
    
    def get_all(self) -> Dict[str, T]:
        """Get all state values."""
        with self._lock:
            return self._state.copy()
    
    def keys(self) -> List[str]:
        """Get all state keys."""
        with self._lock:
            return list(self._state.keys())
    
    def size(self) -> int:
        """Get number of state entries."""
        with self._lock:
            return len(self._state)
    
    def contains(self, key: str) -> bool:
        """Check if key exists in state."""
        with self._lock:
            return key in self._state
    
    def add_observer(self, observer: StateObserver) -> None:
        """Add state change observer."""
        with self._lock:
            if observer not in self._observers:
                self._observers.append(observer)
                logger.debug(f"Added observer to StateManager '{self.name}'")
    
    def remove_observer(self, observer: StateObserver) -> None:
        """Remove state change observer."""
        with self._lock:
            if observer in self._observers:
                self._observers.remove(observer)
                logger.debug(f"Removed observer from StateManager '{self.name}'")
    
    def get_change_history(self, limit: Optional[int] = None) -> List[StateChange]:
        """Get state change history."""
        with self._lock:
            history = self._change_history.copy()
            if limit:
                return history[-limit:]
            return history
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get state manager summary."""
        with self._lock:
            return {
                "name": self.name,
                "size": len(self._state),
                "observer_count": len(self._observers),
                "history_count": len(self._change_history),
                "last_change": self._change_history[-1].timestamp if self._change_history else None,
                "persistence_enabled": self.enable_persistence,
                "last_persistence": self._last_persistence
            }
    
    def persist_state(self, filepath: Optional[str] = None) -> bool:
        """Persist current state to file."""
        if not self.enable_persistence:
            return False
        
        filepath = filepath or f"/tmp/state_{self.name}_{int(time.time())}.json"
        
        try:
            with self._lock:
                state_data = {
                    "name": self.name,
                    "timestamp": time.time(),
                    "state": self._state,
                    "metadata": {
                        "size": len(self._state),
                        "last_change": self._change_history[-1].timestamp if self._change_history else None
                    }
                }
                
                with open(filepath, 'w') as f:
                    json.dump(state_data, f, indent=2, default=str)
                
                self._last_persistence = time.time()
                logger.info(f"State persisted to {filepath}")
                return True
                
        except Exception as exc:
            logger.error(f"Failed to persist state: {exc}")
            return False
    
    def load_state(self, filepath: str) -> bool:
        """Load state from file."""
        try:
            with open(filepath, 'r') as f:
                state_data = json.load(f)
            
            with self._lock:
                # Validate data
                if state_data.get("name") != self.name:
                    logger.warning(f"State name mismatch: expected {self.name}, got {state_data.get('name')}")
                
                # Load state
                loaded_state = state_data.get("state", {})
                self._state.update(loaded_state)
                
                # Create load event
                change = StateChange(
                    change_type=StateChangeType.UPDATE,
                    key="*",
                    old_value=None,
                    new_value=loaded_state,
                    timestamp=time.time(),
                    metadata={"action": "load_state", "filepath": filepath}
                )
                
                self._add_to_history(change)
                self._notify_observers(change)
                
                logger.info(f"State loaded from {filepath}: {len(loaded_state)} entries")
                return True
                
        except Exception as exc:
            logger.error(f"Failed to load state: {exc}")
            return False
    
    def _add_to_history(self, change: StateChange) -> None:
        """Add change to history with size management."""
        self._change_history.append(change)
        
        # Trim history if needed
        if len(self._change_history) > self.max_history:
            excess = len(self._change_history) - self.max_history
            self._change_history = self._change_history[excess:]
    
    def _notify_observers(self, change: StateChange) -> None:
        """Notify all observers of state change."""
        for observer in self._observers.copy():  # Copy to avoid modification during iteration
            try:
                observer.on_state_changed(change)
            except Exception as exc:
                logger.error(f"Observer notification failed: {exc}")
    
    def _check_auto_persistence(self) -> None:
        """Check if auto-persistence should be triggered."""
        if (self.enable_persistence and 
            time.time() - self._last_persistence >= self.persistence_interval):
            safe_execute(
                self.persist_state,
                context=f"Auto-persistence for StateManager '{self.name}'",
                exceptions=Exception,
                logger_name="StateManager"
            )
    
    def _cleanup_resources(self) -> None:
        """Clean up state manager resources."""
        try:
            with self._lock:
                # Final persistence if enabled
                if self.enable_persistence:
                    self.persist_state()
                
                # Clear observers
                self._observers.clear()
                
                # Clear state and history
                self._state.clear()
                self._change_history.clear()
                
                # Unregister from resource manager
                if hasattr(self, '_resource_id') and self._resource_id:
                    global_resource_manager.unregister_resource(self._resource_id, force_cleanup=False)
                
                logger.debug(f"StateManager '{self.name}' resources cleaned up")
                
        except Exception as exc:
            logger.error(f"Error cleaning up StateManager '{self.name}': {exc}")


class UEStateManager(StateManager[Dict[str, Any]]):
    """Specialized state manager for UE (User Equipment) data."""
    
    def __init__(self, max_ues: int = 10000, ue_ttl_hours: float = 24.0):
        """Initialize UE state manager."""
        super().__init__(
            name="UEState",
            max_history=5000,
            enable_persistence=True,
            persistence_interval=300.0  # 5 minutes
        )
        
        self.max_ues = max_ues
        self.ue_ttl_seconds = ue_ttl_hours * 3600
        self._ue_timestamps: Dict[str, float] = {}
        
        # Start cleanup thread
        self._cleanup_thread = threading.Thread(target=self._cleanup_expired_ues, daemon=True)
        self._cleanup_running = True
        self._cleanup_thread.start()
    
    def update_ue(self, ue_id: str, ue_data: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> None:
        """Update UE state with timestamp tracking."""
        current_time = time.time()
        
        with self._lock:
            # Update timestamp
            self._ue_timestamps[ue_id] = current_time
            
            # Update state
            enhanced_metadata = (metadata or {}).copy()
            enhanced_metadata.update({
                "ue_id": ue_id,
                "last_seen": current_time,
                "action": "ue_update"
            })
            
            self.set(ue_id, ue_data, enhanced_metadata)
            
            # Check for capacity management
            self._manage_capacity()
    
    def get_ue(self, ue_id: str) -> Optional[Dict[str, Any]]:
        """Get UE data if not expired."""
        with self._lock:
            if ue_id not in self._state:
                return None
            
            # Check expiry
            last_seen = self._ue_timestamps.get(ue_id, 0)
            if time.time() - last_seen > self.ue_ttl_seconds:
                self._remove_expired_ue(ue_id)
                return None
            
            return self.get(ue_id)
    
    def get_active_ues(self) -> List[str]:
        """Get list of active (non-expired) UE IDs."""
        current_time = time.time()
        active_ues = []
        
        with self._lock:
            for ue_id, last_seen in self._ue_timestamps.items():
                if current_time - last_seen <= self.ue_ttl_seconds:
                    active_ues.append(ue_id)
        
        return active_ues
    
    def get_ue_stats(self) -> Dict[str, Any]:
        """Get UE state statistics."""
        current_time = time.time()
        
        with self._lock:
            total_ues = len(self._state)
            active_ues = sum(1 for ts in self._ue_timestamps.values() 
                           if current_time - ts <= self.ue_ttl_seconds)
            
            return {
                "total_ues": total_ues,
                "active_ues": active_ues,
                "expired_ues": total_ues - active_ues,
                "max_ues": self.max_ues,
                "utilization": total_ues / self.max_ues if self.max_ues > 0 else 0,
                "ttl_seconds": self.ue_ttl_seconds
            }
    
    def _manage_capacity(self) -> None:
        """Manage UE capacity by removing oldest entries."""
        if len(self._state) <= self.max_ues:
            return
        
        # Remove oldest UEs
        with self._lock:
            sorted_ues = sorted(self._ue_timestamps.items(), key=lambda x: x[1])
            to_remove = len(self._state) - self.max_ues
            
            for ue_id, _ in sorted_ues[:to_remove]:
                self._remove_ue(ue_id, reason="capacity_management")
    
    def _cleanup_expired_ues(self) -> None:
        """Background thread to clean up expired UEs."""
        while self._cleanup_running:
            try:
                current_time = time.time()
                expired_ues = []
                
                with self._lock:
                    for ue_id, last_seen in self._ue_timestamps.items():
                        if current_time - last_seen > self.ue_ttl_seconds:
                            expired_ues.append(ue_id)
                
                # Remove expired UEs
                for ue_id in expired_ues:
                    self._remove_expired_ue(ue_id)
                
                if expired_ues:
                    logger.debug(f"Cleaned up {len(expired_ues)} expired UEs")
                
                # Sleep for cleanup interval
                time.sleep(60)  # Check every minute
                
            except Exception as exc:
                logger.error(f"Error in UE cleanup thread: {exc}")
                time.sleep(60)
    
    def _remove_expired_ue(self, ue_id: str) -> None:
        """Remove expired UE."""
        self._remove_ue(ue_id, reason="ttl_expired")
    
    def _remove_ue(self, ue_id: str, reason: str) -> None:
        """Remove UE with reason."""
        with self._lock:
            if ue_id in self._state:
                self.delete(ue_id, metadata={"reason": reason})
            
            if ue_id in self._ue_timestamps:
                del self._ue_timestamps[ue_id]
    
    def _cleanup_resources(self) -> None:
        """Clean up UE state manager resources."""
        self._cleanup_running = False
        if hasattr(self, '_cleanup_thread') and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5.0)
        
        super()._cleanup_resources()


class ModelStateManager(StateManager[Any]):
    """Specialized state manager for ML model state."""
    
    def __init__(self):
        """Initialize model state manager."""
        super().__init__(
            name="ModelState",
            max_history=1000,
            enable_persistence=True,
            persistence_interval=60.0  # 1 minute
        )
        
        # Initialize default model state
        self._initialize_model_state()
    
    def _initialize_model_state(self) -> None:
        """Initialize default model state."""
        default_state = {
            "model_loaded": False,
            "model_path": None,
            "model_version": "unknown",
            "last_training": None,
            "training_samples": 0,
            "prediction_count": 0,
            "last_prediction": None,
            "model_accuracy": None,
            "feature_count": 0,
            "model_size": 0
        }
        
        for key, value in default_state.items():
            self.set(key, value, metadata={"action": "initialize"})
    
    def update_model_loaded(self, model_path: str, version: str = "unknown", metadata: Optional[Dict[str, Any]] = None) -> None:
        """Update model loaded state."""
        self.update({
            "model_loaded": True,
            "model_path": model_path,
            "model_version": version,
            "last_loaded": time.time()
        }, metadata)
    
    def update_training_completed(self, samples: int, accuracy: Optional[float] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Update training completed state."""
        self.update({
            "last_training": time.time(),
            "training_samples": samples,
            "model_accuracy": accuracy
        }, metadata)
    
    def increment_prediction_count(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Increment prediction count."""
        current_count = self.get("prediction_count", 0)
        self.update({
            "prediction_count": current_count + 1,
            "last_prediction": time.time()
        }, metadata)
    
    def get_model_summary(self) -> Dict[str, Any]:
        """Get model state summary."""
        state = self.get_all()
        
        return {
            "model_loaded": state.get("model_loaded", False),
            "model_version": state.get("model_version", "unknown"),
            "prediction_count": state.get("prediction_count", 0),
            "training_samples": state.get("training_samples", 0),
            "model_accuracy": state.get("model_accuracy"),
            "uptime_seconds": time.time() - (state.get("last_loaded", time.time())),
            "last_activity": max(
                state.get("last_prediction", 0),
                state.get("last_training", 0),
                state.get("last_loaded", 0)
            )
        }


class GlobalStateRegistry:
    """Global registry for managing multiple state managers."""
    
    def __init__(self):
        """Initialize global state registry."""
        self._state_managers: Dict[str, StateManager] = {}
        self._lock = threading.RLock()
        
        # Create default state managers
        self._create_default_managers()
        
        logger.info("GlobalStateRegistry initialized")
    
    def _create_default_managers(self) -> None:
        """Create default state managers."""
        with self._lock:
            # UE state manager
            self._state_managers["ue_state"] = UEStateManager(
                max_ues=env_constants.UE_TRACKING_MAX_UES,
                ue_ttl_hours=env_constants.UE_TRACKING_TTL_HOURS
            )
            
            # Model state manager
            self._state_managers["model_state"] = ModelStateManager()
            
            # Application state manager
            self._state_managers["app_state"] = StateManager(
                name="ApplicationState",
                max_history=500,
                enable_persistence=True,
                persistence_interval=120.0
            )
    
    def get_manager(self, name: str) -> Optional[StateManager]:
        """Get state manager by name."""
        with self._lock:
            return self._state_managers.get(name)
    
    def register_manager(self, name: str, manager: StateManager) -> None:
        """Register a state manager."""
        with self._lock:
            if name in self._state_managers:
                logger.warning(f"State manager '{name}' already exists, replacing")
            
            self._state_managers[name] = manager
            logger.info(f"Registered state manager: {name}")
    
    def unregister_manager(self, name: str) -> bool:
        """Unregister a state manager."""
        with self._lock:
            if name in self._state_managers:
                manager = self._state_managers.pop(name)
                manager._cleanup_resources()
                logger.info(f"Unregistered state manager: {name}")
                return True
            return False
    
    def get_all_managers(self) -> Dict[str, StateManager]:
        """Get all registered state managers."""
        with self._lock:
            return self._state_managers.copy()
    
    def get_registry_summary(self) -> Dict[str, Any]:
        """Get summary of all state managers."""
        with self._lock:
            summary = {}
            for name, manager in self._state_managers.items():
                summary[name] = manager.get_state_summary()
            
            return {
                "manager_count": len(self._state_managers),
                "managers": summary
            }
    
    def persist_all_state(self) -> Dict[str, bool]:
        """Persist state for all managers."""
        results = {}
        
        with self._lock:
            for name, manager in self._state_managers.items():
                if manager.enable_persistence:
                    results[name] = manager.persist_state()
                else:
                    results[name] = False
        
        return results
    
    def cleanup_all_managers(self) -> None:
        """Clean up all state managers."""
        with self._lock:
            for manager in self._state_managers.values():
                manager._cleanup_resources()
            
            self._state_managers.clear()
            logger.info("All state managers cleaned up")


# Global state registry instance
_global_state_registry: Optional[GlobalStateRegistry] = None
_registry_lock = threading.Lock()


def get_global_state_registry() -> GlobalStateRegistry:
    """Get the global state registry."""
    global _global_state_registry
    
    if _global_state_registry is None:
        with _registry_lock:
            if _global_state_registry is None:
                _global_state_registry = GlobalStateRegistry()
    
    return _global_state_registry


# Convenience functions for common state operations
def get_ue_state_manager() -> UEStateManager:
    """Get the UE state manager."""
    registry = get_global_state_registry()
    return registry.get_manager("ue_state")


def get_model_state_manager() -> ModelStateManager:
    """Get the model state manager."""
    registry = get_global_state_registry()
    return registry.get_manager("model_state")


def get_app_state_manager() -> StateManager:
    """Get the application state manager."""
    registry = get_global_state_registry()
    return registry.get_manager("app_state")