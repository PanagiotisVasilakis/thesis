import random
import numpy as np

from ml_service.app.models.lightgbm_selector import LightGBMSelector


def synthetic_sample(label_index: int, num_ants: int = 3):
    # Create deterministic-ish sample based on label_index
    random.seed(label_index)
    return {
        "ue_id": f"ue{label_index}",
        "latitude": float((label_index * 37) % 1000),
        "longitude": float((label_index * 91) % 866),
        "speed": float((label_index % 30)),
        "direction_x": float((label_index % 3) - 1),
        "direction_y": float((label_index % 5) - 2),
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": float((label_index % 30)),
        "acceleration": 0.0,
        "cell_load": float((label_index % 100) / 100.0),
        "handover_count": int(label_index % 5),
        "time_since_handover": float(label_index),
        "signal_trend": float((label_index % 7) - 3),
        "environment": float(label_index % 2),
        "rsrp_stddev": float((label_index % 10)),
        "sinr_stddev": float((label_index % 5)),
        "rsrp_current": float(-80 + (label_index % 10)),
        "sinr_current": float(-5 + (label_index % 20)),
        "rsrq_current": float(-10 + (label_index % 5)),
        "best_rsrp_diff": 0.0,
        "best_sinr_diff": 0.0,
        "best_rsrq_diff": 0.0,
        "altitude": 0.0,
        "service_type": random.choice(["urllc", "embb", "mmtc", "default"]),
        "service_priority": int((label_index % 10) + 1),
        "latency_requirement_ms": float((label_index % 100)),
        "throughput_requirement_mbps": float((label_index % 1000)),
        "reliability_pct": float(90 + (label_index % 10)),
        "optimal_antenna": f"a{(label_index % num_ants) + 1}",
    }


def test_training_ci_balanced():
    # Create a balanced dataset for 3 classes
    samples = []
    num_classes = 3
    per_class = 30
    for label in range(num_classes):
        for i in range(per_class):
            idx = label * per_class + i
            # Force optimal_antenna mapping to label
            s = synthetic_sample(idx, num_ants=num_classes)
            s["optimal_antenna"] = f"a{label+1}"
            samples.append(s)

    model = LightGBMSelector(model_path=None, n_estimators=10, random_state=42)

    metrics = model.train(samples)

    # Assert training ran and returned metrics; val_accuracy may be low but should be numeric
    assert "samples" in metrics and metrics["samples"] == len(samples)
    assert "feature_importance" in metrics
    if "val_accuracy" in metrics:
        assert 0.0 <= metrics["val_accuracy"] <= 1.0