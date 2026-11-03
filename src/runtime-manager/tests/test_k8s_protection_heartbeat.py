"""覆盖 AC: AC-07、AC-30、AC-31、AC-35、AC-40、AC-48、AC-49、AC-52、AC-55."""

import copy
import json
from types import SimpleNamespace

import pytest

from runtime_manager.config import Config
from runtime_manager.k8s_client import KubernetesAPIError
from runtime_manager.k8s_config import KubernetesConfig
from runtime_manager.operations import OperationExecutor
from tests.test_k8s_protection_report import NEW_HELPER, check, complete
from tests.test_k8s_protection_report import runtime as runtime


@pytest.fixture
def manager(runtime):
    sent = []

    def capture(body):
        sent.append(json.loads(json.dumps(body, allow_nan=False)))

    item = OperationExecutor(
        runtime.executor.config, platform=SimpleNamespace(heartbeat=capture), runtime=runtime.executor
    )
    try:
        yield item, sent
    finally:
        item.close()


def projections(runtime, monkeypatch, documents):
    original = KubernetesConfig.descriptor
    reads = []

    def read(settings):
        document = documents[min(len(reads), len(documents) - 1)]
        runtime.path.write_text(json.dumps(document))
        reads.append(document)
        return original(settings)

    monkeypatch.setattr(KubernetesConfig, "descriptor", read)
    return reads


@pytest.mark.parametrize("transition", ["expired_to_current", "current_to_failed", "current_to_expired"])
def test_real_manager_heartbeat_consumes_one_projection_and_next_heartbeat_refreshes(
    runtime, manager, monkeypatch, transition
):
    runtime.clock.now = 100000
    expired = copy.deepcopy(runtime.document)
    current = complete(runtime.document, runtime.clock.now)
    failed = copy.deepcopy(current)
    check(failed, "status-provenance")["ok"] = False
    first, second = {
        "expired_to_current": (expired, current),
        "current_to_failed": (current, failed),
        "current_to_expired": (current, expired),
    }[transition]
    reads = projections(runtime, monkeypatch, [first, second])
    executor, sent = manager
    executor.heartbeat()
    assert len(reads) == 1
    assert len(sent) == 1
    assert sent[0]["probe_report"]["ready"] is (transition != "expired_to_current")
    assert sent[0]["capabilities"]["status_protection"] is (transition != "expired_to_current")
    assert sent[0]["capabilities"]["protection_observation"]["state"] == (
        "report_expired" if transition == "expired_to_current" else "current"
    )
    executor.heartbeat()
    assert len(reads) == 2
    assert len(sent) == 2
    assert sent[1]["probe_report"]["ready"] is (transition == "expired_to_current")
    assert sent[1]["capabilities"]["status_protection"] is (transition == "expired_to_current")
    assert sent[1]["capabilities"]["protection_observation"]["state"] == (
        "report_expired" if transition == "current_to_expired" else "current"
    )


def test_helper_projection_cannot_mix_unknown_observation_with_later_failed_guard(runtime, manager, monkeypatch):
    helper = {**runtime.document, "helper_image": NEW_HELPER}
    failed = complete(helper)
    check(failed, "binding-delete-fence")["ok"] = False
    reads = projections(runtime, monkeypatch, [helper, failed])
    item, sent = manager
    item.heartbeat()
    assert len(reads) == 1
    assert sent[0]["capabilities"]["protection_observation"]["state"] == "helper_changed"
    assert sent[0]["probe_report"]["ready"] is False
    item.heartbeat()
    assert len(reads) == 2
    assert sent[1]["capabilities"]["protection_observation"]["state"] == "unconfirmed"
    assert sent[1]["probe_report"]["ready"] is False


def test_snapshot_returns_the_assessed_pair_and_capabilities_uses_it(runtime, monkeypatch):
    result = runtime.executor.heartbeat_snapshot()
    assert set(result) == {"capabilities", "probe_report"}
    assert result["probe_report"]["ready"] is True
    assert result["capabilities"]["status_protection"] is True
    assert result["capabilities"]["protection_observation"]["state"] == "current"
    calls = []

    def snapshot():
        calls.append(True)
        return result

    monkeypatch.setattr(runtime.executor, "heartbeat_snapshot", snapshot)
    assert runtime.executor.capabilities() is result["capabilities"]
    assert calls == [True]


def test_real_manager_prefers_snapshot_and_never_calls_legacy_pair(runtime, manager, monkeypatch):
    for name in ("capabilities", "probe_report"):
        monkeypatch.setattr(runtime.executor, name, lambda: pytest.fail("independent heartbeat re-read"))
    item, sent = manager
    item.heartbeat()
    assert len(sent) == 1
    assert sent[0]["probe_report"]["ready"] is True


@pytest.mark.parametrize("snapshot", [None, "not-callable"])
def test_legacy_fake_runtime_keeps_explicit_callable_fallback(snapshot):
    calls, sent = [], []
    descriptor = SimpleNamespace(
        cluster_id="cluster-a",
        namespace="runtime-apps",
        platform="linux/amd64",
        memory_budget_mb=4096,
        cpu_budget_millicores=4000,
    )

    def capabilities():
        calls.append("capabilities")
        return {"orchestration_available": True}

    def probe_report():
        calls.append("probe_report")
        return {"ready": True}

    runtime = SimpleNamespace(
        descriptor=descriptor,
        heartbeat_snapshot=snapshot,
        capabilities=capabilities,
        probe_report=probe_report,
    )
    manager = OperationExecutor(
        Config(executor_kind="kubernetes", protocol_version=2),
        platform=SimpleNamespace(heartbeat=sent.append),
        runtime=runtime,
    )
    try:
        manager.heartbeat()
    finally:
        manager.close()
    assert calls == ["capabilities", "probe_report"]
    assert len(sent) == 1 and sent[0]["probe_report"]["ready"] is True


def test_snapshot_error_is_not_retried_or_hidden_by_legacy_fallback(runtime, manager, monkeypatch):
    calls = []

    def snapshot():
        calls.append(True)
        raise ValueError("snapshot_unavailable")

    monkeypatch.setattr(runtime.executor, "heartbeat_snapshot", snapshot, raising=False)
    monkeypatch.setattr(
        runtime.executor, "capabilities", lambda: pytest.fail("must not fall back after unknown snapshot")
    )
    item, sent = manager
    with pytest.raises(ValueError, match="snapshot_unavailable"):
        item.heartbeat()
    assert calls == [True] and sent == []


def test_snapshot_preserves_orchestration_failure_and_current_guard_evidence(runtime, manager):
    def unavailable(*args, **kwargs):
        raise KubernetesAPIError("unavailable", 503)

    runtime.cluster.list = unavailable
    item, sent = manager
    item.heartbeat()
    assert len(sent) == 1
    assert sent[0]["probe_report"]["ready"] is False
    assert sent[0]["capabilities"]["orchestration_available"] is False
    assert sent[0]["capabilities"]["status_protection"] is True
    assert sent[0]["capabilities"]["binding_protection"] is True
    assert sent[0]["capabilities"]["protection_observation"]["state"] == "current"


def test_docker_heartbeat_does_not_enter_the_kubernetes_snapshot_branch():
    calls = []
    runtime = SimpleNamespace(
        heartbeat=lambda: calls.append("docker") or {"docker": True},
        heartbeat_snapshot=lambda: pytest.fail("Docker must retain its executor heartbeat"),
    )
    manager = OperationExecutor(Config(executor_kind="docker"), platform=SimpleNamespace(), runtime=runtime)
    manager._legacy_owned = {"owned-container"}
    try:
        assert manager.heartbeat() == {"docker": True}
    finally:
        manager.close()
    assert calls == ["docker"] and runtime._legacy_owned == {"owned-container"}
