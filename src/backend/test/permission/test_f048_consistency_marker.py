"""F048 Redis marker fail-closed and scope contracts."""

from __future__ import annotations

import asyncio

import pytest

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.application import sql_runtime
from bisheng.permission.application.sql_runtime import (
    HIGHER_CONSISTENCY,
    RECENT_CATALOG_MARKER,
    RECENT_MARKER_SENTINEL,
    RedisConsistencyMarker,
    SqlProjectionFinalizer,
    SqlProjectionScopeGuard,
)
from bisheng.permission.domain.services.projection_plan import ProjectionPlan


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def aget(self, key: str):
        return self.values.get(key)

    async def aset(
        self,
        key: str,
        value: object,
        expiration: int = 3600,
    ) -> None:
        del expiration
        self.values[key] = value

    async def asetNx(
        self,
        key: str,
        value: object,
        expiration: int = 3600,
    ) -> bool:
        del expiration
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def adelete(self, key: str) -> None:
        self.values.pop(key, None)


class _ExternalScope:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.current = True

    async def reserve(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None:
        self.calls.append(("reserve", plan.scope_key, operation_id))

    async def is_expected_version(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> bool:
        self.calls.append(("current", plan.scope_key, operation_id))
        return self.current

    async def fail_closed(
        self,
        plan: ProjectionPlan,
        reason: str,
    ) -> None:
        self.calls.append(("failed", plan.scope_key, reason))

    async def finalize(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None:
        self.calls.append(("finalize", plan.scope_key, operation_id))


def _plan(
    *,
    scope_type: str,
    scope_key: str,
) -> ProjectionPlan:
    return ProjectionPlan(
        tenant_id=5,
        idempotency_key=f"{scope_type}:{scope_key}:v2",
        operation_type="TEST",
        scope_type=scope_type,
        scope_key=scope_key,
        expected_version=1,
        target_version=2,
        store_id="store",
        model_id="model",
        operator_id=7,
        change_item_count=1,
        deltas=(),
    )


@pytest.fixture
def redis(monkeypatch) -> _Redis:
    instance = _Redis()

    async def get_redis():
        return instance

    monkeypatch.setattr(sql_runtime, "get_redis_client", get_redis)
    return instance


@pytest.mark.asyncio
async def test_missing_sentinel_forces_higher_and_rejects_writes_until_recovered(
    redis: _Redis,
) -> None:
    marker = RedisConsistencyMarker(
        window_seconds=1,
        recovery_wait_seconds=0,
    )

    await marker.initialize()
    assert (
        await marker.consistency_for(
            tenant_id=5,
            resource_type="workflow",
            resource_id="9",
        )
        == HIGHER_CONSISTENCY
    )
    with pytest.raises(PermissionPublishNotReadyError):
        await marker.arm(_plan(scope_type="resource", scope_key="workflow:9"))

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert redis.values[RECENT_MARKER_SENTINEL] == "ready"


@pytest.mark.asyncio
async def test_wait_until_ready_observes_sentinel_recovery(redis: _Redis) -> None:
    marker = RedisConsistencyMarker(
        window_seconds=1,
        recovery_wait_seconds=0,
    )

    await marker.wait_until_ready(timeout_seconds=1)

    assert redis.values[RECENT_MARKER_SENTINEL] == "ready"


@pytest.mark.asyncio
async def test_department_marker_forces_higher_for_the_entire_tenant(
    redis: _Redis,
) -> None:
    redis.values[RECENT_MARKER_SENTINEL] = "ready"
    marker = RedisConsistencyMarker(window_seconds=35)

    await marker.arm(_plan(scope_type="department", scope_key="17"))

    assert (
        await marker.consistency_for(
            tenant_id=5,
            resource_type="workflow",
            resource_id="9",
        )
        == HIGHER_CONSISTENCY
    )
    assert (
        await marker.consistency_for(
            tenant_id=6,
            resource_type="workflow",
            resource_id="9",
        )
        is None
    )


@pytest.mark.asyncio
async def test_resource_marker_covers_check_and_bounded_list_scope(
    redis: _Redis,
) -> None:
    redis.values[RECENT_MARKER_SENTINEL] = "ready"
    marker = RedisConsistencyMarker(window_seconds=35)

    await marker.arm(_plan(scope_type="resource", scope_key="knowledge_file:91"))

    assert (
        await marker.consistency_for(
            tenant_id=5,
            resource_type="knowledge_file",
            resource_id="91",
        )
        == HIGHER_CONSISTENCY
    )
    assert (
        await marker.consistency_for(
            tenant_id=5,
            resource_type="knowledge_file",
            resource_id=None,
        )
        == HIGHER_CONSISTENCY
    )
    assert (
        await marker.consistency_for(
            tenant_id=5,
            resource_type="workflow",
            resource_id="91",
        )
        is None
    )


@pytest.mark.asyncio
async def test_catalog_marker_forces_higher_globally(redis: _Redis) -> None:
    redis.values[RECENT_MARKER_SENTINEL] = "ready"
    redis.values[RECENT_CATALOG_MARKER] = "catalog-v2"
    marker = RedisConsistencyMarker(window_seconds=35)

    assert (
        await marker.consistency_for(
            tenant_id=999,
            resource_type="dashboard",
            resource_id="42",
        )
        == HIGHER_CONSISTENCY
    )


@pytest.mark.asyncio
async def test_department_scope_uses_injected_business_state_delegate() -> None:
    department = _ExternalScope()
    scopes = {"department": department}
    guard = SqlProjectionScopeGuard(external_scopes=scopes)
    finalizer = SqlProjectionFinalizer(external_scopes=scopes)
    plan = _plan(scope_type="department", scope_key="17")

    await guard.reserve(plan, 81)
    assert await guard.is_expected_version(plan, 81) is True
    await guard.fail_closed(plan, "uncertain commit")
    await finalizer.finalize(plan, 81)

    assert department.calls == [
        ("reserve", "17", 81),
        ("current", "17", 81),
        ("failed", "17", "uncertain commit"),
        ("finalize", "17", 81),
    ]


@pytest.mark.asyncio
async def test_unconfigured_external_scope_fails_closed() -> None:
    guard = SqlProjectionScopeGuard()
    plan = _plan(scope_type="department", scope_key="17")

    with pytest.raises(PermissionPublishNotReadyError):
        await guard.reserve(plan, 81)
