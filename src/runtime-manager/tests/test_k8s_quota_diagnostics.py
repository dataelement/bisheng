"""Quota refusals retain bounded resource facts across the manager failure fact."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import certifi
import httpx
import pytest

from runtime_manager.config import Config
from runtime_manager.k8s_client import KubernetesAPIError, KubernetesClient
from runtime_manager.k8s_config import KubernetesConfig
from runtime_manager.operations import OperationExecutor
from tests.test_operations_v2 import Platform

QUOTA = {"limits.cpu": {"requested": "2", "used": "3", "limit": "4"}}


def refusal(message, **extra):
    return {"kind": "Status", "apiVersion": "v1", "reason": "Forbidden", "code": 403, "message": message, **extra}


def client(tmp_path, response):
    token = tmp_path / "token"
    token.write_text("fixture-private-token")
    settings = KubernetesConfig(
        namespace="bisheng-runtime-apps",
        cluster_id="cluster-a",
        descriptor_file=tmp_path / "descriptor.json",
        token_file=token,
        ca_file=Path(certifi.where()),
        api_server="https://cluster.invalid",
    )
    return KubernetesClient(settings, transport=httpx.MockTransport(lambda _: response), sleep=lambda _: None)


@pytest.mark.parametrize(
    "webhook", ["", 'admission webhook "resourcesquotas.quota.kubesphere.io" denied the request: ']
)
def test_native_and_webhook_quota_refusals_keep_only_quantities(tmp_path, webhook):
    message = (
        webhook
        + 'pods "private-pod" is forbidden: exceeded quota: private-name, requested: limits.cpu=2, used: limits.cpu=3, limited: limits.cpu=4'
    )
    api = client(tmp_path, httpx.Response(403, json=refusal(message, details={"token": "private-token"})))
    try:
        with pytest.raises(KubernetesAPIError, match=r"^k8s_quota_exceeded$") as caught:
            api.create("pods", {"metadata": {"name": "task-a"}})
        assert caught.value.status_code == 403 and caught.value.quota == QUOTA
        assert not any(word in str(vars(caught.value)) for word in ("private-name", "private-pod", "private-token"))
    finally:
        api.close()


@pytest.mark.parametrize(
    "status,body",
    [
        (403, refusal('pods "private" is forbidden: RBAC refused')),
        (403, refusal("quota service temporarily unavailable")),
        (
            403,
            refusal(
                "exceeded quota: q, requested: unknown.secret=1, used: unknown.secret=1, limited: unknown.secret=1"
            ),
        ),
        (
            403,
            refusal("exceeded quota: q, requested: limits.cpu=2, used: limits.cpu=3, limited: limits.cpu=credential"),
        ),
        (403, refusal("exceeded quota: q, requested: limits.cpu=2, used: limits.cpu=3")),
        (403, {"message": "exceeded quota: q, requested: limits.cpu=2, used: limits.cpu=3, limited: limits.cpu=4"}),
        (403, refusal("x" * 20000)),
        (422, refusal("exceeded quota: q, requested: limits.cpu=2, used: limits.cpu=3, limited: limits.cpu=4")),
    ],
)
def test_ordinary_forbidden_or_untrusted_body_is_not_capacity(tmp_path, status, body):
    api = client(tmp_path, httpx.Response(status, json=body))
    try:
        with pytest.raises(KubernetesAPIError, match=r"^k8s_api_refused$") as caught:
            api.create("pods", {"metadata": {"name": "task-a"}})
        assert caught.value.quota == {}
    finally:
        api.close()


def test_multiple_resources_and_zero_are_preserved_without_unknown_fields(tmp_path):
    text = "exceeded quota: q, requested: limits.cpu=0,limits.memory=512Mi,private.name=2, used: limits.cpu=4,limits.memory=1Gi,private.name=2, limited: limits.cpu=4,limits.memory=1Gi,private.name=2"
    api = client(tmp_path, httpx.Response(403, json=refusal(text)))
    try:
        with pytest.raises(KubernetesAPIError) as caught:
            api.create("pods", {"metadata": {"name": "task-a"}})
        assert caught.value.quota == {
            "limits.cpu": {"requested": "0", "used": "4", "limit": "4"},
            "limits.memory": {"requested": "512Mi", "used": "1Gi", "limit": "1Gi"},
        }
    finally:
        api.close()


def test_real_client_refusal_survives_manager_cleanup_and_terminal_retry(tmp_path):
    api = client(
        tmp_path,
        httpx.Response(
            403, json=refusal("exceeded quota: q, requested: limits.cpu=2, used: limits.cpu=3, limited: limits.cpu=4")
        ),
    )
    try:
        with pytest.raises(KubernetesAPIError) as caught:
            api.create("pods", {"metadata": {"name": "task-a"}})
    finally:
        api.close()
    platform = Platform("prepare")
    platform.op["stage"] = "preparing"
    logs = Mock(side_effect=AssertionError("No Pod exists; do not fabricate output"))
    runtime = SimpleNamespace(cleanup=lambda _: {"complete": False}, diagnostics=logs, _controller=lambda: {})
    executor = OperationExecutor(
        Config(data_root=tmp_path, executor_kind="kubernetes", protocol_version=2), platform, runtime=runtime
    )
    try:
        executor._failure(platform.op, None, caught.value)
        detail = platform.facts[-1][1]
        assert detail["reason"] == "k8s_quota_exceeded" and detail["quota"] == QUOTA
        assert detail["failed_stage"] == "preparing" and not detail["cleanup_complete"]
        assert not detail["diagnostic_tail"]
        logs.assert_not_called()
        platform.op["failure"]["quota"] = detail["quota"]
        executor._failure(platform.op, None, RuntimeError("later cleanup transport failure"))
        assert platform.facts[-1][1]["quota"] == QUOTA
        assert platform.facts[-1][1]["reason"] == "k8s_quota_exceeded"
    finally:
        executor.close()
