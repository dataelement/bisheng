"""覆盖 AC: AC-47、AC-52、AC-53。"""

from pathlib import Path

from runtime_manager.config import Config
from runtime_manager.data_executor import DataExecutor


def test_data_helper_has_only_target_app_and_disposable_output(tmp_path):
    config = Config(data_root=tmp_path, host_data_root=Path("/host/data"), node_id="node")
    service = DataExecutor(config, None)
    output = tmp_path / "data-jobs/job"
    output.mkdir(parents=True)
    body = service.payload("app-a", "rows", {"table": "data"}, output, "sha256:" + "a" * 64, "job")
    assert body["HostConfig"]["NetworkMode"] == "none"
    assert body["HostConfig"]["Binds"] == [
        "/host/data/apps/app-a/db:/app-data/apps/app-a/db:ro",
        "/host/data/data-jobs/job:/app-data/exports:rw",
    ]
    assert body["Env"] == ["PYTHONDONTWRITEBYTECODE=1"]
    assert body["HostConfig"]["CapDrop"] == ["ALL"]
    assert body["User"] == "10001:10001"


def test_helper_error_is_preserved_and_container_is_removed(tmp_path, monkeypatch):
    import json

    import pytest
    from fastapi import HTTPException

    class Engine:
        removed = []

        def inspect_image(self, ref):
            return {"Id": "image"}

        def list_containers(self, **kwargs):
            return []

        def create_container(self, name, body):
            return "created"

        def start_container(self, ref):
            pass

        def inspect_container(self, ref):
            return {"State": {"Running": False, "ExitCode": 0}}

        def container_logs(self, ref, **kwargs):
            result = json.dumps({"error": {"code": "data_invalid"}, "status_code": 400})
            return result if kwargs.get("timestamps") is False else "2026-10-20T00:00:00Z " + result

        def remove_container(self, ref, **kwargs):
            self.removed.append(ref)

    monkeypatch.setattr("runtime_manager.data_executor.os.chown", lambda *args: None)
    engine = Engine()
    service = DataExecutor(Config(data_root=tmp_path, data_helper_image="image", reserve_mb=256), engine)
    with pytest.raises(HTTPException) as result:
        service.call("app", "rows", {"table": "bad"})
    assert result.value.status_code == 400
    assert engine.removed == ["created"]
    assert list((tmp_path / "data-jobs").iterdir()) == []
