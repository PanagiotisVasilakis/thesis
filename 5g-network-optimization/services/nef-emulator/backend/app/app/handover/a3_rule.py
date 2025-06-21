"""Event A3 handover rule with hysteresis and time-to-trigger."""
from datetime import datetime, timedelta

class A3EventRule:
    """Implements 3GPP Event A3 hysteresis/time-to-trigger logic."""
    def __init__(self, hysteresis_db: float = 2.0, ttt_seconds: float = 0.0):
        self.hysteresis_db = hysteresis_db
        self.ttt = timedelta(seconds=ttt_seconds)
        self._start: datetime | None = None

    def check(self, rsrp_serving: float, rsrp_target: float, now: datetime) -> bool:
        """Return True if the A3 condition has been met for the duration."""
        diff = rsrp_target - rsrp_serving
        if diff > self.hysteresis_db:
            if self._start is None:
                self._start = now
            elif now - self._start >= self.ttt:
                self._start = None
                return True
        else:
            self._start = None
        return False
