import os
import sys

# Ensure the NEF emulator root is on sys.path for all tests
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND_ROOT = os.path.join(ROOT, 'backend')
APP_ROOT = os.path.join(BACKEND_ROOT, 'app')
ML_ROOT_PARENT = os.path.abspath(os.path.join(ROOT, '..'))

for path in [ML_ROOT_PARENT, ROOT, BACKEND_ROOT, APP_ROOT]:
    if path not in sys.path:
        sys.path.insert(0, path)

# Provide a minimal stub for optional database module used in tools
import types
crud_stub = types.ModuleType("crud")
crud_stub.crud_mongo = object()
sys.modules.setdefault("app.crud", crud_stub)
