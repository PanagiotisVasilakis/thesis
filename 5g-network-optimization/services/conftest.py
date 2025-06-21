import os
import sys

# Ensure service packages are on sys.path for all tests
SERVICES_ROOT = os.path.abspath(os.path.dirname(__file__))
NEF_ROOT = os.path.join(SERVICES_ROOT, 'nef-emulator')
NEF_BACKEND_ROOT = os.path.join(NEF_ROOT, 'backend')
NEF_APP_ROOT = os.path.join(NEF_BACKEND_ROOT, 'app')

for path in reversed([NEF_APP_ROOT, NEF_BACKEND_ROOT, NEF_ROOT]):
    if path not in sys.path:
        sys.path.insert(0, path)

# Provide a minimal stub for optional database module used in tools
import types
crud_stub = types.ModuleType("crud")
crud_stub.crud_mongo = object()
sys.modules.setdefault("app.crud", crud_stub)

# Provide lightweight settings for tests avoiding env var requirements
config_stub = types.ModuleType("config")
settings_stub = types.SimpleNamespace(
    API_V1_STR="/api/v1",
    FIRST_SUPERUSER="admin@example.com",
    FIRST_SUPERUSER_PASSWORD="password",
    EMAIL_TEST_USER="test@example.com",
)
config_stub.settings = settings_stub
sys.modules.setdefault("app.core.config", config_stub)
