import types
import sys
import time
from pathlib import Path

UE_PATH = Path(__file__).resolve().parents[1] / "backend" / "app" / "app" / "api" / "api_v1" / "endpoints" / "ue_movement.py"

# Load the portion of the module containing BackgroundTasks
with open(UE_PATH) as f:
    lines = [next(f) for _ in range(320)]
SOURCE = ''.join(lines)

def load_module(monkeypatch):
    app_pkg = types.ModuleType("app")
    # crud stubs
    crud_mod = types.ModuleType("app.crud")
    crud_mod.ue = types.SimpleNamespace(get_supi=lambda *a, **k: None,
                                        update_coordinates=lambda *a, **k: None,
                                        update=lambda *a, **k: None)
    crud_mod.path = types.SimpleNamespace()
    crud_mod.points = types.SimpleNamespace()
    crud_mod.cell = types.SimpleNamespace()
    crud_mod.user = types.SimpleNamespace(is_superuser=lambda u: False)
    crud_mod.crud_mongo = types.ModuleType("crud_mongo")
    crud_mongo_mod = crud_mod.crud_mongo
    crud_mongo_mod.read_by_multiple_pairs = lambda *a, **k: None
    crud_mongo_mod.update = lambda *a, **k: None
    crud_mongo_mod.delete_by_uuid = lambda *a, **k: None
    crud_mongo_mod.read = lambda *a, **k: {"qosMonInfo": {"repFreqs": [], "repPeriod": 1}, "owner_id": 0}
    app_pkg.crud = crud_mod

    tools_pkg = types.ModuleType("app.tools")
    dist_mod = types.ModuleType("app.tools.distance")
    dist_mod.check_distance = lambda *a, **k: None
    tools_pkg.distance = dist_mod
    tools_pkg.qos_callback = types.ModuleType("app.tools.qos_callback")
    mc_mod = types.ModuleType("app.tools.monitoring_callbacks")
    mc_mod.loss_of_connectivity_callback = lambda *a, **k: types.SimpleNamespace(json=lambda: {"ack": "ok"})
    mc_mod.ue_reachability_callback = lambda *a, **k: None
    mc_mod.location_callback = lambda *a, **k: None
    timer_mod = types.ModuleType("app.tools.timer")
    class DummySeqTimer:
        def __init__(self, **kw):
            pass
        def start(self):
            pass
        def stop(self):
            pass
        def status(self):
            return 0
    class DummyRT:
        def __init__(self, *a, **k):
            self.is_running = False
        def start(self):
            self.is_running = True
        def stop(self):
            self.is_running = False
    class TimerError(Exception):
        pass
    timer_mod.SequencialTimer = DummySeqTimer
    timer_mod.RepeatedTimer = DummyRT
    timer_mod.TimerError = TimerError
    tools_pkg.monitoring_callbacks = mc_mod
    tools_pkg.timer = timer_mod
    app_pkg.tools = tools_pkg

    models_pkg = types.ModuleType("app.models")
    models_pkg.User = types.SimpleNamespace
    app_pkg.models = models_pkg

    api_pkg = types.ModuleType("app.api")
    deps_mod = types.ModuleType("app.api.deps")
    api_pkg.deps = deps_mod
    app_pkg.api = api_pkg

    api_v1_pkg = types.ModuleType("app.api.api_v1")
    state_mod = types.ModuleType("app.api.api_v1.state_manager")
    class DummySM:
        def __init__(self):
            self._ues = {}
        def set_ue(self, supi, data):
            self._ues[supi] = data
        def get_ue(self, supi):
            return self._ues.get(supi)
        def remove_ue(self, supi):
            self._ues.pop(supi, None)
        def set_thread(self, *a, **k):
            pass
        def get_thread(self, *a, **k):
            return None
        def remove_thread(self, *a, **k):
            pass
        def all_ues(self):
            return self._ues
        def increment_timer_error(self):
            pass
    state_mod.state_manager = DummySM()
    api_v1_pkg.state_manager = state_mod
    app_pkg.api.api_v1 = api_v1_pkg

    db_pkg = types.ModuleType("app.db")
    session_mod = types.ModuleType("app.db.session")
    class DummySession:
        def close(self):
            pass
    session_mod.SessionLocal = lambda: DummySession()
    session_mod.client = types.SimpleNamespace(fastapi=object())
    db_pkg.session = session_mod
    app_pkg.db = db_pkg

    schemas_mod = types.ModuleType("app.schemas")
    class Msg: ...
    schemas_mod.Msg = Msg

    modules = {
        "app": app_pkg,
        "app.crud": crud_mod,
        "crud_mongo": crud_mongo_mod,
        "app.tools": tools_pkg,
        "app.tools.distance": dist_mod,
        "app.tools.qos_callback": tools_pkg.qos_callback,
        "app.tools.monitoring_callbacks": mc_mod,
        "app.tools.timer": timer_mod,
        "app.models": models_pkg,
        "app.api": api_pkg,
        "app.api.deps": deps_mod,
        "app.api.api_v1": api_v1_pkg,
        "app.api.api_v1.state_manager": state_mod,
        "app.db": db_pkg,
        "app.db.session": session_mod,
        "app.schemas": schemas_mod,
    }

    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)

    module = types.ModuleType("ue_mod")
    exec(SOURCE, module.__dict__)
    return module


def test_thread_stops_quickly(monkeypatch):
    ue_module = load_module(monkeypatch)
    ue_module.ue_data = {
        "latitude": 0,
        "longitude": 0,
        "speed": "LOW",
        "external_identifier": "ue1",
        "ip_address_v4": "1.1.1.1",
        "Cell_id": None,
    }
    task = ue_module.BackgroundTasks(args=(object(), "ue1", [], [{"latitude": 0, "longitude": 0}], True))
    task.start()
    time.sleep(0.05)
    start = time.perf_counter()
    task.stop()
    task.join(timeout=0.3)
    elapsed = time.perf_counter() - start
    assert not task.is_alive()
    assert elapsed < 0.3
