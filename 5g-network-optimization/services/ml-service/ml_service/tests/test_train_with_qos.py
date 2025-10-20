import tempfile
import random

from ml_service.app.models.lightgbm_selector import LightGBMSelector


def make_sample(i):
    # Create a synthetic sample with base features and QoS fields
    return {
        "ue_id": f"ue{i}",
        "latitude": random.uniform(0, 1000),
        "longitude": random.uniform(0, 866),
        "speed": random.uniform(0, 30),
        "direction_x": random.uniform(-1, 1),
        "direction_y": random.uniform(-1, 1),
        "heading_change_rate": random.uniform(0, 1),
        "path_curvature": random.uniform(0, 1),
        "velocity": random.uniform(0, 30),
        "acceleration": random.uniform(-1, 1),
        "cell_load": random.random(),
        "handover_count": random.randint(0, 5),
        "time_since_handover": random.uniform(0, 1000),
        "signal_trend": random.uniform(-1, 1),
        "environment": random.choice([0.0, 1.0]),
        "rsrp_stddev": random.uniform(0, 10),
        "sinr_stddev": random.uniform(0, 5),
        "rsrp_current": random.uniform(-120, -50),
        "sinr_current": random.uniform(-10, 30),
        "rsrq_current": random.uniform(-20, -5),
        "best_rsrp_diff": random.uniform(-10, 10),
        "best_sinr_diff": random.uniform(-10, 10),
        "best_rsrq_diff": random.uniform(-5, 5),
        "altitude": random.uniform(0, 100),
        # QoS fields
        "service_type": random.choice(["urllc", "embb", "mmtc", "default"]),
        "service_priority": random.randint(1, 10),
        "latency_requirement_ms": random.uniform(1, 100),
        "throughput_requirement_mbps": random.uniform(0.1, 1000),
        "reliability_pct": random.uniform(50, 99.9),
        # Label
        "optimal_antenna": random.choice(["a1", "a2", "a3"]),
    }


def test_lightgbm_train_with_qos():
    samples = [make_sample(i) for i in range(30)]

    # Use small model to keep test fast
    model = LightGBMSelector(model_path=None, n_estimators=5)

    metrics = model.train(samples)

    assert "samples" in metrics and metrics["samples"] == 30
    assert "feature_importance" in metrics
    # Ensure QoS features are present in the trained feature importance
    fi_keys = set(metrics["feature_importance"].keys())
    assert "service_type" in fi_keys
    assert "service_priority" in fi_keys
    assert "latency_requirement_ms" in fi_keys

