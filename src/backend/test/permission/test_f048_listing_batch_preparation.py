"""F116 bounded preparation and security gates for verified listing batches."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionFGAUnavailableError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
)
from bisheng.permission.application import business_authorization, sql_runtime
from bisheng.permission.application.business_authorization import batch_check_verified_business_actions
from bisheng.permission.application.sql_runtime import (
    HIGHER_CONSISTENCY,
    RECENT_CATALOG_MARKER,
    RECENT_MARKER_SENTINEL,
    RedisConsistencyMarker,
)
from test.permission.test_f048_permission_service import _actor, _service, _target


class BatchMarker:
    def __init__(self, *, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error

    async def consistency_for_batch(self, targets):
        self.calls.append(targets)
        if self.error:
            raise self.error
        return self.result


@pytest.mark.parametrize("action", ["edit", "visible"])
async def test_ac03_one_catalog_fence_marker_and_fga_call_per_100_targets(action):
    """AC-03: per-target Catalog/fence/Redis N+1 preparation is removed."""
    service, catalog, fence, _, fga, _, _ = _service()
    marker = BatchMarker()
    service._marker = marker
    targets = tuple(_target(str(i)) for i in range(100))
    if action == "visible":
        await service.batch_check_visible(_actor(), targets)
    else:
        await service.batch_check_actions(_actor(), targets, action)
    assert catalog.calls == (["ready", ("action", "workflow", "edit")] if action == "edit" else ["ready"])
    assert fence.calls == []
    assert len(fence.batch_calls) == len(marker.calls) == len(fga.batches) == 1
    assert len(fga.batches[0][0]) == 100


@pytest.mark.parametrize("marker_error", [RuntimeError("redis unavailable"), None])
async def test_ac04_marker_error_and_recent_changes_require_higher_consistency(marker_error):
    """AC-04: batch marker errors never relax consistency or grant permission."""
    service, _, _, _, fga, _, _ = _service()
    marker = BatchMarker(result=HIGHER_CONSISTENCY, error=marker_error)
    service._marker = marker
    assert await service.batch_check_actions(_actor(), (_target("allow"), _target("deny")), "edit") == (True, False)
    assert fga.batches[0][1] == HIGHER_CONSISTENCY


async def test_ac04_stale_projection_is_excluded_and_recoverable_projection_forces_higher():
    """AC-04: mixed healthy/stale/degraded targets retain individual fence results."""
    service, _, fence, _, fga, _, _ = _service()
    marker = BatchMarker()
    service._marker = marker
    fence.ensure_readable_batch = AsyncMock(return_value=(False, PermissionPublishNotReadyError(), True))
    result = await service.batch_check_actions(_actor(), (_target("allow"), _target("stale"), _target("deny")), "edit")
    assert result == (True, False, False)
    assert [check["object"] for check in fga.batches[0][0]] == ["workflow:allow", "workflow:deny"]
    assert fga.batches[0][1] == HIGHER_CONSISTENCY
    assert marker.calls == []  # the entire batch is already forced to higher


async def test_ac04_catalog_and_fence_failures_stop_before_openfga():
    """AC-04: unavailable actions and incomplete fence replies fail closed."""
    service, catalog, fence, _, fga, _, _ = _service()
    with pytest.raises(InvalidCatalogActionError):
        await service.batch_check_actions(_actor(), (_target(),), "download")
    assert fga.batches == []
    fence.ensure_readable_batch = AsyncMock(return_value=())
    with pytest.raises(PermissionProjectionFailedError):
        await service.batch_check_actions(_actor(), (_target(),), "edit")
    assert fga.batches == []
    catalog.ready = False
    with pytest.raises(PermissionPublishNotReadyError):
        await service.batch_check_actions(_actor(), (_target(),), "edit")


async def test_ac04_identity_shortcuts_and_foreign_tenant_skip_batch_io():
    """AC-04: existing identity shortcuts and ordinary tenant denials are retained."""
    service, catalog, fence, _, fga, _, _ = _service()
    service._marker = BatchMarker()
    assert await service.batch_check_actions(_actor(super_admin=True), (_target(),), "edit") == (True,)
    assert await service.batch_check_actions(_actor(), (_target(tenant_id=8),), "edit") == (False,)
    assert catalog.calls == fence.calls == fence.batch_calls == fga.batches == []


@pytest.mark.parametrize("action", ["edit", "manage_permission"])
async def test_ac03_verified_facade_chunks_and_never_resolves_ids_again(monkeypatch, action):
    """AC-03: already verified target batches stay bounded and aligned."""
    runtime = SimpleNamespace(
        batch_check_actions=AsyncMock(
            side_effect=lambda _actor, targets, _action: tuple(t.resource_id != "2" for t in targets)
        )
    )
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    targets = tuple(_target(str(i)) for i in range(201))
    result = await batch_check_verified_business_actions(
        actor=_actor(), targets=targets + targets[:1], actions=(action, action)
    )
    assert [len(call.args[1]) for call in runtime.batch_check_actions.await_args_list] == [100, 100, 1]
    assert result[("workflow", "1")] == {action}
    assert result[("workflow", "2")] == frozenset()


@pytest.mark.parametrize("error", [InvalidCatalogActionError(), PermissionFGAUnavailableError(), None])
async def test_ac04_verified_facade_disabled_action_vs_runtime_failure(monkeypatch, error):
    """AC-04: disabled actions are absent; runtime/incomplete failures propagate."""
    runtime = SimpleNamespace(batch_check_actions=AsyncMock(return_value=(), side_effect=error))
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    if isinstance(error, InvalidCatalogActionError):
        result = await batch_check_verified_business_actions(actor=_actor(), targets=(_target(),), actions=("edit",))
        assert result[("workflow", "42")] == frozenset()
    else:
        with pytest.raises(PermissionFGAUnavailableError if error else PermissionPublishNotReadyError):
            await batch_check_verified_business_actions(actor=_actor(), targets=(_target(),), actions=("edit",))


async def test_ac04_catalog_action_disabled_mid_list_discards_earlier_batches(monkeypatch):
    """AC-04: a disabled action cannot leave a partly authorized result."""
    runtime = SimpleNamespace(batch_check_actions=AsyncMock(side_effect=[(True,) * 100, InvalidCatalogActionError()]))
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    result = await batch_check_verified_business_actions(
        actor=_actor(), targets=tuple(_target(str(i)) for i in range(101)), actions=("edit",)
    )
    assert all(not actions for actions in result.values())


@pytest.mark.parametrize("scope", ["none", "catalog", "tenant", "type", "resource", "unrelated"])
async def test_ac03_redis_batch_marker_reads_sentinel_and_one_mget(monkeypatch, scope):
    """AC-03/04: missing values may be omitted; only any matching marker matters."""
    marker = RedisConsistencyMarker(window_seconds=30)
    values = {RECENT_MARKER_SENTINEL: "ready"}
    keys = {
        "catalog": RECENT_CATALOG_MARKER,
        "tenant": marker._tenant_key(7),
        "type": marker._resource_key(tenant_id=7, resource_type="workflow", resource_id=None),
        "resource": marker._resource_key(tenant_id=7, resource_type="workflow", resource_id="4"),
        "unrelated": marker._resource_key(tenant_id=8, resource_type="workflow", resource_id="4"),
    }
    if scope != "none":
        values[keys[scope]] = "changed"
    redis = SimpleNamespace(
        aget=AsyncMock(side_effect=values.get),
        amget=AsyncMock(side_effect=lambda requested: [values[key] for key in requested if key in values]),
    )
    monkeypatch.setattr(sql_runtime, "get_redis_client", AsyncMock(return_value=redis))
    targets = tuple(_target(str(i)) for i in range(100))
    result = await marker.consistency_for_batch(targets)
    assert result == (None if scope in {"none", "unrelated"} else HIGHER_CONSISTENCY)
    redis.aget.assert_awaited_once_with(RECENT_MARKER_SENTINEL)
    redis.amget.assert_awaited_once()
    assert len(redis.amget.await_args.args[0]) == 103  # catalog + tenant + type + 100 IDs


async def test_ac04_redis_sentinel_recovery_keeps_higher_consistency(monkeypatch):
    """AC-04: missing sentinel triggers recovery instead of accepting an empty MGET."""
    marker = RedisConsistencyMarker(window_seconds=30)
    marker._ensure_recovery_started = AsyncMock()
    redis = SimpleNamespace(aget=AsyncMock(return_value=None), amget=AsyncMock())
    monkeypatch.setattr(sql_runtime, "get_redis_client", AsyncMock(return_value=redis))
    assert await marker.consistency_for_batch((_target(),)) == HIGHER_CONSISTENCY
    marker._ensure_recovery_started.assert_awaited_once_with(redis=redis)
    redis.amget.assert_not_awaited()
