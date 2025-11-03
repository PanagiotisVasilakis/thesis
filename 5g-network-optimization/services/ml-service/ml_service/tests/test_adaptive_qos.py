from ml_service.app.core.adaptive_qos import adaptive_qos_manager


def test_adaptive_threshold_increases_after_failures():
    adaptive_qos_manager.reset()
    base = adaptive_qos_manager.get_required_confidence("embb", 5)
    for _ in range(10):
        adaptive_qos_manager.observe_feedback("embb", passed=False)
    updated = adaptive_qos_manager.get_required_confidence("embb", 5)
    assert updated > base


def test_adaptive_threshold_relaxes_after_success():
    adaptive_qos_manager.reset()
    # Seed with failures to raise threshold first
    for _ in range(5):
        adaptive_qos_manager.observe_feedback("embb", passed=False)
    raised = adaptive_qos_manager.get_required_confidence("embb", 5)
    for _ in range(20):
        adaptive_qos_manager.observe_feedback("embb", passed=True)
    relaxed = adaptive_qos_manager.get_required_confidence("embb", 5)
    assert relaxed <= raised
    adaptive_qos_manager.reset()
