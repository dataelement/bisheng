"""覆盖 AC: AC-19。使用独立进程验证生产路由导入。"""

import os
import subprocess
import sys
from pathlib import Path


def test_api_registers_knowledge_without_preloaded_worker(tmp_path):
    config = tmp_path / "empty.yaml"
    config.write_text("{}\n")
    backend = Path(__file__).resolve().parents[2]
    script = """
import socket
def deny(*args, **kwargs):
    raise AssertionError("module import must not contact external services")
socket.socket.connect = deny
socket.socket.connect_ex = deny
from bisheng.main import app
assert any(route.path == "/api/v1/workflow/platform-knowledge" for route in app.routes)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env={**os.environ, "config": str(config), "PYTHONPATH": str(backend)},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr[-4000:]
