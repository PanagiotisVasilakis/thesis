"""State observers for monitoring and reacting to state changes."""

import logging
import time
from typing import Dict, Any, List, Optional, Callable
from collections import defaultdict
import threading

from .state_management import StateObserver, StateChange, StateChangeType
from ..utils.exception_handler import safe_execute
from ..monitoring.metrics import track_prediction, track_training

logger = logging.getLogger(__name__)


class LoggingStateObserver(StateObserver):
    """Observer that logs all state changes."""
    
    def __init__(self, log_level: int = logging.DEBUG, max_log_entries: int = 1000):
        """Initialize logging observer.
        
        Args:
            log_level: Logging level for state changes
            max_log_entries: Maximum log entries to keep in memory
        """
        self.log_level = log_level
        self.max_log_entries = max_log_entries
        self._log_entries: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        
        logger.info("LoggingStateObserver initialized")
    
    def on_state_changed(self, change: StateChange) -> None:
        """Log state change."""
        log_message = (
            f"State change [{change.change_type.value}] "
            f"key='{change.key}' "
            f"old='{self._format_value(change.old_value)}' "
            f"new='{self._format_value(change.new_value)}'"
        )
        
        # Log the change
        logger.log(self.log_level, log_message)
        
        # Store in memory for analysis
        with self._lock:
            self._log_entries.append({
                "timestamp": change.timestamp,
                "change_type": change.change_type.value,
                "key": change.key,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "metadata": change.metadata
            })
            
            # Trim log entries if needed
            if len(self._log_entries) > self.max_log_entries:
                self._log_entries = self._log_entries[-self.max_log_entries:]
    
    def get_log_entries(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get recent log entries."""
        with self._lock:
            entries = self._log_entries.copy()
            if limit:
                return entries[-limit:]
            return entries
    
    def get_log_stats(self) -> Dict[str, Any]:
        """Get logging statistics."""
        with self._lock:
            change_counts = defaultdict(int)
            for entry in self._log_entries:
                change_counts[entry["change_type"]] += 1
            
            return {
                "total_entries": len(self._log_entries),
                "change_type_counts": dict(change_counts),
                "first_entry": self._log_entries[0]["timestamp"] if self._log_entries else None,
                "last_entry": self._log_entries[-1]["timestamp"] if self._log_entries else None
            }
    
    def _format_value(self, value: Any) -> str:
        """Format value for logging."""
        if value is None:
            return "None"
        elif isinstance(value, (dict, list)) and len(str(value)) > 100:
            return f"{type(value).__name__}[{len(value)} items]"
        else:
            return str(value)[:100]


class MetricsStateObserver(StateObserver):
    """Observer that tracks metrics for state changes."""
    
    def __init__(self):
        """Initialize metrics observer."""
        self._change_counts = defaultdict(int)
        self._key_counts = defaultdict(int)
        self._last_change_time = 0
        self._lock = threading.Lock()
        
        logger.info("MetricsStateObserver initialized")
    
    def on_state_changed(self, change: StateChange) -> None:
        """Track metrics for state change."""
        with self._lock:
            # Count by change type
            self._change_counts[change.change_type.value] += 1
            
            # Count by key
            self._key_counts[change.key] += 1
            
            # Update last change time
            self._last_change_time = change.timestamp
            
            # Track specific metrics based on metadata
            metadata = change.metadata or {}
            
            # Track model-related metrics
            if "ue_id" in metadata:
                # This is a UE-related state change
                pass  # Could track UE-specific metrics here
            
            if metadata.get("action") == "ue_update":
                # Track UE update metrics
                pass
            
            if change.key == "prediction_count":
                # Track prediction metrics
                if isinstance(change.new_value, int) and isinstance(change.old_value, int):
                    predictions_made = change.new_value - change.old_value
                    if predictions_made > 0:
                        # Use default values for demonstration
                        track_prediction("antenna_1", 0.8)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get collected metrics."""
        with self._lock:
            total_changes = sum(self._change_counts.values())
            
            return {
                "total_changes": total_changes,
                "change_type_counts": dict(self._change_counts),
                "key_counts": dict(self._key_counts),
                "last_change_time": self._last_change_time,
                "most_changed_key": max(self._key_counts.items(), key=lambda x: x[1])[0] if self._key_counts else None
            }
    
    def reset_metrics(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._change_counts.clear()
            self._key_counts.clear()
            self._last_change_time = 0


class ThresholdStateObserver(StateObserver):
    """Observer that triggers actions when state values cross thresholds."""
    
    def __init__(self):
        """Initialize threshold observer."""
        self._thresholds: Dict[str, Dict[str, Any]] = {}
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()
        
        # Set up default thresholds
        self._setup_default_thresholds()
        
        logger.info("ThresholdStateObserver initialized")
    
    def _setup_default_thresholds(self) -> None:
        """Set up default thresholds for common state keys."""
        # UE count thresholds
        self.add_threshold(
            key="total_ues",
            threshold_type="max",
            value=8000,  # 80% of default max
            callback=self._handle_high_ue_count
        )
        
        # Memory usage thresholds
        self.add_threshold(
            key="memory_usage_mb",
            threshold_type="max",
            value=1024,  # 1GB
            callback=self._handle_high_memory_usage
        )
        
        # Prediction count thresholds
        self.add_threshold(
            key="prediction_count",
            threshold_type="rate",
            value=1000,  # 1000 predictions per hour
            callback=self._handle_high_prediction_rate
        )
    
    def add_threshold(self, key: str, threshold_type: str, value: Any, callback: Callable) -> None:
        """Add a threshold for a state key."""
        with self._lock:
            self._thresholds[key] = {
                "type": threshold_type,
                "value": value,
                "last_triggered": 0
            }
            self._callbacks[key].append(callback)
        
        logger.debug(f"Added threshold for key '{key}': {threshold_type} = {value}")
    
    def remove_threshold(self, key: str) -> None:
        """Remove threshold for a state key."""
        with self._lock:
            self._thresholds.pop(key, None)
            self._callbacks.pop(key, None)
        
        logger.debug(f"Removed threshold for key '{key}'")
    
    def on_state_changed(self, change: StateChange) -> None:
        """Check thresholds and trigger callbacks."""
        key = change.key
        new_value = change.new_value
        
        with self._lock:
            if key not in self._thresholds:
                return
            
            threshold_config = self._thresholds[key]
            threshold_type = threshold_config["type"]
            threshold_value = threshold_config["value"]
            last_triggered = threshold_config["last_triggered"]
            
            # Check if threshold is crossed
            triggered = False
            
            if threshold_type == "max" and isinstance(new_value, (int, float)):
                triggered = new_value > threshold_value
            elif threshold_type == "min" and isinstance(new_value, (int, float)):
                triggered = new_value < threshold_value
            elif threshold_type == "rate":
                # Simple rate check (could be enhanced)
                current_time = change.timestamp
                if current_time - last_triggered > 3600:  # 1 hour cooldown
                    triggered = True
            
            # Trigger callbacks if threshold crossed
            if triggered:
                self._thresholds[key]["last_triggered"] = change.timestamp
                
                for callback in self._callbacks[key]:
                    safe_execute(
                        lambda: callback(change, threshold_config),
                        context=f"Threshold callback for key '{key}'",
                        exceptions=Exception,
                        logger_name="ThresholdStateObserver"
                    )
    
    def _handle_high_ue_count(self, change: StateChange, threshold_config: Dict[str, Any]) -> None:
        """Handle high UE count threshold."""
        logger.warning(
            f"High UE count detected: {change.new_value} (threshold: {threshold_config['value']})"
        )
        
        # Could trigger cleanup or scaling actions here
        from .state_management import get_ue_state_manager
        ue_manager = get_ue_state_manager()
        if ue_manager:
            stats = ue_manager.get_ue_stats()
            logger.info(f"UE stats: {stats}")
    
    def _handle_high_memory_usage(self, change: StateChange, threshold_config: Dict[str, Any]) -> None:
        """Handle high memory usage threshold."""
        logger.warning(
            f"High memory usage detected: {change.new_value}MB (threshold: {threshold_config['value']}MB)"
        )
        
        # Could trigger memory cleanup actions here
    
    def _handle_high_prediction_rate(self, change: StateChange, threshold_config: Dict[str, Any]) -> None:
        """Handle high prediction rate threshold."""
        logger.info(
            f"High prediction rate detected: {change.new_value} predictions"
        )
        
        # Could trigger scaling or load balancing actions here
    
    def get_threshold_summary(self) -> Dict[str, Any]:
        """Get summary of all thresholds."""
        with self._lock:
            return {
                "threshold_count": len(self._thresholds),
                "thresholds": self._thresholds.copy(),
                "callback_count": {key: len(callbacks) for key, callbacks in self._callbacks.items()}
            }


class StateHistoryObserver(StateObserver):
    """Observer that maintains detailed state history and analytics."""
    
    def __init__(self, max_history: int = 10000):
        """Initialize history observer."""
        self.max_history = max_history
        self._history: List[StateChange] = []
        self._key_timelines: Dict[str, List[StateChange]] = defaultdict(list)
        self._lock = threading.Lock()
        
        logger.info("StateHistoryObserver initialized")
    
    def on_state_changed(self, change: StateChange) -> None:
        """Store state change in history."""
        with self._lock:
            # Add to global history
            self._history.append(change)
            
            # Add to key-specific timeline
            self._key_timelines[change.key].append(change)
            
            # Trim history if needed
            if len(self._history) > self.max_history:
                excess = len(self._history) - self.max_history
                
                # Remove from global history
                removed_changes = self._history[:excess]
                self._history = self._history[excess:]
                
                # Remove from key timelines
                for removed_change in removed_changes:
                    key_timeline = self._key_timelines[removed_change.key]
                    if key_timeline and key_timeline[0] == removed_change:
                        key_timeline.pop(0)
    
    def get_key_timeline(self, key: str, limit: Optional[int] = None) -> List[StateChange]:
        """Get timeline for a specific key."""
        with self._lock:
            timeline = self._key_timelines[key].copy()
            if limit:
                return timeline[-limit:]
            return timeline
    
    def get_changes_in_timeframe(self, start_time: float, end_time: float) -> List[StateChange]:
        """Get changes within a time frame."""
        with self._lock:
            return [
                change for change in self._history
                if start_time <= change.timestamp <= end_time
            ]
    
    def get_key_statistics(self, key: str) -> Dict[str, Any]:
        """Get statistics for a specific key."""
        with self._lock:
            timeline = self._key_timelines[key]
            
            if not timeline:
                return {"key": key, "change_count": 0}
            
            change_types = defaultdict(int)
            for change in timeline:
                change_types[change.change_type.value] += 1
            
            return {
                "key": key,
                "change_count": len(timeline),
                "change_types": dict(change_types),
                "first_change": timeline[0].timestamp,
                "last_change": timeline[-1].timestamp,
                "current_value": timeline[-1].new_value
            }
    
    def get_global_statistics(self) -> Dict[str, Any]:
        """Get global history statistics."""
        with self._lock:
            if not self._history:
                return {"total_changes": 0}
            
            # Count changes by type
            change_type_counts = defaultdict(int)
            for change in self._history:
                change_type_counts[change.change_type.value] += 1
            
            # Get most active keys
            key_counts = defaultdict(int)
            for change in self._history:
                key_counts[change.key] += 1
            
            most_active_keys = sorted(key_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            
            return {
                "total_changes": len(self._history),
                "unique_keys": len(self._key_timelines),
                "change_type_counts": dict(change_type_counts),
                "most_active_keys": most_active_keys,
                "time_range": {
                    "start": self._history[0].timestamp,
                    "end": self._history[-1].timestamp,
                    "duration": self._history[-1].timestamp - self._history[0].timestamp
                }
            }


class CompositeStateObserver(StateObserver):
    """Composite observer that delegates to multiple child observers."""
    
    def __init__(self, observers: Optional[List[StateObserver]] = None):
        """Initialize composite observer."""
        self._observers: List[StateObserver] = observers or []
        self._lock = threading.Lock()
        
        logger.info(f"CompositeStateObserver initialized with {len(self._observers)} observers")
    
    def add_observer(self, observer: StateObserver) -> None:
        """Add child observer."""
        with self._lock:
            if observer not in self._observers:
                self._observers.append(observer)
                logger.debug(f"Added observer: {type(observer).__name__}")
    
    def remove_observer(self, observer: StateObserver) -> None:
        """Remove child observer."""
        with self._lock:
            if observer in self._observers:
                self._observers.remove(observer)
                logger.debug(f"Removed observer: {type(observer).__name__}")
    
    def on_state_changed(self, change: StateChange) -> None:
        """Notify all child observers."""
        # Make a copy to avoid modification during iteration
        with self._lock:
            observers = self._observers.copy()
        
        for observer in observers:
            try:
                observer.on_state_changed(change)
            except Exception as exc:
                logger.error(f"Observer {type(observer).__name__} failed: {exc}")
    
    def get_observer_count(self) -> int:
        """Get number of child observers."""
        with self._lock:
            return len(self._observers)
    
    def get_observer_types(self) -> List[str]:
        """Get types of child observers."""
        with self._lock:
            return [type(observer).__name__ for observer in self._observers]


# Factory function for creating default observer chain
def create_default_observer_chain() -> CompositeStateObserver:
    """Create default chain of state observers."""
    observers = [
        LoggingStateObserver(log_level=logging.INFO),
        MetricsStateObserver(),
        ThresholdStateObserver(),
        StateHistoryObserver(max_history=5000)
    ]
    
    composite = CompositeStateObserver(observers)
    logger.info("Created default state observer chain")
    
    return composite