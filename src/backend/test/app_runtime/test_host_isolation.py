"""Node-wide evidence is not a heartbeat. 覆盖 AC: AC-66, AC-67, AC-68, AC-69."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


@pytest.fixture
async def host_env(runtime_repo, monkeypatch):
    from bisheng.app_runtime.domain.models.runtime_host_isolation import RuntimeHostIsolationReport
    from bisheng.app_runtime.domain.repositories.host_isolation_repository import REQUIRED, HostIsolationRepository

    async with runtime_repo.transaction() as session:
        row = await session.get(RuntimeHostIsolationReport, "node-a")
        await session.delete(row)
    repository = HostIsolationRepository(runtime_repo._factory)
    identity = SimpleNamespace(node_id="node-a", roles=("host-isolation",))
    from bisheng.app_runtime.domain.services.runtime_protocol import content_digest
    from bisheng.common.services.config_service import settings

    descriptor = {"node_id": "node-a"}
    expected = {
        "engine_id": "engine-a",
        "network_id": "network-a",
        "config_digest": content_digest(descriptor),
        "descriptor": descriptor,
    }
    monkeypatch.setattr(settings.app_runtime, "runtime_host_isolation_nodes", {"node-a": expected})
    body = {
        **{key: value for key, value in expected.items() if key != "descriptor"},
        "rule_digest": "b" * 64,
        "revision": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "valid",
        "checks": dict.fromkeys(REQUIRED, True),
    }
    return runtime_repo, repository, identity, expected, body


async def test_fresh_report_required_and_k8s_independent(host_env):
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

    repo, proof, identity, expected, body = host_env
    node = SimpleNamespace(id="node-a", engine_id="engine-a", executor_kind="docker")
    async with repo.transaction() as session:
        with pytest.raises(RuntimeConflict, match="unavailable"):
            await proof.require(session, node, expected)
        assert await proof.require(session, SimpleNamespace(executor_kind="kubernetes"), None) is None
    await proof.accept(identity, body, expected)
    async with repo.transaction() as session:
        assert (await proof.require(session, node, expected)).revision == 1
        with pytest.raises(RuntimeConflict):
            await proof.require(session, node, {**expected, "config_digest": "c" * 64})


async def test_replay_stale_and_false_canary_refused(host_env):
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

    _, proof, identity, expected, body = host_env
    await proof.accept(identity, body, expected)
    with pytest.raises(RuntimeConflict, match="revision"):
        await proof.accept(identity, body, expected)
    body["revision"] = 2
    body["checks"] = {**body["checks"], "egress_allowed": False}
    with pytest.raises(RuntimeConflict, match="incomplete"):
        await proof.accept(identity, body, expected)
    body["checked_at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    with pytest.raises(RuntimeConflict, match="stale"):
        await proof.accept(identity, body, expected)


async def test_heartbeat_cannot_refresh_host_proof_and_report_restores_readiness(host_env):
    """覆盖 AC: AC-69. A forged manager boolean is not a host canary result."""
    from bisheng.app_runtime.api.endpoints.runtime_delivery import Heartbeat
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeNode
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    repo, proof, identity, expected, body = host_env
    service = RuntimeOperationService(repo)
    heartbeat = Heartbeat(
        engine_id="engine-a",
        platform="linux/arm64",
        memory_budget_mb=1024,
        cpu_budget_millicores=2000,
        capabilities={"host_isolation_ready": True},
    )
    manager = SimpleNamespace(node_id="node-a", roles=("manager",))
    await service.heartbeat(manager, heartbeat)
    assert (await repo.get(RuntimeNode, "node-a")).status == "blocked"
    await proof.accept(identity, body, expected)
    await service.heartbeat(manager, heartbeat)
    assert (await repo.get(RuntimeNode, "node-a")).status == "ready"


async def test_host_report_api_rejects_manager_role(host_env, monkeypatch):
    """覆盖 AC: AC-69. Separate HMAC identities reach the real report endpoint."""
    import secrets

    import httpx
    from fastapi import FastAPI

    from bisheng.app_runtime.api.endpoints import runtime_delivery
    from bisheng.app_runtime.api.endpoints.host_isolation import router
    from bisheng.app_runtime.domain.repositories.host_isolation_repository import HostIsolationRepository
    from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json, signed_headers
    from bisheng.common.services.config_service import settings

    repo, _, _, _, body = host_env
    secret = secrets.token_hex(32)
    monkeypatch.setattr(settings.app_runtime, "enabled", True)
    monkeypatch.setattr(
        settings.app_runtime,
        "runtime_service_keys",
        {
            "manager": {"roles": ["manager"], "node_id": "node-a", "secret": secret},
            "host": {"roles": ["host-isolation"], "node_id": "node-a", "secret": secret},
        },
    )

    async def nonce(*args):
        return True

    monkeypatch.setattr(runtime_delivery, "consume_runtime_nonce", nonce)
    original = HostIsolationRepository.__init__
    monkeypatch.setattr(HostIsolationRepository, "__init__", lambda self: original(self, repo._factory))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    raw = canonical_json(body)
    url = "/api/v1/internal/app-runtime/host-isolation-reports"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = signed_headers("POST", url, raw, key_id="manager", secret=secret)
        headers["Content-Type"] = "application/json"
        denied = await client.post(url, content=raw, headers=headers)
        assert denied.status_code == 403
        headers = signed_headers("POST", url, raw, key_id="host", secret=secret)
        headers["Content-Type"] = "application/json"
        allowed = await client.post(url, content=raw, headers=headers)
        assert allowed.status_code == 200
        assert allowed.json()["node_id"] == "node-a"
