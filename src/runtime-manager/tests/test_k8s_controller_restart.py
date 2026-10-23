"""F059 controller admission must precede operation failure handling.

覆盖 AC: AC-43、AC-48、AC-49、AC-52、AC-55。

Uses real OperationExecutor/KubernetesExecutor and existing in-memory platform/cluster
fixtures. It does not claim MySQL locking, real kubelet restart or native Node proof.
"""

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime_manager.executors.kubernetes import KubernetesExecutor, _ref
from runtime_manager.k8s_templates import pod_template
from runtime_manager.operations import OperationExecutor
from runtime_manager.platform_client import PlatformError
from tests.test_kubernetes_executor import runtime as runtime


@pytest.fixture
def live_prepare(runtime, monkeypatch):
    old, platform, cluster, op, events, clock = runtime
    op.update(kind="prepare", stage="preparing", cleanup_status="pending")
    op["payload"]["profile"] = op["payload"].pop("resolved_delivery")["profile"]
    op["payload"].update(source_artifact_id="source-a", delivery={"mode": "bundle", "dependencies": {}})
    document = {
        key: copy.deepcopy(op["payload"][key]) for key in ("tenant_id", "source_artifact_id", "profile", "delivery")
    }
    document.update(app_id=op["app_id"], offline=True, package_environment={})
    old._phase(op, "inputs", "prepare-download", {**document, "phase": "inputs"})
    platform.dependencies(op["operation_id"], "c" * 64)
    document["dependency_resolution"] = copy.deepcopy(op["payload"]["dependency_resolution"])
    old._phase(op, "resolve", "prepare-download", {**document, "phase": "resolve"})
    reference = _ref(op, "prepare-install", "install")
    plan = old._plan(
        op, "prepare-install", reference=reference, image=op["payload"]["profile"]["preparer_image"], deadline=1800
    )
    plan = replace(
        plan,
        command=("python", "-I", "/runtime/tools/k8s_prepare.py"),
        prepare_environment=False,
        material_secret="",
        app_secret="",
        secret_env=(),
    )
    template = pod_template(plan)
    row = old._intent(op, plan, template, reference)
    old._volume(op, plan)
    body = old._create(row, template)
    key = ("pods", body["metadata"]["name"])
    cluster.objects[key]["status"]["phase"] = "Running"
    for item in cluster.objects[key]["status"]["containerStatuses"]:
        item["state"] = {"running": {"startedAt": clock.iso()}}
    claims, original_fact = [], platform.fact
    monkeypatch.setattr(platform, "claim", lambda ident: claims.append(ident), raising=False)

    def fact(operation, sequence, phase, *, exec_ref="", detail=None):
        original_fact(operation, sequence, phase, exec_ref=exec_ref, detail=detail)
        target = platform.operations[operation["operation_id"]]
        target["stage"] = phase
        if phase in {"completed", "failed", "cancelled", "timed_out"}:
            target.update(status=phase, cleanup_status="complete" if detail.get("cleanup_complete") else "pending")
            target["failure"] = {key: detail[key] for key in ("reason", "failed_stage") if key in detail}
        return copy.deepcopy(target)

    monkeypatch.setattr(platform, "fact", fact)
    case = SimpleNamespace(
        old=old,
        platform=platform,
        cluster=cluster,
        op=op,
        events=events,
        clock=clock,
        reference=reference,
        key=key,
        uid=body["metadata"]["uid"],
        claims=claims,
        runners=[],
    )
    yield case
    for runner in case.runners:
        runner.close()


def runner_for(case, *, reuse_current=False):
    runtime = (
        case.old
        if reuse_current
        else KubernetesExecutor(
            case.old.config, case.old.settings, platform=case.platform, client=case.cluster, clock=case.clock
        )
    )
    runner = OperationExecutor(case.old.config, case.platform, clock=case.clock, runtime=runtime)
    case.runners.append(runner)
    return runner


def finish_existing_install(case):
    case.cluster.objects[case.key]["status"]["phase"] = "Succeeded"
    for item in case.cluster.objects[case.key]["status"]["containerStatuses"]:
        item["state"] = {"terminated": {"exitCode": 0}}


@pytest.mark.parametrize("held_reply_crosses_expiry", [False, True])
def test_held_controller_never_claims_operation_or_fails_existing_install_and_next_pass_resumes(
    live_prepare, monkeypatch, held_reply_crosses_expiry
):
    case = live_prepare
    claim_controller = case.platform.claim_controller
    original_deadline = case.op["deadline"]
    original_epoch = case.platform.epoch
    before = copy.deepcopy((case.platform.rows, case.cluster.objects, case.platform.operation(case.op["operation_id"])))

    def delayed_reply(holder_id, expected_epoch):
        try:
            return claim_controller(holder_id, expected_epoch)
        except PlatformError as exc:
            if str(exc) == "controller_lease_held" and held_reply_crosses_expiry:
                # The server rejected while live; only its response latency crosses natural expiry.
                case.clock.sleep(case.platform.lease_until - case.clock.value + 1)
            raise

    monkeypatch.setattr(case.platform, "claim_controller", delayed_reply)
    runner = runner_for(case)
    with pytest.raises(PlatformError, match=r"^controller_lease_held$") as error:
        runner.execute(case.op["operation_id"])
    assert error.value.status == 409
    assert case.claims == []
    assert (case.platform.rows, case.cluster.objects, case.platform.operation(case.op["operation_id"])) == before
    assert case.platform.epoch == original_epoch
    if not held_reply_crosses_expiry:
        case.clock.sleep(31)
    finish_existing_install(case)
    runner.execute(case.op["operation_id"])
    saved = case.platform.operation(case.op["operation_id"])
    assert saved["status"] == "completed" and saved["cleanup_status"] == "complete"
    assert saved["deadline"] == original_deadline
    assert case.platform.epoch == original_epoch + 1
    assert case.platform.resource(case.reference)["uid"] == case.uid
    assert saved["result"]["prepare_progress"]["inputs"] == before[2]["result"]["prepare_progress"]["inputs"]
    assert saved["result"]["prepare_progress"]["resolve"] == before[2]["result"]["prepare_progress"]["resolve"]
    assert len([event for event in case.events if event[:2] == ("create", "pods")]) == 4
    assert case.claims == [case.op["operation_id"]]


def test_current_valid_controller_continues_prepare_without_new_epoch(live_prepare):
    case = live_prepare
    finish_existing_install(case)
    original_epoch, original_holder, deadline = case.platform.epoch, case.platform.holder, case.op["deadline"]
    runner_for(case, reuse_current=True).execute(case.op["operation_id"])
    assert (case.platform.epoch, case.platform.holder) == (original_epoch, original_holder)
    assert case.platform.operation(case.op["operation_id"])["status"] == "completed"
    assert case.platform.operation(case.op["operation_id"])["deadline"] == deadline


@pytest.mark.parametrize("reason,status", [("controller_epoch_conflict", 409), ("platform_unreachable", 503)])
def test_other_controller_admission_errors_propagate_without_operation_failure(
    live_prepare, monkeypatch, reason, status
):
    case = live_prepare
    before = copy.deepcopy((case.platform.rows, case.cluster.objects, case.platform.operation(case.op["operation_id"])))

    def reject(*unused):
        raise PlatformError(reason, status)

    monkeypatch.setattr(case.platform, "claim_controller", reject)
    with pytest.raises(PlatformError, match="^" + reason + "$"):
        runner_for(case).execute(case.op["operation_id"])
    assert case.claims == []
    assert (case.platform.rows, case.cluster.objects, case.platform.operation(case.op["operation_id"])) == before


def test_non_controller_platform_business_failure_retains_original_failure_cleanup(live_prepare, monkeypatch):
    case = live_prepare
    runner = runner_for(case, reuse_current=True)

    def business_conflict(operation):
        raise PlatformError("resource_intent_conflict", 409)

    monkeypatch.setattr(runner.runtime, "prepare", business_conflict)
    runner.execute(case.op["operation_id"])
    saved = case.platform.operation(case.op["operation_id"])
    assert saved["status"] == "failed" and saved["failure"]["reason"] == "execution_failed"
    assert saved["cleanup_status"] == "complete" and case.cluster.objects.get(case.key) is None
    assert case.claims == [case.op["operation_id"]]


def test_docker_operation_keeps_its_existing_path(tmp_path):
    from runtime_manager.config import Config
    from tests.test_operations_v2 import Docker, Platform

    platform = Platform()
    executor = OperationExecutor(Config(data_root=tmp_path, node_id="node-a"), platform, Docker())
    try:
        executor.execute("operation-a")
    finally:
        executor.close()
    assert platform.facts == [("completed", {"stopped": True, "cleanup_complete": True})]
