from pathlib import Path

from ml_service.app.visualization.plotter import (
    plot_antenna_coverage,
    plot_movement_trajectory,
)


class DummyAntennaSelector:
    """Minimal predictor for deterministic results."""

    def extract_features(self, data):
        return data

    def predict(self, features):
        return {"antenna_id": "a1", "confidence": 1.0}


def _check_png(path: Path):
    assert path.exists(), f"{path} was not created"
    with path.open("rb") as fh:
        signature = fh.read(8)
    assert signature == b"\x89PNG\r\n\x1a\n", "File is not a valid PNG"


def test_plot_functions_generate_png(tmp_path):
    model = DummyAntennaSelector()

    cov_path = Path(plot_antenna_coverage(model, output_dir=tmp_path))
    _check_png(cov_path)
    cov_path.unlink()

    movement = [
        {"latitude": 0, "longitude": 0, "connected_to": "a1"},
        {"latitude": 1, "longitude": 1, "connected_to": "a1"},
        {"latitude": 2, "longitude": 2, "connected_to": "a2"},
    ]
    traj_path = Path(plot_movement_trajectory(movement, output_dir=tmp_path))
    _check_png(traj_path)
    traj_path.unlink()
