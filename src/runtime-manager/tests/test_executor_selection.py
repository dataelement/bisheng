"""覆盖 AC: AC-01、AC-02、AC-04、AC-05、AC-07、AC-08、AC-09、AC-36、AC-37、AC-39、AC-48、AC-56."""

import copy
from types import SimpleNamespace

import pytest

from runtime_manager.config import Config
from runtime_manager.executors.protocol import ExecutorError
from runtime_manager.operations import OperationExecutor
from tests.test_operations_v2 import Platform


class Backend(Platform):
    def __init__(self, kind):
        super().__init__(kind)
        self.op["payload"] = {"uses_sqlite": False}
        self.op["result"] = {}
        self.observations = []

    def fact(self, operation, sequence, phase, **kwargs):
        super().fact(operation, sequence, phase, **kwargs)
        self.op["result"] = copy.deepcopy(kwargs.get("detail", {}))
        if phase == "ready" and self.op["kind"] == "deploy":
            self.op["stage"] = "serving"

    def node_snapshot(self):
        return {"operations": [copy.deepcopy(self.op)], "node": {"controller_epoch": 1}}

    def resources(self, operation_id):
        return []

    def observation(self, document):
        self.observations.append(document)


class Runtime:
    def __init__(self):
        self.calls = []
        self.cleanup_complete = True
        self.ready = True
        self.data_failure = None

    def _controller(self):
        return {"holder_id": "controller-a", "controller_epoch": 1}

    def capabilities(self):
        return {"executor_kind": "kubernetes", "status_policy_revision": "v1", "mandatory_isolation": True}

    def prepare(self, operation):
        self.calls.append("prepare")
        return {"mode": "bundle", "compiled_artifact_id": "compiled-a"}

    def launch(self, operation, *, preview=False):
        self.calls.append(("launch", preview))
        return {
            "exec_ref": "pod-a",
            "pod_uid": "uid-a",
            "service_ref": "service-a",
            "service_uid": "service-uid",
            "ready": True,
            "target": {"host": "10.96.0.2", "port": 8080},
        }

    def observe(self, exec_ref):
        self.calls.append(("observe", exec_ref))
        return {"exec_ref": exec_ref, "running": True, "ready": self.ready, "phase": "Running"}

    def cleanup(self, operation):
        self.calls.append("cleanup")
        return {"complete": self.cleanup_complete}

    def data(self, operation, action, parameters):
        self.calls.append(("data", action))
        if self.data_failure:
            raise self.data_failure
        return {"artifact_id": "snapshot-a", "state": "verified"}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    import runtime_manager.operations as module

    monkeypatch.setattr(module, "get_docker_backend", lambda: pytest.fail("K8s initialized Docker"))
    backend, driver = Backend("prepare"), Runtime()
    executor = OperationExecutor(
        Config(executor_kind="kubernetes", protocol_version=2, data_root=tmp_path, node_id="node-a"),
        backend,
        runtime=driver,
    )
    try:
        yield executor, backend, driver
    finally:
        executor.close()


def test_kubernetes_prepare_uses_capabilities_and_controller_facts(runtime):
    executor, platform, driver = runtime
    platform.op["result"] = {"prepare_progress": {"inputs": {"result": {"input_key": "a" * 64}}}}
    executor.execute("operation-a")
    assert driver.calls == ["prepare", "cleanup"]
    assert [phase for phase, _ in platform.facts] == ["preparing", "completed"]
    assert platform.facts[0][1]["prepare_progress"]["inputs"]["result"]["input_key"] == "a" * 64
    assert all(detail["controller"] == driver._controller() for _, detail in platform.facts)
    assert platform.facts[-1][1]["delivery"]["compiled_artifact_id"] == "compiled-a"


def test_unknown_cleanup_keeps_the_reservation_held(runtime):
    executor, platform, driver = runtime
    driver.cleanup_complete = False
    executor.execute("operation-a")
    phase, detail = platform.facts[-1]
    assert phase == "failed" and detail["stopped"] is False and detail["cleanup_complete"] is False


@pytest.mark.parametrize("kind,preview", [("probe", False), ("preview", True)])
def test_probe_and_preview_preserve_their_distinct_resource_scopes(runtime, kind, preview):
    executor, platform, driver = runtime
    platform.op["kind"] = kind
    executor.execute("operation-a")
    assert ("launch", preview) in driver.calls
    assert ("cleanup" in driver.calls) is (kind == "probe")
    assert [phase for phase, _ in platform.facts][:2] == ["starting", "ready"]


def test_deploy_waits_for_platform_route_commit_and_preserves_candidate(runtime):
    executor, platform, driver = runtime
    platform.op["kind"] = "deploy"
    executor.execute("operation-a")
    assert [phase for phase, _ in platform.facts] == ["starting", "ready", "completed"]
    assert "cleanup" not in driver.calls
    assert platform.facts[-1][1]["serving"] is True


def test_snapshot_failure_never_starts_or_migrates_a_new_writer(runtime):
    executor, platform, driver = runtime
    platform.op["kind"] = "deploy"
    platform.op["payload"] = {"uses_sqlite": True, "migration_plan": [{"sql": "create table fixture(id integer)"}]}
    driver.data_failure = ExecutorError("snapshot_upload_failed")
    executor.execute("operation-a")
    assert [phase for phase, _ in platform.facts] == ["maintenance", "failed"]
    assert ("data", "backup") in driver.calls
    assert not any(isinstance(call, tuple) and call[0] == "launch" for call in driver.calls)
    assert ("data", "migrate") not in driver.calls


def test_serving_preview_restart_observes_existing_workload(runtime):
    executor, platform, driver = runtime
    platform.op.update(kind="preview", stage="serving", status="running", execution={"exec_ref": "preview-a"})
    executor.execute("operation-a")
    assert driver.calls == [("observe", "preview-a")]
    assert not platform.facts


def test_default_composition_selects_kubernetes_without_docker(tmp_path, monkeypatch):
    from runtime_manager.executors import kubernetes
    from runtime_manager.k8s_config import KubernetesConfig

    monkeypatch.setattr("runtime_manager.operations.get_docker_backend", lambda: pytest.fail("Docker selected"))
    selected = []
    driver = Runtime()
    monkeypatch.setattr(KubernetesConfig, "from_env", lambda: SimpleNamespace(namespace="fixture"))

    def create(config, settings, **kwargs):
        selected.append((config.executor_kind, settings.namespace))
        return driver

    monkeypatch.setattr(kubernetes, "KubernetesExecutor", create)
    executor = OperationExecutor(
        Config(executor_kind="kubernetes", protocol_version=2, data_root=tmp_path), Backend("prepare")
    )
    try:
        assert executor.runtime is driver and selected == [("kubernetes", "fixture")]
    finally:
        executor.close()


def test_wakeup_rejects_executable_payload_fields():
    from pydantic import ValidationError

    from runtime_manager.api.operations import Wakeup

    with pytest.raises(ValidationError):
        Wakeup.model_validate({"operation_id": "operation-a", "pod_spec": {"hostNetwork": True}})
