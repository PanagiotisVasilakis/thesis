import importlib.util
from pathlib import Path
import sys
import types

import pytest
import requests

MODULE_PATH = Path(__file__).parent / "api" / "test_utils_functions.py"
_previous_constants = sys.modules.get("app.core.constants")
const_mod = types.ModuleType("app.core.constants")
const_mod.DEFAULT_TIMEOUT = (3.05, 27)
sys.modules["app.core.constants"] = const_mod
spec = importlib.util.spec_from_file_location("test_utils_functions", MODULE_PATH)
test_utils_functions = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(test_utils_functions)
finally:
    if _previous_constants is None:
        sys.modules.pop("app.core.constants", None)
    else:
        sys.modules["app.core.constants"] = _previous_constants

utils = test_utils_functions.utils


def test_get_test_uses_timeout(monkeypatch):
    calls = {}
    monkeypatch.setenv("ENABLE_TEST_CALLBACK_ENDPOINT", "1")
    monkeypatch.setenv("TEST_CALLBACK_PAYLOAD", "{}")

    def fake_request(method, url, headers=None, data=None, timeout=None):
        calls["timeout"] = timeout
        raise requests.exceptions.Timeout

    monkeypatch.setattr(utils.requests, "request", fake_request)

    with pytest.raises(requests.exceptions.Timeout):
        utils.get_test(utils.callback(callbackurl="http://example.org"))

    assert calls["timeout"] == utils.DEFAULT_TIMEOUT
