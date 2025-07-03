import importlib.util
import math
import random
from pathlib import Path
import sys

import numpy as np
import pytest


def _load_adapter(monkeypatch: pytest.MonkeyPatch):
    """Load MobilityPatternAdapter without importing the full app package."""
    backend_root = Path(__file__).resolve().parents[2] / "backend" / "app"
    monkeypatch.syspath_prepend(str(backend_root))

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    spec = importlib.util.spec_from_file_location(
        "app.tools.mobility.adapter",
        backend_root / "app" / "tools" / "mobility" / "adapter.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MobilityPatternAdapter


def test_linear_mobility(monkeypatch: pytest.MonkeyPatch):
    Adapter = _load_adapter(monkeypatch)
    model = Adapter.get_mobility_model(
        "linear",
        ue_id="ue1",
        start_position=(0, 0, 0),
        end_position=(10, 0, 0),
        speed=1.0,
    )
    traj = model.generate_trajectory(10, time_step=1.0)
    assert traj
    assert traj[0]["position"] == (0, 0, 0)
    last = traj[-1]["position"]
    assert last[0] == pytest.approx(10, abs=1)
    assert last[1:] == (0, 0)


def test_l_shaped_mobility(monkeypatch: pytest.MonkeyPatch):
    Adapter = _load_adapter(monkeypatch)
    model = Adapter.get_mobility_model(
        "l_shaped",
        ue_id="ue2",
        start_position=(0, 0, 0),
        corner_position=(5, 0, 0),
        end_position=(5, 5, 0),
        speed=1.0,
    )
    duration = 15
    traj = model.generate_trajectory(duration, time_step=1.0)
    assert traj
    last = traj[-1]["position"]
    assert last[0] == pytest.approx(5, abs=1)
    assert last[1] == pytest.approx(5, abs=1)
    corner = (5, 0, 0)
    assert min(math.hypot(p["position"][0]-corner[0], p["position"][1]-corner[1]) for p in traj) <= 1.0


def test_random_directional_mobility(monkeypatch: pytest.MonkeyPatch):
    Adapter = _load_adapter(monkeypatch)
    random.seed(0)
    np.random.seed(0)
    bounds = [(0, 10), (0, 10), (0, 0)]
    model = Adapter.get_mobility_model(
        "random_directional",
        ue_id="ue3",
        start_position=(5, 5, 0),
        speed=1.0,
        area_bounds=bounds,
        direction_change_mean=5.0,
    )
    traj = model.generate_trajectory(10, time_step=1.0)
    assert traj
    for p in traj:
        x, y, z = p["position"]
        assert bounds[0][0] <= x <= bounds[0][1]
        assert bounds[1][0] <= y <= bounds[1][1]
        assert z == 0


def test_urban_grid_mobility(monkeypatch: pytest.MonkeyPatch):
    Adapter = _load_adapter(monkeypatch)
    random.seed(1)
    grid = 5.0
    model = Adapter.get_mobility_model(
        "urban_grid",
        ue_id="ue4",
        start_position=(5, 5, 0),
        speed=1.0,
        grid_size=grid,
        turn_probability=1.0,
    )
    traj = model.generate_trajectory(10, time_step=1.0)
    assert traj
    for p in traj:
        x, y, _ = p["position"]
        on_x = abs(x % grid) < 1e-6
        on_y = abs(y % grid) < 1e-6
        assert on_x or on_y


def test_reference_point_group_mobility(monkeypatch: pytest.MonkeyPatch):
    Adapter = _load_adapter(monkeypatch)
    from app.mobility_models.models import ReferencePointGroupMobilityModel

    class Wrapper(ReferencePointGroupMobilityModel):
        def __init__(self, ue_id, reference_model, relative_position, max_deviation=5.0, deviation_change_mean=10.0, start_time=None):
            super().__init__(ue_id, group_center_model=reference_model, d_max=max_deviation, start_time=start_time)

    monkeypatch.setitem(Adapter.MODEL_TYPES, "group", Wrapper)
    random.seed(2)
    np.random.seed(2)
    ref_model = Adapter.get_mobility_model(
        "linear",
        ue_id="center",
        start_position=(0, 0, 0),
        end_position=(10, 0, 0),
        speed=1.0,
    )
    duration = 5
    center_traj = ref_model.generate_trajectory(duration, time_step=1.0)
    group_model = Adapter.get_mobility_model(
        "group",
        ue_id="member",
        reference_model=ref_model,
        relative_position=(0, 0, 0),
        max_deviation=2.0,
    )
    traj = group_model.generate_trajectory(duration, time_step=1.0)
    assert traj and len(traj) == len(center_traj)
    for p, c in zip(traj, center_traj):
        dist = math.hypot(p["position"][0]-c["position"][0], p["position"][1]-c["position"][1])
        assert dist <= 2.0 + 1e-6
