import threading
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


# Global shared instance
state_manager = StateManager()
