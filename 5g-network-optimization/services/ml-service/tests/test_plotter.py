import importlib.util
from pathlib import Path

# Load plotter module directly to avoid package import issues
PLOTTER_PATH = Path(__file__).resolve().parents[1] / "ml_service" / "visualization" / "plotter.py"
spec = importlib.util.spec_from_file_location("plotter", PLOTTER_PATH)
plotter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plotter)
plot_antenna_coverage = plotter.plot_antenna_coverage
plot_movement_trajectory = plotter.plot_movement_trajectory


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
