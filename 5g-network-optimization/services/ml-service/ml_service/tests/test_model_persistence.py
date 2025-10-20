import tempfile
import os

from ml_service.app.models.lightgbm_selector import LightGBMSelector


def make_sample(i):
    return {
        "ue_id": f"ue{i}",
        "latitude": 1.0,
        "longitude": 2.0,
        "speed": 1.0,
        "direction_x": 0.0,
        "direction_y": 1.0,
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": 1.0,
        "acceleration": 0.0,
        "cell_load": 0.1,
        "handover_count": 0,
        "time_since_handover": 0.0,
        "signal_trend": 0.0,
        "environment": 0.0,
        "rsrp_stddev": 0.0,
        "sinr_stddev": 0.0,
        "rsrp_current": -90,
        "sinr_current": 10,
        "rsrq_current": -10,
        "best_rsrp_diff": 0.0,
        "best_sinr_diff": 0.0,
        "best_rsrq_diff": 0.0,
        "altitude": 0.0,
        "service_type": "embb",
        "service_priority": 5,
        "latency_requirement_ms": 10.0,
        "throughput_requirement_mbps": 1.0,
        "reliability_pct": 99.0,
        "optimal_antenna": "a1",
    }


def test_save_and_load_model(tmp_path):
    samples = [make_sample(i) for i in range(15)]
    model = LightGBMSelector(model_path=None, n_estimators=5)
    metrics = model.train(samples)

    out = tmp_path / "model.pkl"
    model_path = str(out)
    # Save and load
    assert model.save(model_path) is True
    new_model = LightGBMSelector(model_path=None)
    loaded = new_model.load(model_path)
    assert loaded is True
    # Run a predict with qos
    result = new_model.predict(new_model.extract_features(samples[0]))
    assert "antenna_id" in result
    assert "confidence" in result
    # cleanup
    for suffix in ("", ".scaler", ".meta.json"):
        try:
            os.remove(model_path + suffix)
        except OSError:
            pass
