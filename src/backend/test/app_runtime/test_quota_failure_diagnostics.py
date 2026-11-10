"""Capacity failures remain actionable after terminal persistence and publish mapping."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import certifi
import httpx
import pytest

from bisheng.app_publish.domain.schemas.failure import failure_from_error
from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation
from bisheng.app_runtime.domain.schemas.runtime_delivery import ExecutionFactInput
from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService
from bisheng.app_runtime.domain.services.runtime_public_diagnostics import runtime_failure_error
from test.app_runtime.test_runtime_delivery_repository import operation
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo

QUOTA = {"limits.cpu": {"requested": "2", "used": "3", "limit": "4"}}


@pytest.mark.parametrize("kind,code", [("prepare", 16226), ("probe", 16125), ("deploy", 16125)])
def test_quota_uses_existing_capacity_family_and_never_dependency_advice(kind, code):
    row = SimpleNamespace(
        id="op",
        kind=kind,
        status="failed",
        stage="failed",
        failure={"reason": "k8s_quota_exceeded", "failed_stage": "preparing", "quota": QUOTA},
    )
    error = runtime_failure_error(row)
    failure = failure_from_error(error, stage="precheck_build")
    assert failure["code"] == code
    assert failure["details"]["reason"] == "k8s_quota_exceeded"
    assert failure["details"]["quota"] == QUOTA
    assert "管理员" in " ".join(failure["hints"])
    assert "requirements.txt" not in " ".join(failure["hints"])


@pytest.mark.parametrize("reason", ["k8s_api_refused", "execution_failed", "preparation_phase_failed"])
def test_non_quota_failure_is_not_reclassified(reason):
    row = SimpleNamespace(id="op", kind="prepare", status="failed", stage="failed", failure={"reason": reason})
    error = runtime_failure_error(row)
    assert error.code == 16227 and "quota" not in error.kwargs["details"]


async def test_fact_persistence_and_publish_read_keep_only_quota_contract(runtime_repo):
    pending = operation()
    pending.kind = "prepare"
    op = await runtime_repo.create_operation(pending)
    identity = SimpleNamespace(node_id=op.node_id, key_id="manager")
    detail = {
        "reason": "k8s_quota_exceeded",
        "failed_stage": "preparing",
        "stopped": False,
        "cleanup_complete": False,
        "quota": {**QUOTA, "private-pod": {"requested": "credential", "used": "1", "limit": "4"}},
    }
    body = ExecutionFactInput(
        sequence=1,
        phase="failed",
        node_id=op.node_id,
        generation=op.generation,
        owner_epoch=op.owner_epoch,
        detail=detail,
    )
    await RuntimeOperationService(runtime_repo).fact(op, identity, body)
    saved = await runtime_repo.get(RuntimeOperation, op.id)
    assert saved.failure["quota"] == QUOTA and saved.failure["reason"] == "k8s_quota_exceeded"
    assert "private-pod" not in str(saved.failure)
    error = runtime_failure_error(saved)
    assert error.code == 16226 and error.kwargs["details"]["quota"] == QUOTA


def test_public_projection_revalidates_persisted_quota_values():
    row = SimpleNamespace(
        id="op",
        kind="prepare",
        status="failed",
        stage="failed",
        failure={
            "reason": "k8s_quota_exceeded",
            "quota": {"limits.cpu": {"requested": "secret", "used": "1", "limit": "4"}, "message": "private"},
        },
    )
    error = runtime_failure_error(row)
    assert "quota" not in error.kwargs["details"] and "secret" not in str(error.kwargs)


async def test_quota_response_flows_through_manager_fact_publish_and_cli(runtime_repo, monkeypatch, tmp_path):
    """Offline contract integration: the original 403 reaches the CLI as capacity."""
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "runtime-manager"))
    monkeypatch.syspath_prepend(str(root / "bisheng-cli"))
    from bisheng_cli.errors import EXIT_CAPACITY, error_from_platform, render_human
    from runtime_manager.config import Config
    from runtime_manager.k8s_client import KubernetesAPIError, KubernetesClient
    from runtime_manager.k8s_config import KubernetesConfig
    from runtime_manager.operations import OperationExecutor

    pending = operation("quota-contract")
    pending.kind = "prepare"
    op = await runtime_repo.create_operation(pending)
    document = {
        "operation_id": op.id,
        "app_id": op.app_id,
        "node_id": op.node_id,
        "kind": "prepare",
        "generation": op.generation,
        "owner_epoch": op.owner_epoch,
        "stage": "preparing",
        "status": "running",
        "deadline": op.deadline.isoformat(),
        "fact_sequence": 0,
        "payload": {},
    }
    facts = []

    def fact(_, sequence, phase, **kwargs):
        facts.append((sequence, phase, kwargs["detail"]))

    platform = SimpleNamespace(operation=lambda _: deepcopy(document), fact=fact)
    runtime = SimpleNamespace(cleanup=lambda _: {"complete": False}, _controller=lambda: {})
    executor = OperationExecutor(
        Config(data_root=tmp_path, executor_kind="kubernetes", protocol_version=2), platform, runtime=runtime
    )
    token = tmp_path / "token"
    token.write_text("fixture-private-token")
    settings = KubernetesConfig(
        namespace="bisheng-runtime-apps",
        cluster_id="cluster-a",
        descriptor_file=tmp_path / "descriptor",
        token_file=token,
        ca_file=Path(certifi.where()),
        api_server="https://cluster.invalid",
    )
    status = {
        "kind": "Status",
        "reason": "Forbidden",
        "code": 403,
        "message": 'pods "private-pod" is forbidden: exceeded quota: private-name, requested: limits.cpu=2, used: limits.cpu=3, limited: limits.cpu=4',
    }
    client = KubernetesClient(settings, transport=httpx.MockTransport(lambda _: httpx.Response(403, json=status)))
    try:
        with pytest.raises(KubernetesAPIError) as caught:
            client.create("pods", {"metadata": {"name": "task-a"}})
        executor._failure(document, None, caught.value)
    finally:
        client.close()
        executor.close()
    sequence, phase, detail = facts[0]
    await RuntimeOperationService(runtime_repo).fact(
        op,
        SimpleNamespace(node_id=op.node_id),
        ExecutionFactInput(
            sequence=sequence,
            phase=phase,
            node_id=op.node_id,
            generation=op.generation,
            owner_epoch=op.owner_epoch,
            detail=detail,
        ),
    )
    saved = await runtime_repo.get(RuntimeOperation, op.id)
    failure = failure_from_error(runtime_failure_error(saved), stage="precheck_build")
    cli = error_from_platform(failure["code"], failure["message"], details=failure["details"], hints=failure["hints"])
    text = render_human(cli)
    assert failure["code"] == 16226 and cli.exit_code == EXIT_CAPACITY
    assert "limits.cpu" in text and "本次申请 2" in text and "上限 4" in text
    assert not any(
        value in text
        for value in ("private-name", "private-pod", "fixture-private-token", "Execution observation unavailable")
    )
