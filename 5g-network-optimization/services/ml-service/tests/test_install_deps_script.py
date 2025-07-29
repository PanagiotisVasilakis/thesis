import os
import subprocess
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[4] / "scripts" / "install_deps.sh"


def test_install_deps_skip_if_present(tmp_path):
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(tmp_path)
    result = subprocess.run(
        [str(SCRIPT_PATH), "--skip-if-present"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "skipping installation" in result.stderr.lower()


def test_install_deps_unknown_option():
    result = subprocess.run(
        [str(SCRIPT_PATH), "--does-not-exist"], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "unknown option" in result.stderr.lower()
