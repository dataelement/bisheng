"""Regression for wildcard domains accepted by publishing but rejected on startup."""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeEgressPolicy
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_egress_service import RuntimeEgressService, destination
from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService
from bisheng.common.services.config_service import settings
from test.app_runtime.test_runtime_delivery_repository import operation
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


@pytest.mark.parametrize("domain", ["*.hdslb.com", "*.qpic.cn", "*.video.qq.com", "*.xhscdn.com"])
def test_declared_wildcard_domains_use_the_proxy_zone_representation(domain):
    assert destination(domain) == {"host": domain[1:], "ports": [443], "trusted": False}


@pytest.mark.parametrize(
    ("value", "host", "port"),
    [
        ("https://*.Example.COM:8443/path", ".example.com", 8443),
        ("http://*.example.com", ".example.com", 80),
        (".example.com", ".example.com", 443),
        ("api.example.com", "api.example.com", 443),
    ],
)
def test_wildcard_normalization_preserves_ports_and_exact_host_scope(value, host, port):
    assert destination(value) == {"host": host, "ports": [port], "trusted": False}


@pytest.mark.parametrize("value", ["*", "*.", "*..example.com", "api.*.example.com", "*example.com"])
def test_unbounded_and_malformed_wildcards_remain_rejected(value):
    with pytest.raises(RuntimeConflict, match=r"^egress_destination_invalid$"):
        destination(value)


def test_declared_wildcard_url_cannot_supply_proxy_credentials():
    with pytest.raises(RuntimeConflict, match=r"^egress_destination_invalid$"):
        destination("https://user:fixture@*.example.com")


async def test_wildcard_declaration_is_persisted_and_projected_as_an_untrusted_zone(runtime_repo, monkeypatch):
    from bisheng.app_runtime.domain.models.runtime_kubernetes import KUBERNETES_TABLES

    # The shared egress projection also queries material grants, even when empty.
    async with runtime_repo.transaction() as session:
        connection = await session.connection()
        for model in KUBERNETES_TABLES:
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn, checkfirst=True))
    monkeypatch.setattr(settings.app_runtime, "runtime_payload_key", Fernet.generate_key().decode())
    op = await runtime_repo.create_operation(operation())
    await runtime_repo.claim(op.id, node_id=op.node_id, generation=1, owner_epoch=1)
    service = RuntimeEgressService(runtime_repo)
    credentials = await service.issue(op, phase="runtime", declared=["*.example.com", "api.other.example"])
    assert await service.issue(op, phase="runtime", declared=["*.example.com", "api.other.example"]) == credentials
    policies = await runtime_repo.find(RuntimeEgressPolicy, operation_id=op.id)
    assert len(policies) == 1
    assert policies[0].destinations == [
        {"host": ".example.com", "ports": [443], "trusted": False},
        {"host": "api.other.example", "ports": [443], "trusted": False},
    ]
    projected = await RuntimeOperationService(runtime_repo).policies(
        SimpleNamespace(node_id=op.node_id, roles=("egress",))
    )
    assert projected["policies"][0]["destinations"] == policies[0].destinations
    assert credentials["token"] not in str(projected)
