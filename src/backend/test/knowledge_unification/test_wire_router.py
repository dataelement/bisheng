"""T196: inspect the actual application in a fresh interpreter, without route doubles."""

import os
import subprocess
import sys
from pathlib import Path


def test_actual_registry_and_openapi_import_in_a_fresh_process(tmp_path):
    backend = Path(__file__).resolve().parents[2]
    script = """
from bisheng.common.services.config_service import settings
# Test collection must not write deployment log files outside its workspace.
settings.logger_conf.handlers = []
from bisheng.main import app
assert app.openapi()["paths"]
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend)},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-12000:]
