"""Manual same-version rebuild. 覆盖 AC: AC-70, AC-74, AC-75, AC-76, AC-77, AC-86, AC-90, AC-91, AC-92."""

import pytest

from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo
from test.app_runtime.test_secret_runtime_snapshot import secret_runtime as secret_runtime


def actor():
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(user_id=7, user_name="owner", user_role=[], tenant_id=1)


def confirmation(**updates):
    from bisheng.app_publish.domain.schemas.app_secrets import SecretRebuildInput

    return SecretRebuildInput(
        **{
            "request_id": "confirm-1",
            "expected_version_id": "v1",
            "expected_config_revision": 0,
            "expected_route_epoch": 3,
            "confirm_restart": True,
            **updates,
        }
    )


async def test_rebuild_reuses_delivery_tier_and_pending_and_replays_original_confirmation(secret_runtime, monkeypatch):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation
    from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
    from bisheng.app_runtime.domain.services.runtime_payload import unseal
    from bisheng.app_runtime.domain.services.secret_rebuild_service import AppSecretRebuildService
    from bisheng.common.errcode.app_publish import AppSecretRebuildConflictError

    repo, app, _ = secret_runtime
    wakes = []

    async def wake(self, op):
        wakes.append(op.id)

    monkeypatch.setattr(RuntimeDeliveryCoordinator, "wake", wake)
    service = AppSecretRebuildService(repository=repo)
    result = await service.rebuild_current(app.id, request=confirmation(), actor=actor())
    op = await repo.get(RuntimeOperation, result["operation_id"])
    assert op.payload["purpose"] == "config_restart" and op.payload["auto_commit"]
    assert op.payload["migration_plan"] == [] and op.payload["preserve_pending_version"]
    assert op.payload["tier"] == {"memory_mb": 128, "cpu_millicores": 100}
    assert unseal(op.payload["sealed_env"])["API_KEY"] == ""
    assert app.pending_version_id == "pending-v2" and len(wakes) == 1
    assert (await service.rebuild_current(app.id, request=confirmation(), actor=actor()))["operation_id"] == op.id
    with pytest.raises(AppSecretRebuildConflictError):
        await service.rebuild_current(app.id, request=confirmation(expected_config_revision=1), actor=actor())


async def test_unconfirmed_revision_or_wrong_owner_creates_no_operation(secret_runtime):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation
    from bisheng.app_runtime.domain.services.secret_rebuild_service import AppSecretRebuildService
    from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError, AppSecretRebuildConflictError

    repo, app, _ = secret_runtime
    service = AppSecretRebuildService(repository=repo)
    with pytest.raises(AppSecretRebuildConflictError):
        await service.rebuild_current(app.id, request=confirmation(expected_route_epoch=2), actor=actor())
    other = actor().model_copy(update={"user_id": 8, "is_global_super": True})
    with pytest.raises(AppPublishOwnerOnlyError):
        await service.rebuild_current(app.id, request=confirmation(), actor=other)
    assert len(await repo.find(RuntimeOperation, app_id=app.id)) == 1


async def test_maintenance_transition_is_precise_and_idempotent(secret_runtime, monkeypatch):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation, RuntimeRoute
    from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
    from bisheng.app_runtime.domain.services.runtime_projection_service import RuntimeProjectionService
    from bisheng.app_runtime.domain.services.secret_rebuild_service import AppSecretRebuildService

    repo, app, _ = secret_runtime

    async def wake(self, op):
        return None

    monkeypatch.setattr(RuntimeDeliveryCoordinator, "wake", wake)
    result = await AppSecretRebuildService(repository=repo).rebuild_current(
        app.id, request=confirmation(), actor=actor()
    )
    op = await repo.get(RuntimeOperation, result["operation_id"])
    projection = RuntimeProjectionService(repo)
    await projection.block_for_config_restart(op, sequence=1)
    route = (await repo.find(RuntimeRoute, app_id=app.id))[0]
    assert route.status == "maintenance" and route.route_epoch == 4
    await projection.block_for_config_restart(op, sequence=1)
    assert (await repo.find(RuntimeRoute, app_id=app.id))[0].route_epoch == 4


async def test_ready_fact_commits_rebuild_without_consuming_pending_version(secret_runtime, monkeypatch):
    from types import SimpleNamespace

    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation, RuntimeRoute
    from bisheng.app_runtime.domain.schemas.runtime_delivery import ExecutionFactInput
    from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService
    from bisheng.app_runtime.domain.services.secret_rebuild_service import AppSecretRebuildService
    from bisheng.database.models.app import App
    from bisheng.database.models.app_version import AppVersion

    repo, app, _ = secret_runtime

    async def wake(self, op):
        return None

    monkeypatch.setattr(RuntimeDeliveryCoordinator, "wake", wake)
    result = await AppSecretRebuildService(repository=repo).rebuild_current(
        app.id, request=confirmation(), actor=actor()
    )
    service = RuntimeOperationService(repo)
    op = await repo.get(RuntimeOperation, result["operation_id"])
    identity = SimpleNamespace(node_id="node-a", key_id="manager")
    await service.fact(
        op,
        identity,
        ExecutionFactInput(
            sequence=1, node_id="node-a", generation=op.generation, owner_epoch=op.owner_epoch, phase="maintenance"
        ),
    )
    ready = ExecutionFactInput(
        sequence=2,
        node_id="node-a",
        generation=op.generation,
        owner_epoch=op.owner_epoch,
        phase="ready",
        exec_ref="new-instance",
        detail={"exec_ref": "new-instance", "target": {"host": "172.20.0.3", "port": 8080}, "writers_stopped": True},
    )
    await service.fact(op, identity, ready)
    await service.fact(op, identity, ready)
    current = await repo.get(App, app.id)
    assert (
        current.current_version_id == "v1" and current.pending_version_id == "pending-v2" and current.state == "online"
    )
    assert (await repo.get(AppVersion, "v1")).terminal_state == "online"
    route = (await repo.find(RuntimeRoute, app_id=app.id))[0]
    assert route.operation_id == op.id and route.status == "serving" and route.exec_ref == "new-instance"


async def test_approval_preview_injects_names_with_empty_values(secret_runtime, monkeypatch):
    """AC-71: the real preview adapter passes declarations, without decrypting formal values."""
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation
    from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
    from bisheng.app_runtime.domain.services.runtime_payload import unseal

    repo, app, version = secret_runtime
    coordinator = RuntimeDeliveryCoordinator(repo)

    async def wake(op):
        return None

    async def wait(op, **kwargs):
        return {"operation_id": op.id}

    monkeypatch.setattr(coordinator, "wake", wake)
    monkeypatch.setattr(coordinator, "wait", wait)
    result = await coordinator.preview_start(
        app,
        version,
        SimpleNamespace(id="preview-a", expires_at=datetime.utcnow() + timedelta(minutes=5)),
        {"base_path": "/preview/", "port": 8080, "health": {}, "tier": {"mem": 128, "cpu": 0.1}, "egress_domains": []},
    )
    op = await repo.get(RuntimeOperation, result["operation_id"])
    assert unseal(op.payload["sealed_env"])["API_KEY"] == ""


async def test_f113_frozen_owner_tenant_is_revalidated_before_config_restart(secret_runtime):
    """F113 覆盖 AC: AC-16、AC-34、AC-36; rejected rebuild creates no runtime operation."""
    from sqlmodel import select

    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation
    from bisheng.app_runtime.domain.services.secret_rebuild_service import AppSecretRebuildService
    from bisheng.common.errcode.open_api import ServiceAccountOwnerTenantMismatchError
    from bisheng.database.models.tenant import UserTenant

    repo, app, _ = secret_runtime
    async with repo.transaction() as session:
        membership = (await session.exec(select(UserTenant).where(UserTenant.user_id == 7))).one()
        membership.tenant_id = 2
        session.add(membership)
    with pytest.raises(ServiceAccountOwnerTenantMismatchError):
        await AppSecretRebuildService(repository=repo).rebuild_current(app.id, request=confirmation(), actor=actor())
    assert len(await repo.find(RuntimeOperation, app_id=app.id)) == 1
    assert app.current_version_id == "v1" and app.pending_version_id == "pending-v2"
