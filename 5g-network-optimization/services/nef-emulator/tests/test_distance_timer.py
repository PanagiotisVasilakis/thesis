import json

import pytest

from backend.app.app.tools import distance as dist_mod
from backend.app.app.tools import timer as timer_mod
from backend.app.app.tools.mobility.adapter import MobilityPatternAdapter


def test_distance_haversine():
    d = dist_mod.distance(0.0, 0.0, 0.0, 1.0)
    # 1 degree of longitude at equator ~111.2 km
    assert pytest.approx(d, rel=0.01) == 111000


def test_check_distance():
    cells = [
        {"latitude": 0.0, "longitude": 0.0, "radius": 150, "description": "A"},
        {"latitude": 0.0, "longitude": 0.002, "radius": 50, "description": "B"},
    ]
    # Position near cell A but outside B
    cell = dist_mod.check_distance(0.0, 0.001, cells)
    assert cell and cell["description"] == "A"
    # Position outside any cell
    assert dist_mod.check_distance(1.0, 1.0, cells) is None


def test_sequencial_timer(monkeypatch):
    tvals = iter([0.0, 1.5])
    monkeypatch.setattr(timer_mod.time, "perf_counter", lambda: next(tvals))
    timer = timer_mod.SequencialTimer(logger=None)
    timer.start()
    elapsed = timer.stop()
    assert pytest.approx(elapsed, rel=1e-6) == 1.5


def test_repeated_timer(monkeypatch):
    calls = []

    class DummyTimer:
        def __init__(self, interval, func):
            self.interval = interval
            self.func = func
            self.cancelled = False

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(timer_mod, "Timer", DummyTimer)

    def cb(x):
        calls.append(x)

    rt = timer_mod.RepeatedTimer(1, cb, 1)
    assert rt.is_running is True
    rt._run()  # trigger once
    assert calls == [1]
    assert rt.is_running is True  # restarted
    rt.stop()
    assert rt.is_running is False
    assert rt._timer.cancelled is True


def test_adapter_functions(tmp_path):
    model = MobilityPatternAdapter.get_mobility_model(
        "linear",
        "ue1",
        start_position=(0, 0, 0),
        end_position=(10, 0, 0),
        speed=1.0,
    )
    pts = MobilityPatternAdapter.generate_path_points(model, duration=5, time_step=1)
    assert pts and pts[0]["latitude"] == 0
    json_path = tmp_path / "path.json"
    out = MobilityPatternAdapter.save_path_to_json(pts, json_path.as_posix())
    assert out == json_path.as_posix()
    with open(out) as f:
        saved = json.load(f)
    assert saved[0]["latitude"] == pts[0]["latitude"]
    # altitude field removed if None
    assert "altitude" not in saved[0] or saved[0]["altitude"] is not None
