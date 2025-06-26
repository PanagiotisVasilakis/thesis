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
crud_stub.ue = object()
crud_stub.user = object()
crud_stub.gnb = object()

# Ensure hierarchy packages exist so ``import app.crud`` succeeds during
# module import at collection time.
app_pkg = sys.modules.setdefault("app", types.ModuleType("app"))
app_pkg.__path__ = []
app_pkg.crud = crud_stub
sys.modules.setdefault("app.crud", crud_stub)

# Provide lightweight settings for tests avoiding env var requirements
config_stub = types.ModuleType("config")

class SettingsStub(types.SimpleNamespace):
    def __getattr__(self, name):
        return None

settings_stub = SettingsStub(
    API_V1_STR="/api/v1",
    FIRST_SUPERUSER="admin@example.com",
    FIRST_SUPERUSER_PASSWORD="password",
    EMAIL_TEST_USER="test@example.com",
    SQLALCHEMY_DATABASE_URI="postgresql://user:pass@localhost/testdb",
    MONGO_CLIENT="mongodb://localhost:27017",
    PROJECT_NAME="Test Project",
)
class QoSSettings:
    def retrieve_settings(self):
        return {}

config_stub.qosSettings = QoSSettings()
config_stub.settings = settings_stub

core_pkg = sys.modules.setdefault("app.core", types.ModuleType("core"))
core_pkg.__path__ = []
core_pkg.config = config_stub
app_pkg.core = core_pkg
sys.modules.setdefault("app.core.config", config_stub)
