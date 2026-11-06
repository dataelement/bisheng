"""覆盖 AC: AC-01、AC-04、AC-10、AC-36、AC-37、AC-56."""

from copy import deepcopy

import pytest

from runtime_manager.config import Config
from runtime_manager.container_runner import ExecutionError
from tests.test_operations_v2 import Docker, Platform


def adapter(tmp_path, **kwargs):
    from runtime_manager.executors.docker import DockerExecutor

    return DockerExecutor(Config(data_root=tmp_path, node_id="node-a"), Platform(), Docker(), **kwargs)


def test_docker_adapter_prepares_bundle_through_the_existing_preparer(tmp_path, monkeypatch):
    from runtime_manager.executors import docker as module

    calls = []

    class Preparer:
        def __init__(self, config, platform, *, runner):
            calls.append((config.node_id, platform, runner))

        def prepare(self, operation):
            return {"mode": "bundle", "compiled_artifact_id": operation["operation_id"]}

    monkeypatch.setattr(module, "BundlePreparer", Preparer)
    executor = adapter(tmp_path)
    operation = deepcopy(executor.platform.op)
    operation.update(kind="prepare", payload={"delivery": {"mode": "bundle"}})
    assert executor.prepare(operation) == {"mode": "bundle", "compiled_artifact_id": operation["operation_id"]}
    assert calls[0][0] == "node-a"


def test_docker_adapter_preserves_image_entrypoint_and_startup_inputs(tmp_path, monkeypatch):
    from runtime_manager.executors import docker as module

    calls = []

    class Launcher:
        def __init__(self, config, *, runner, checkpoint):
            pass

        def start(self, operation, delivery, **paths):
            calls.append((operation, delivery, paths))
            return {"exec_ref": "container-a", "target": {"host": "172.18.0.2", "port": 8080}}

    monkeypatch.setattr(module, "BundleLauncher", Launcher)
    executor = adapter(tmp_path)
    op = deepcopy(executor.platform.op)
    op["payload"] = {
        "resolved_delivery": {"mode": "image", "image_ref": "example/app@sha256:" + "a" * 64, "startup": {}}
    }
    result = executor.launch(op)
    assert result["exec_ref"] == "container-a"
    assert calls[0] == (op, op["payload"]["resolved_delivery"], {})


def test_docker_adapter_stop_does_not_treat_running_or_missing_as_proven(tmp_path):
    executor = adapter(tmp_path)
    running = {"value": True}

    def inspect(ref):
        if ref == "missing":
            raise SimpleError()
        return {
            "Config": {
                "Labels": {"bisheng.managed": "v2", "bisheng.runtime.node": "node-a", "bisheng.app.id": "app-a"}
            },
            "State": {"Running": running["value"]},
        }

    class SimpleError(Exception):
        status_code = 404

    executor.docker.inspect_container = inspect
    executor.docker.stop_container = lambda *args, **kwargs: None
    executor.request_stop("container-a", executor.platform.op)
    assert executor.confirm_stopped("container-a")["stopped"] is False
    assert executor.confirm_stopped("missing")["stopped"] is False
    running["value"] = False
    assert executor.confirm_stopped("container-a")["stopped"] is True


def test_docker_adapter_refuses_foreign_execution_before_stop(tmp_path):
    executor = adapter(tmp_path)
    executor.docker.inspect_container = lambda ref: {
        "Config": {"Labels": {"bisheng.managed": "v2", "bisheng.runtime.node": "other", "bisheng.app.id": "app-a"}}
    }
    executor.docker.stop_container = lambda *args, **kwargs: pytest.fail("foreign execution")
    with pytest.raises(ExecutionError):
        executor.request_stop("foreign", executor.platform.op)


def test_existing_operation_executor_uses_the_docker_adapter(tmp_path):
    from runtime_manager.executors.docker import DockerExecutor
    from runtime_manager.operations import OperationExecutor

    executor = OperationExecutor(Config(data_root=tmp_path), Platform(), Docker())
    try:
        assert isinstance(executor.runtime, DockerExecutor)
        assert executor.runtime.docker is executor.docker
    finally:
        executor.close()
