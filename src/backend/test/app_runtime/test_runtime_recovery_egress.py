"""Automatic recovery must keep the application's declared egress domains."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

from bisheng.app_runtime.domain.services.app_state_service import AppStateService
from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest


class _Repo:
    def __init__(self, app, previous, route):
        self.app = app
        self.previous = previous
        self.route = route

    async def get_application(self, app_id):
        return self.app

    async def find(self, model, **_):
        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeAssignment

        if model is RuntimeAssignment:
            return [SimpleNamespace(active_operation_id=self.previous.id, data_operation_id="")]
        return []

    async def get(self, model, key, lock=False):
        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeRoute

        if model is RuntimeRoute:
            return self.route
        return self.previous if key == self.previous.id else self.app

    @asynccontextmanager
    async def transaction(self):
        yield


async def test_recovery_deploy_carries_declared_egress_domains(monkeypatch):
    """A recovered runtime gets a fresh egress policy; dropping the declaration cut the app off."""
    app = SimpleNamespace(
        id="app-a",
        tenant_id=1,
        slug="monitor",
        state="online",
        current_version_id="v1",
        pending_version_id=None,
    )
    delivery_content = {"mode": "bundle"}
    previous = SimpleNamespace(
        id="op-1",
        tenant_id=1,
        app_id="app-a",
        version_id="v1",
        kind="deploy",
        request_digest="a" * 64,
        status="completed",
        cleanup_status="complete",
        payload={"resolved_delivery": delivery_content, "recovery_attempt": 3},
    )
    route = SimpleNamespace(
        id="r1",
        tenant_id=1,
        app_id="app-a",
        operation_id="op-1",
        version_id="v1",
        node_id="node-a",
        exec_ref="exec-a",
        generation=1,
        owner_epoch=1,
        route_epoch=1,
        status="serving",
    )
    version = SimpleNamespace(
        id="v1",
        version_no=1,
        tier_id=None,
        capabilities=[],
        injections={},
        manifest={"port": 8080, "egress": {"domains": ["www.dshdesktop.cn", "api.github.com"]}},
    )

    async def load_version(app_id, version_id):
        return version

    async def resolve_tier(tier_id):
        return {"cpu": 1, "mem": 1024}

    monkeypatch.setattr(AppStateService, "_load_version", staticmethod(load_version))
    monkeypatch.setattr(AppStateService, "_resolve_tier", staticmethod(resolve_tier))

    coordinator = RuntimeDeliveryCoordinator(_Repo(app, previous, route))
    submitted = {}

    async def delivery(app_id, version_id):
        return SimpleNamespace(content=delivery_content, delivery_digest=content_digest(delivery_content))

    async def submit(app, *, kind, key, version_id="", payload=None):
        submitted.update(payload)
        return SimpleNamespace(id="op-2")

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(coordinator, "delivery", delivery)
    monkeypatch.setattr(coordinator, "submit", submit)
    monkeypatch.setattr(coordinator, "inject_environment", noop)
    monkeypatch.setattr(coordinator, "wake", noop)

    await coordinator.recover(
        app,
        route,
        running=True,
        observation={
            "key_id": "manager",
            "node_id": "node-a",
            "operation_id": "op-1",
            "exec_ref": "exec-a",
            "generation": 1,
            "owner_epoch": 1,
            "route_epoch": 1,
        },
    )

    # A healthy serving interval starts a new fault window, even if the serving
    # operation was itself the third attempt of an older recovery window.
    assert submitted["recovery_attempt"] == 1
    assert submitted["egress_domains"] == ["www.dshdesktop.cn", "api.github.com"]
