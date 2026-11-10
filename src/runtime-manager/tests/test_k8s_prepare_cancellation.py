"""F059 覆盖 AC: AC-43、AC-48、AC-49、AC-52、AC-55."""

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime_manager.executors.protocol import ExecutorError
from runtime_manager.k8s_templates import pod_template
from runtime_manager.platform_client import PlatformError
from tests.test_kubernetes_executor import runtime as runtime


@pytest.fixture
def preparation(runtime, monkeypatch):
    executor, platform, cluster, operation, events, clock = runtime
    operation["kind"] = "prepare"
    operation["payload"].update(
        delivery={"mode": "bundle"}, profile=operation["payload"]["resolved_delivery"]["profile"]
    )
    operation["deadline"] = clock.iso(20)
    platform.operations[operation["operation_id"]] = copy.deepcopy(operation)
    executor.probe_report = lambda: {"ready": True, "sandbox": {}}
    plan = replace(
        executor._plan(operation, "prepare-install", deadline=8),
        command=("python", "-I", "/runtime/tools/k8s_prepare.py"),
        material_secret="",
        app_secret="",
        secret_env=(),
    )
    harness = SimpleNamespace(
        executor=executor,
        platform=platform,
        cluster=cluster,
        operation=operation,
        plan=plan,
        clock=clock,
        events=events,
        start=clock.time(),
        succeeds_at=3,
        on_success=None,
    )
    original_create, original_get = cluster.create, cluster.get

    def create(resource, document):
        result = original_create(resource, document)
        if resource == "pods":
            body = cluster.objects[resource, document["metadata"]["name"]]
            body["status"]["phase"] = "Running"
            for container in body["status"]["containerStatuses"]:
                container["state"] = {"running": {}}
            result = copy.deepcopy(body)
        return result

    def get(resource, name):
        body = cluster.objects.get((resource, name))
        if resource == "pods" and body and not body["metadata"].get("deletionTimestamp"):
            complete = clock.time() >= harness.start + harness.succeeds_at
            body["status"]["phase"] = "Succeeded" if complete else "Running"
            for container in body["status"]["containerStatuses"]:
                container["state"] = {"terminated": {"exitCode": 0}} if complete else {"running": {}}
            if complete and harness.on_success:
                harness.on_success()
        return original_get(resource, name)

    monkeypatch.setattr(cluster, "create", create)
    monkeypatch.setattr(cluster, "get", get)
    return harness


def change_current(harness, **fields):
    current = copy.deepcopy(harness.platform.operations[harness.operation["operation_id"]])
    current.update(fields)
    harness.platform.operations[harness.operation["operation_id"]] = current


def cancel(harness, field="payload"):
    if field == "payload":
        current = harness.platform.operation(harness.operation["operation_id"])
        change_current(harness, payload={**current["payload"], "cancel_requested": True})
    else:
        change_current(harness, cancel_requested=True)


def after_sleep(harness, monkeypatch, action):
    original = harness.clock.sleep

    def sleep(seconds):
        assert 0 <= seconds <= 1, "phase waits must remain bounded by the virtual deadline"
        original(seconds)
        if harness.clock.time() >= harness.start + 1:
            action()

    monkeypatch.setattr(harness.clock, "sleep", sleep)


def phase(harness):
    return harness.executor._phase(harness.operation, "install", "prepare-install", {}, plan=harness.plan)


def no_progress(harness):
    saved = harness.platform.operation(harness.operation["operation_id"])
    assert "install" not in saved.get("result", {}).get("prepare_progress", {})
    assert not any(event[:2] == ("fact", "preparing") for event in harness.events)


def seed_cached_result(harness):
    template = pod_template(harness.plan)
    row = harness.executor._intent(harness.operation, harness.plan, template, harness.plan.resource_ref)
    harness.executor._volume(harness.operation, harness.plan)
    pod = harness.executor._create(row, template)
    current = harness.platform.operation(harness.operation["operation_id"])
    current["result"] = {
        "prepare_progress": {"install": {"exec_ref": harness.plan.resource_ref, "result": {"installed": True}}}
    }
    harness.platform.operations[harness.operation["operation_id"]] = current
    return pod["metadata"]["uid"]


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("field", ["payload", "top"])
def test_phase_entry_cancel_cannot_create_or_reuse_a_success(preparation, cached, field):
    """F059 覆盖 AC: AC-43、AC-52、AC-55."""
    h = preparation
    if cached:
        original_uid = seed_cached_result(h)
    cancel(h, field)
    with pytest.raises(ExecutorError, match=r"^operation_cancelled$"):
        phase(h)
    assert h.clock.time() == h.start
    if cached:
        row = h.platform.resource(h.plan.resource_ref)
        assert row["uid"] == original_uid and row["stop_state"] == "held"
    else:
        assert not h.platform.rows and not h.cluster.objects


def test_cancel_after_cached_writer_stop_does_not_return_cached_success(preparation, monkeypatch):
    """F059 覆盖 AC: AC-43、AC-49、AC-52、AC-55."""
    h = preparation
    original_uid = seed_cached_result(h)
    original = h.platform.observe_resource

    def stopped(reference, document):
        answer = original(reference, document)
        if document["action"] == "stopped":
            cancel(h)
        return answer

    monkeypatch.setattr(h.platform, "observe_resource", stopped)
    with pytest.raises(ExecutorError, match=r"^operation_cancelled$"):
        phase(h)
    row = h.platform.resource(h.plan.resource_ref)
    assert row["stop_state"] == "confirmed" and row["stop_evidence"]["uid"] == original_uid
    assert ("pods", row["name"]) not in h.cluster.objects


@pytest.mark.parametrize("change", ["payload_cancel", "top_cancel", "terminal"])
def test_running_preparation_observes_cancel_before_install_can_finish(preparation, monkeypatch, change):
    """F059 覆盖 AC: AC-43、AC-49、AC-52、AC-55."""
    h = preparation
    action = (
        (lambda: change_current(h, status="cancelled"))
        if change == "terminal"
        else (lambda: cancel(h, "payload" if change == "payload_cancel" else "top"))
    )
    after_sleep(h, monkeypatch, action)
    with pytest.raises(ExecutorError, match=r"^operation_cancelled$"):
        phase(h)
    assert h.clock.time() == h.start + 1 < h.start + h.succeeds_at
    no_progress(h)
    row = h.platform.resource(h.plan.resource_ref)
    uid = row["uid"]
    assert uid and row["stop_state"] == "held"
    assert h.executor.cleanup(h.operation)["complete"]
    row = h.platform.resource(h.plan.resource_ref)
    assert row["stop_state"] == "confirmed" and row["stop_evidence"]["uid"] == uid
    assert row["cleanup_state"] == "complete" and ("pods", row["name"]) not in h.cluster.objects


@pytest.mark.parametrize("field", ["operation_id", "app_id", "node_id", "generation", "owner_epoch"])
def test_running_preparation_rejects_changed_operation_fence(preparation, monkeypatch, field):
    """F059 覆盖 AC: AC-48、AC-49、AC-52、AC-55."""
    h = preparation
    value = h.operation[field] + 1 if field in {"generation", "owner_epoch"} else "foreign-scope"
    after_sleep(h, monkeypatch, lambda: change_current(h, **{field: value}))
    with pytest.raises(ExecutorError, match=r"^execution_fence_mismatch$"):
        phase(h)
    assert h.clock.time() == h.start + 1
    row = h.platform.resource(h.plan.resource_ref)
    assert row["stop_state"] == "held" and row["cleanup_state"] == "pending"
    no_progress(h)


@pytest.mark.parametrize("deadline", ["original", "shortened"])
def test_phase_cannot_extend_original_or_fresh_shortened_operation_deadline(preparation, monkeypatch, deadline):
    """F059 覆盖 AC: AC-43、AC-48、AC-52、AC-55."""
    h = preparation
    h.succeeds_at = 7
    if deadline == "original":
        h.operation["deadline"] = h.clock.iso(3)
        change_current(h, deadline=h.operation["deadline"])
        after_sleep(h, monkeypatch, lambda: change_current(h, deadline=h.clock.iso(100)))
        expected_elapsed = 3
    else:
        shortened = h.clock.iso(2)
        after_sleep(h, monkeypatch, lambda: change_current(h, deadline=shortened))
        expected_elapsed = 2
    with pytest.raises(ExecutorError, match=r"^operation_timeout$"):
        phase(h)
    assert h.clock.time() == h.start + expected_elapsed
    no_progress(h)


@pytest.mark.parametrize("at", ["entry", "running"])
def test_unknown_operation_read_never_becomes_success_or_progress(preparation, monkeypatch, at):
    """F059 覆盖 AC: AC-43、AC-48、AC-52、AC-55."""
    h = preparation
    original = h.platform.operation

    def unavailable(reference):
        if at == "entry" or h.clock.time() >= h.start + 1:
            raise PlatformError("platform_unreachable", 503)
        return original(reference)

    monkeypatch.setattr(h.platform, "operation", unavailable)
    with pytest.raises(PlatformError, match="platform_unreachable"):
        phase(h)
    assert h.clock.time() == h.start + (1 if at == "running" else 0)
    assert not any(event[:2] == ("fact", "preparing") for event in h.events)
    if at == "running":
        assert h.platform.resource(h.plan.resource_ref)["stop_state"] == "held"
    else:
        assert not h.platform.rows and not h.cluster.objects


@pytest.mark.parametrize("at", ["pod_succeeded", "result_log"])
def test_succeeded_pod_cannot_publish_progress_after_fresh_cancel(preparation, monkeypatch, at):
    """F059 覆盖 AC: AC-43、AC-48、AC-52、AC-55."""
    h = preparation
    if at == "pod_succeeded":
        h.on_success = lambda: cancel(h)
    else:
        original = h.cluster.logs

        def logs(name, **kwargs):
            value = original(name, **kwargs)
            if kwargs.get("container") == "prepare":
                cancel(h)
            return value

        monkeypatch.setattr(h.cluster, "logs", logs)
    with pytest.raises(ExecutorError, match=r"^operation_cancelled$"):
        phase(h)
    assert h.clock.time() == h.start + h.succeeds_at
    no_progress(h)
    assert h.platform.resource(h.plan.resource_ref)["stop_state"] == "held"


def test_cancel_during_scratch_setup_prevents_pod_creation(preparation, monkeypatch):
    """F059 覆盖 AC: AC-43、AC-52、AC-55."""
    h = preparation
    original = h.cluster.create

    def create(resource, document):
        answer = original(resource, document)
        if resource == "persistentvolumeclaims":
            cancel(h)
        return answer

    monkeypatch.setattr(h.cluster, "create", create)
    with pytest.raises(ExecutorError, match=r"^operation_cancelled$"):
        phase(h)
    row = h.platform.resource(h.plan.resource_ref)
    assert row["uid"] is None and row["observed_state"]["creation"]["state"] == "unattempted"
    assert not any(kind == "pods" for kind, _ in h.cluster.objects)
    no_progress(h)


def test_normal_phase_persists_result_then_confirms_same_uid_stop_and_reuses_it(preparation):
    """F059 覆盖 AC: AC-43、AC-48、AC-49、AC-52、AC-55."""
    h = preparation
    assert phase(h) == {"installed": True}
    row = h.platform.resource(h.plan.resource_ref)
    assert row["uid"] and row["stop_state"] == "confirmed"
    assert row["stop_evidence"]["uid"] == row["uid"] and row["stop_evidence"]["node_name"] == "worker-a"
    saved = h.platform.operation(h.operation["operation_id"])["result"]["prepare_progress"]["install"]
    assert saved == {"exec_ref": row["resource_ref"], "result": {"installed": True}}
    assert ("pods", row["name"]) not in h.cluster.objects
    before = copy.deepcopy(h.platform.rows)
    assert phase(h) == saved["result"] and h.platform.rows == before
    assert h.clock.time() == h.start + h.succeeds_at
