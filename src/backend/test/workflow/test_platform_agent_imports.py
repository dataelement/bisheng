"""覆盖 AC-22。独立进程不继承 pytest 的预加载顺序和模块桩。"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.mark.parametrize("entry", ["bisheng.api.services.workflow", "bisheng.main"])
def test_api_imports_without_preloading_worker(entry, tmp_path):
    config = tmp_path / "empty.yaml"
    config.write_text("{}\n")
    backend = Path(__file__).resolve().parents[2]
    script = textwrap.dedent("""
        import importlib
        import socket
        import sys

        # 仅验证真实导入与路由构造。不启动 lifespan 或连接外部服务。
        def deny_network(*args, **kwargs):
            raise AssertionError("module import must not connect to external services")

        socket.socket.connect = deny_network
        socket.socket.connect_ex = deny_network
        module = importlib.import_module(sys.argv[1])
        if sys.argv[1] == "bisheng.main":
            assert any(route.path == "/api/v1/workflow/run_once" for route in module.app.routes)
        else:
            assert callable(module.WorkFlowService.run_once)
        print("PASS clean API import")
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, entry],
        cwd=backend,
        env={**os.environ, "config": str(config), "PYTHONPATH": str(backend)},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr[-6000:]
    assert "PASS clean API import" in result.stdout
