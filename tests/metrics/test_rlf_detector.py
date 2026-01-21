"""Unit tests for RLF detector module.

Tests RLF detection, throughput calculation, and handover interruption tracking.
"""
import unittest
from collections import deque

# Import paths are configured by conftest.py


class TestRLFDetector(unittest.TestCase):
    """Tests for RLFDetector class."""
    
    def setUp(self):
        """Create fresh detector for each test."""
        from app.app.metrics.rlf_detector import RLFDetector
        self.detector = RLFDetector()
    
    def test_rlf_not_triggered_above_threshold(self):
        """RLF should not trigger when SINR is above threshold."""
        # SINR at -5 dB, above default threshold of -6 dB
        result = self.detector.check_rlf("ue001", sinr_db=-5.0, timestamp=0.0)
        self.assertFalse(result)
    
    def test_rlf_timer_starts_below_threshold(self):
        """RLF timer should start when SINR drops below threshold."""
        # SINR at -8 dB, below threshold
        result = self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=0.0)
        self.assertFalse(result)  # Not yet RLF, just timer started
        
        state = self.detector._get_state("ue001")
        self.assertIsNotNone(state.rlf_timer_start)
    
    def test_rlf_triggered_after_duration(self):
        """RLF should trigger after being below threshold for 1 second."""
        # Start timer
        self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=0.0)
        
        # Check at exactly 1 second (should trigger with >= comparison)
        result = self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=1.0)
        self.assertTrue(result)
    
    def test_rlf_timer_resets_on_recovery(self):
        """RLF timer should reset when SINR recovers."""
        # Start timer
        self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=0.0)
        
        # SINR recovers
        self.detector.check_rlf("ue001", sinr_db=-3.0, timestamp=0.5)
        
        state = self.detector._get_state("ue001")
        self.assertIsNone(state.rlf_timer_start)
    
    def test_rlf_skipped_during_handover(self):
        """RLF detection should be skipped during handover interruption."""
        # Notify handover start
        self.detector.notify_handover_start("ue001", timestamp=0.0)
        
        # Check RLF during handover (should be skipped)
        result = self.detector.check_rlf("ue001", sinr_db=-15.0, timestamp=0.5)
        self.assertFalse(result)
        
        # Timer should not have started
        state = self.detector._get_state("ue001")
        self.assertIsNone(state.rlf_timer_start)
    
    def test_rlf_count_increments(self):
        """RLF count should increment for each RLF event."""
        # First RLF
        self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=0.0)
        self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=1.0)
        
        # Recovery
        self.detector.check_rlf("ue001", sinr_db=-3.0, timestamp=1.5)
        
        # Second RLF
        self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=2.0)
        self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=3.0)
        
        self.assertEqual(self.detector.get_ue_rlf_count("ue001"), 2)
    
    def test_total_rlf_count_across_ues(self):
        """Total RLF count should sum across all UEs."""
        # RLF for UE1
        self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=0.0)
        self.detector.check_rlf("ue001", sinr_db=-8.0, timestamp=1.0)
        
        # RLF for UE2
        self.detector.check_rlf("ue002", sinr_db=-8.0, timestamp=0.0)
        self.detector.check_rlf("ue002", sinr_db=-8.0, timestamp=1.0)
        
        self.assertEqual(self.detector.get_total_rlf_count(), 2)


class TestThroughputCalculator(unittest.TestCase):
    """Tests for ThroughputCalculator class."""
    
    def setUp(self):
        """Create fresh calculator for each test."""
        from app.app.metrics.rlf_detector import ThroughputCalculator
        self.calc = ThroughputCalculator(bandwidth_hz=20e6)
    
    def test_zero_throughput_below_min_sinr(self):
        """Throughput should be 0 below minimum SINR (-10 dB)."""
        result = self.calc.calculate_throughput(sinr_db=-15.0)
        self.assertEqual(result, 0.0)
    
    def test_zero_throughput_during_interruption(self):
        """Throughput should be 0 during handover interruption."""
        result = self.calc.calculate_throughput(
            sinr_db=20.0, is_handover_interruption=True
        )
        self.assertEqual(result, 0.0)
    
    def test_degraded_throughput_in_rlf_zone(self):
        """Throughput should be degraded in RLF zone (-10 to -6 dB)."""
        # In RLF zone
        result_rlf = self.calc.calculate_throughput(sinr_db=-8.0)
        # Above RLF zone
        result_normal = self.calc.calculate_throughput(sinr_db=0.0)
        
        self.assertGreater(result_normal, result_rlf)
        self.assertGreater(result_rlf, 0.0)  # Still some throughput
    
    def test_throughput_increases_with_sinr(self):
        """Throughput should increase with SINR in normal zone."""
        result_low = self.calc.calculate_throughput(sinr_db=0.0)
        result_high = self.calc.calculate_throughput(sinr_db=20.0)
        
        self.assertGreater(result_high, result_low)
    
    def test_throughput_capped_at_max_efficiency(self):
        """Throughput should not exceed max spectral efficiency × bandwidth."""
        # Very high SINR
        result = self.calc.calculate_throughput(sinr_db=50.0)
        max_throughput = self.calc.max_efficiency * 20e6 / 1e6  # in Mbps
        
        self.assertLessEqual(result, max_throughput)


class TestHandoverInterruptionTracker(unittest.TestCase):
    """Tests for HandoverInterruptionTracker class."""
    
    def setUp(self):
        """Create fresh tracker for each test."""
        from app.app.metrics.rlf_detector import HandoverInterruptionTracker
        self.tracker = HandoverInterruptionTracker(interruption_duration_s=0.050)
    
    def test_record_handover_creates_interruption(self):
        """Recording a handover should create an interruption period."""
        self.tracker.record_handover("ue001", timestamp=1.0)
        
        # Should be in interruption immediately after handover
        self.assertTrue(
            self.tracker.is_in_interruption("ue001", timestamp=1.025)
        )
    
    def test_interruption_ends_after_duration(self):
        """Interruption should end after the configured duration."""
        self.tracker.record_handover("ue001", timestamp=1.0)
        
        # 50ms later, should not be in interruption
        self.assertFalse(
            self.tracker.is_in_interruption("ue001", timestamp=1.1)
        )
    
    def test_handover_count_increments(self):
        """Handover count should increment for each recorded handover."""
        self.tracker.record_handover("ue001", timestamp=1.0)
        self.tracker.record_handover("ue001", timestamp=2.0)
        self.tracker.record_handover("ue001", timestamp=3.0)
        
        self.assertEqual(self.tracker.get_handover_count("ue001"), 3)
    
    def test_total_interruption_time_accumulates(self):
        """Total interruption time should accumulate correctly."""
        self.tracker.record_handover("ue001", timestamp=1.0)
        self.tracker.record_handover("ue001", timestamp=2.0)
        
        # After both complete (at timestamp 3.0)
        total = self.tracker.get_total_interruption_time("ue001", current_time=3.0)
        
        # Should be approximately 100ms (2 × 50ms)
        self.assertAlmostEqual(total, 0.1, places=3)
    
    def test_multiple_ues_tracked_separately(self):
        """Each UE should have separate interruption tracking."""
        self.tracker.record_handover("ue001", timestamp=1.0)
        self.tracker.record_handover("ue002", timestamp=1.0)
        self.tracker.record_handover("ue002", timestamp=2.0)
        
        self.assertEqual(self.tracker.get_handover_count("ue001"), 1)
        self.assertEqual(self.tracker.get_handover_count("ue002"), 2)


class TestMaxInterruptionQueueSize(unittest.TestCase):
    """Test configurable MAX_INTERRUPTION_QUEUE_SIZE."""
    
    def test_queue_size_constant_exists(self):
        """MAX_INTERRUPTION_QUEUE_SIZE constant should be defined."""
        from app.app.metrics.rlf_detector import MAX_INTERRUPTION_QUEUE_SIZE
        
        self.assertIsInstance(MAX_INTERRUPTION_QUEUE_SIZE, int)
        self.assertGreater(MAX_INTERRUPTION_QUEUE_SIZE, 0)


class TestMetricsCollector(unittest.TestCase):
    """Tests for MetricsCollector unified interface."""
    
    def setUp(self):
        """Create fresh collector for each test."""
        from app.app.metrics.rlf_detector import MetricsCollector
        self.collector = MetricsCollector()
    
    def test_update_returns_metrics_dict(self):
        """update() should return a dictionary with expected keys."""
        result = self.collector.update(
            ue_id="ue001",
            sinr_db=10.0,
            timestamp=1.0
        )
        
        self.assertIn("ue_id", result)
        self.assertIn("sinr_db", result)
        self.assertIn("throughput_mbps", result)
        self.assertIn("is_rlf", result)
        self.assertIn("is_interruption", result)
    
    def test_record_handover_syncs_rlf_detector(self):
        """record_handover should sync state with RLF detector."""
        self.collector.record_handover("ue001", timestamp=1.0)
        
        # Update during interruption should have is_interruption=True
        result = self.collector.update(
            ue_id="ue001",
            sinr_db=-8.0,
            timestamp=1.025  # Within 50ms interruption
        )
        
        self.assertTrue(result["is_interruption"])
    
    def test_average_throughput_calculation(self):
        """get_average_throughput should calculate correctly."""
        # Multiple updates at good SINR
        for t in range(10):
            self.collector.update(
                ue_id="ue001",
                sinr_db=10.0,
                timestamp=float(t) * 0.1,
                timestep_s=0.1
            )
        
        avg = self.collector.get_average_throughput("ue001")
        self.assertGreater(avg, 0.0)
    
    def test_summary_contains_all_metrics(self):
        """get_summary should return comprehensive metrics."""
        self.collector.update("ue001", sinr_db=10.0, timestamp=1.0)
        
        summary = self.collector.get_summary()
        
        self.assertIn("total_rlfs", summary)
        self.assertIn("total_handovers", summary)
        self.assertIn("average_throughput_mbps", summary)
        self.assertIn("ue_count", summary)


class TestRLFDetectorThreadSafety(unittest.TestCase):
    """Thread safety tests for RLF detector components.
    
    These tests verify that concurrent access to RLF detector classes
    doesn't cause data corruption or race conditions.
    """
    
    def setUp(self):
        """Create fresh instances for each test."""
        from app.app.metrics.rlf_detector import (
            RLFDetector,
            HandoverInterruptionTracker,
            MetricsCollector,
        )
        self.detector = RLFDetector()
        self.tracker = HandoverInterruptionTracker()
        self.collector = MetricsCollector()
    
    def test_concurrent_rlf_checks_no_crash(self):
        """Concurrent RLF checks should not crash or corrupt state."""
        import threading
        
        errors = []
        n_threads = 10
        n_iterations = 100
        
        def check_rlf_worker(thread_id):
            try:
                for i in range(n_iterations):
                    ue_id = f"ue_{thread_id}"
                    sinr = -10.0 + (i % 20)  # Vary SINR
                    timestamp = float(i) * 0.01
                    self.detector.check_rlf(ue_id, sinr, timestamp)
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=check_rlf_worker, args=(i,))
            for i in range(n_threads)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
    
    def test_concurrent_handover_recording_no_crash(self):
        """Concurrent handover recording should not crash."""
        import threading
        
        errors = []
        n_threads = 10
        n_iterations = 50
        
        def record_handover_worker(thread_id):
            try:
                for i in range(n_iterations):
                    ue_id = f"ue_{thread_id}"
                    timestamp = float(i) * 0.1
                    self.tracker.record_handover(ue_id, timestamp)
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=record_handover_worker, args=(i,))
            for i in range(n_threads)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
    
    def test_concurrent_collector_updates_no_crash(self):
        """Concurrent MetricsCollector updates should not crash."""
        import threading
        
        errors = []
        n_threads = 10
        n_iterations = 100
        
        def collector_worker(thread_id):
            try:
                for i in range(n_iterations):
                    ue_id = f"ue_{thread_id}"
                    sinr = -5.0 + (i % 30)
                    timestamp = float(i) * 0.01
                    self.collector.update(
                        ue_id=ue_id,
                        sinr_db=sinr,
                        timestamp=timestamp,
                    )
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=collector_worker, args=(i,))
            for i in range(n_threads)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
    
    def test_mixed_operations_no_crash(self):
        """Mixed RLF checks and handover recordings should not crash."""
        import threading
        import random
        
        errors = []
        n_threads = 10
        n_iterations = 100
        
        def mixed_worker(thread_id):
            try:
                rng = random.Random(thread_id)
                for i in range(n_iterations):
                    ue_id = f"ue_{thread_id}"
                    timestamp = float(i) * 0.01
                    
                    # Randomly choose operation
                    op = rng.randint(0, 2)
                    if op == 0:
                        self.detector.check_rlf(ue_id, rng.uniform(-15, 20), timestamp)
                    elif op == 1:
                        self.tracker.record_handover(ue_id, timestamp)
                    else:
                        self.collector.update(ue_id, rng.uniform(-15, 20), timestamp)
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=mixed_worker, args=(i,))
            for i in range(n_threads)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")


if __name__ == "__main__":
    unittest.main()
