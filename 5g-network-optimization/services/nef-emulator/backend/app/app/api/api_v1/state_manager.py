import threading
import time
from typing import Any, Dict, List, Optional


class StateManager:
    """Thread-safe container for runtime state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event_notifications: List[Dict[str, Any]] = []
        self._counter: int = 0
        self._threads: Dict[str, Dict[str, threading.Thread]] = {}
        self._ues: Dict[str, Dict[str, Any]] = {}
        self._timer_error_counter: int = 0
        # Handover tracking for thesis experiments
        self._handover_count: int = 0
        self._handovers_by_ue: Dict[str, List[Dict[str, Any]]] = {}
        self._session_start: float = time.time()

    # Notification handling
    def add_notification(self, notification: Dict[str, Any]) -> Dict[str, Any]:
        """Add a notification entry and assign an incremental id."""
        with self._lock:
            notification["id"] = self._counter
            self._counter += 1
            self._event_notifications.append(notification)
            if len(self._event_notifications) > 100:
                self._event_notifications.pop(0)
            return notification

    def get_notifications(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._event_notifications[skip:limit])

    def all_notifications(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._event_notifications)

    # Timer error counter
    def increment_timer_error(self) -> int:
        with self._lock:
            self._timer_error_counter += 1
            return self._timer_error_counter

    def get_timer_error_counter(self) -> int:
        with self._lock:
            return self._timer_error_counter

    # Thread management
    def get_thread(self, supi: str, user_id: str) -> Optional[threading.Thread]:
        with self._lock:
            return self._threads.get(supi, {}).get(user_id)

    def set_thread(self, supi: str, user_id: str, thread: threading.Thread) -> None:
        with self._lock:
            self._threads.setdefault(supi, {})[user_id] = thread

    def remove_thread(self, supi: str, user_id: Optional[str] = None) -> None:
        with self._lock:
            if user_id is None:
                self._threads.pop(supi, None)
            else:
                d = self._threads.get(supi)
                if d:
                    d.pop(user_id, None)
                    if not d:
                        self._threads.pop(supi, None)

    # UE state management
    def get_ue(self, supi: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._ues.get(supi)

    def set_ue(self, supi: str, ue_data: Dict[str, Any]) -> None:
        with self._lock:
            self._ues[supi] = ue_data

    def remove_ue(self, supi: str) -> None:
        with self._lock:
            self._ues.pop(supi, None)

    def all_ues(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._ues)

    # Handover tracking for thesis experiments
    def record_handover(
        self, 
        ue_id: str, 
        from_cell: str, 
        to_cell: str,
        method: str = "A3",
        confidence: Optional[float] = None,
        rsrp: Optional[float] = None,
        sinr: Optional[float] = None,
    ) -> None:
        """Record a handover event for statistical analysis."""
        with self._lock:
            self._handover_count += 1
            if ue_id not in self._handovers_by_ue:
                self._handovers_by_ue[ue_id] = []
            self._handovers_by_ue[ue_id].append({
                "time": time.time(),
                "from": from_cell,
                "to": to_cell,
                "method": method,
                "confidence": confidence,
                "rsrp": rsrp,
                "sinr": sinr,
            })

    def get_handover_stats(self) -> Dict[str, Any]:
        """Get handover statistics for the current session."""
        with self._lock:
            return {
                "total_handovers": self._handover_count,
                "handovers_by_ue": {
                    ue: len(events) for ue, events in self._handovers_by_ue.items()
                },
                "session_start": self._session_start,
                "session_duration": time.time() - self._session_start,
            }

    def get_recent_handovers(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent handover events with full details including ML confidence."""
        with self._lock:
            all_events = []
            for ue_id, events in self._handovers_by_ue.items():
                for event in events:
                    all_events.append({
                        "ue": ue_id,
                        **event
                    })
            # Sort by time descending, return most recent
            all_events.sort(key=lambda x: x["time"], reverse=True)
            return all_events[:limit]

    def reset_handover_stats(self) -> None:
        """Reset handover statistics for a new experiment session."""
        with self._lock:
            self._handover_count = 0
            self._handovers_by_ue.clear()
            self._session_start = time.time()

    def reset(self) -> None:
        """Stop all threads and clear runtime state."""
        with self._lock:
            # Signal all threads to stop
            for user_dict in self._threads.values():
                for thread in user_dict.values():
                    if hasattr(thread, 'do_run'):
                        thread.do_run = False
            
            # Clear state
            self._threads.clear()
            self._ues.clear()
            self._event_notifications.clear()
            self._counter = 0
            self._timer_error_counter = 0
            # Reset handover tracking
            self._handover_count = 0
            self._handovers_by_ue.clear()
            self._session_start = time.time()


# Global shared instance
state_manager = StateManager()

