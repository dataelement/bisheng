"""Data helpers must not spend their 100m CPU budget importing the HTTP server."""

import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime_manager.errors import DataBusyError

ROOT = Path(__file__).resolve().parents[1]


def test_worker_import_has_no_control_plane_dependencies():
    code = """
import sys
from runtime_manager import data_worker
assert 'fastapi' not in sys.modules
assert 'pydantic' not in sys.modules
assert 'runtime_manager.container_runner' not in sys.modules
assert 'runtime_manager.docker_backend' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_error_preserves_http_envelope():
    app = FastAPI()

    @app.get("/busy")
    def busy():
        raise DataBusyError("busy", request_id="test-request")

    response = TestClient(app).get("/busy")
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "data_busy", "message": "busy", "request_id": "test-request"}}


def test_execution_error_compatibility_export():
    from runtime_manager.container_runner import ExecutionError
    from runtime_manager.execution_errors import ExecutionError as WorkerError

    assert ExecutionError is WorkerError
    assert WorkerError("failed", "tail").tail == "tail"


async def test_docker_read_contention_is_busy_not_maintenance(monkeypatch, tmp_path):
    from threading import Lock
    from types import SimpleNamespace

    import pytest
    from starlette.requests import Request

    from runtime_manager.api import platform_data
    from runtime_manager.config import Config

    lock = Lock()
    lock.acquire()
    service = SimpleNamespace(
        config=Config(data_root=tmp_path, node_id="test-node"),
        platform=SimpleNamespace(application=lambda _: {"node_id": "test-node", "phase": "online"}),
        _guard=Lock(),
        _apps={"app-a": lock},
    )

    async def authorized(_request):
        return None

    monkeypatch.setattr(platform_data, "authorized", authorized)
    monkeypatch.setattr(platform_data, "executor", lambda: service)
    request = Request({"type": "http", "method": "GET", "path_params": {"app_id": "app-a"}, "headers": []})
    try:
        with pytest.raises(DataBusyError) as caught:
            await anext(platform_data.scoped_data(request))
        assert caught.value.detail["code"] == "data_busy"
        assert "maintenance" not in caught.value.detail["message"]
        assert lock.locked()
    finally:
        lock.release()
