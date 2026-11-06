"""Bootstrap creates tenant grants once and preserves later permission decisions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services import f048_system_resource_bootstrap as bootstrap
from bisheng.common.errcode.permission import (
    PermissionPublishNotReadyError,
)
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.permission.application import control_state, sql_runtime, system_resource_reconcile
from bisheng.permission.application.control_state import (
    RuntimeCatalogSnapshot,
    RuntimeModelSnapshot,
    SqlOwnerProjectionState,
    SqlPermissionControlState,
)
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.application.system_resource_reconcile import (
    SystemOwnedResourceSpec,
    reconcile_system_owned_resources,
)
from bisheng.permission.domain.models import (
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot, GrantSourceService
from bisheng.permission.domain.services.owner_service import F048OwnerProjectionService
from bisheng.permission.domain.services.projection_service import ProjectionService
from test.permission.test_f048_projection_service import FakeFGAProjection, FakeRecentMarker


def _spec(tenant_id=1, resource_id="902"):
    return SystemOwnedResourceSpec(
        tenant_id=tenant_id,
        resource_type="tool",
        resource_id=resource_id,
        action_codes=("use", "visible"),
        context_version=f"preset:{tenant_id}:{resource_id}",
    )


class _FGA(FakeFGAProjection):
    store_id = "store"
    model_id = "model"

    def __init__(self, factory):
        super().__init__(set())
        self.factory = factory
        self.reject_existing_writes = True
        self.reads = []
        self.extra_rows = []

    async def read_tuples(self, **kwargs):
        assert kwargs["consistency"] == "HIGHER_CONSISTENCY"
        self.reads.append((get_current_tenant_id(), kwargs))
        return [
            {"user": user, "relation": relation, "object": obj}
            for user, relation, obj in sorted(self.present)
            if user == kwargs["user"] and obj == kwargs["object"]
        ] + self.extra_rows

    async def write_atomic(self, *, writes, deletes):
        assert not any(row.relation == "system_use_marker" for row in writes)
        assert not any(row.relation == "visible" and row.user == "user:*" for row in writes)
        async with self.factory() as session:
            operation = (
                await session.exec(
                    select(PermissionProjectionOperation).order_by(PermissionProjectionOperation.id.desc())
                )
            ).first()
            assert operation.status in {"STAGING", "COMMIT_UNKNOWN"}
            ledger = (
                await session.exec(
                    select(PermissionProjectionTuple).where(PermissionProjectionTuple.operation_id == operation.id)
                )
            ).all()
            assert {row.key for row in writes} <= {(row.fga_user, row.relation, row.fga_object) for row in ledger}
        return await super().write_atomic(writes=writes, deletes=deletes)


@pytest.fixture
async def repair_env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    metadata = sa.MetaData()
    for name in (
        "authorization_model_release",
        "permission_catalog_release",
        "permission_projection_operation",
        "permission_projection_tuple",
        "permission_migration_run",
        "permission_migration_item",
        "resource_permission_mode",
        "permission_grant",
        "permission_grant_assignee",
        "permission_visible_source_projection",
        "t_gpts_tools_type",
    ):
        cloned = SQLModel.metadata.tables[name].to_metadata(metadata)
        cloned.c.id.type = sa.Integer()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    for module in (sql_runtime, control_state, system_resource_reconcile, bootstrap):
        monkeypatch.setattr(module, "get_async_db_session", factory)
    async with factory() as session:
        session.add(
            PermissionCatalogRelease(
                id=1,
                release_key="catalog",
                version=1,
                status="CURRENT",
                write_fenced=False,
                required_authorization_model_release_id=1,
                draft_owner_id=1,
                idempotency_key="catalog",
                checksum="c" * 64,
            )
        )
        await session.commit()
    state = SqlPermissionControlState()
    state.current_catalog = AsyncMock(
        return_value=RuntimeCatalogSnapshot(
            release_id=1,
            release_key="catalog",
            version=1,
            checksum="c" * 64,
            store_id="store",
            model_id="model",
            model_checksum="m" * 64,
            models=(
                RuntimeModelSnapshot(
                    snapshot=GrantModelSnapshot(
                        model_key="viewer", active=True, action_codes=("use",), derived_level=1
                    ),
                    name="Viewer",
                    kind="STANDARD",
                    version=1,
                ),
            ),
        )
    )
    repository = ProjectionRepository(session_factory=factory)
    marker = FakeRecentMarker()
    fga = _FGA(factory)
    projection = ProjectionService(
        repository=repository,
        marker=marker,
        scope_guard=sql_runtime.SqlProjectionScopeGuard(),
        fga=fga,
        finalizer=sql_runtime.SqlProjectionFinalizer(),
    )
    sources = GrantSourceService()
    owner = F048OwnerProjectionService(
        source_service=sources, projection=projection, state=SqlOwnerProjectionState(state)
    )
    runtime = F048PermissionRuntime(
        client=fga,
        state=state,
        marker=marker,
        decision=object(),
        projection=projection,
        sources=sources,
        owner=owner,
        grants=object(),
        modes=object(),
        explain=object(),
    )
    with tenant_execution_scope(1):
        try:
            yield SimpleNamespace(
                runtime=runtime, factory=factory, fga=fga, state=state, projection=projection, marker=marker
            )
        finally:
            await engine.dispose()


@pytest.mark.parametrize("resource_type", ["tool", "linsight_skill"])
async def test_fresh_bootstrap_creates_tenant_grant_and_restart_is_read_only(repair_env, resource_type):
    from dataclasses import replace

    env = repair_env
    spec = replace(_spec(), resource_type=resource_type)
    report = await reconcile_system_owned_resources(env.runtime, (spec,), apply=True, operator_id=1)
    assert report.missing_count == report.current_count == 1
    assert ("tenant:1#member", "visible", spec.object_key) in env.fga.present
    assert any(user == "tenant:1#member" and relation == "ordinary_assignee" for user, relation, _ in env.fga.present)
    async with env.factory() as session:
        operation = (await session.exec(select(PermissionProjectionOperation))).one()
        grant = (await session.exec(select(PermissionGrant))).one()
        source = (await session.exec(select(PermissionGrantAssignee))).one()
        mode = (await session.exec(select(ResourcePermissionMode))).one()
    assert operation.status == "FINALIZED"
    assert source.subject_type == "tenant" and source.subject_id == "1" and not source.protected
    assert grant.projection_state == mode.projection_state == "CURRENT"
    calls = len(env.fga.calls)
    await reconcile_system_owned_resources(env.runtime, (spec,), apply=True, operator_id=1)
    assert len(env.fga.calls) == calls
    assert not env.fga.reads


@pytest.mark.parametrize("resource_type", ["tool", "linsight_skill"])
@pytest.mark.parametrize("source_state", ["ACTIVE", "INACTIVE"])
async def test_existing_or_revoked_grants_are_never_restored_by_bootstrap(repair_env, resource_type, source_state):
    from dataclasses import replace

    env = repair_env
    spec = replace(_spec(), resource_type=resource_type)
    async with env.factory() as session:
        session.add(
            ResourcePermissionMode(
                tenant_id=1,
                resource_type=resource_type,
                resource_id=spec.resource_id,
                mode="CUSTOM",
                version=3,
                projection_state="CURRENT",
            )
        )
        grant = PermissionGrant(
            tenant_id=1,
            resource_type=resource_type,
            resource_id=spec.resource_id,
            model_key="viewer",
            state=source_state,
            projection_state="CURRENT",
        )
        session.add(grant)
        await session.flush()
        session.add(
            PermissionGrantAssignee(
                tenant_id=1,
                grant_id=grant.id,
                subject_type="tenant",
                subject_id="1",
                source_type="TENANT",
                source_ref="tenant:1#member",
                source_locator="tenant:1#member",
                source_fingerprint="s" * 64,
                projected_subject="tenant:1#member",
                protected=False,
                state=source_state,
            )
        )
        await session.commit()
    report = await reconcile_system_owned_resources(env.runtime, (spec,), apply=True, operator_id=1)
    assert report.current_count == 1
    assert not env.fga.calls and not env.fga.reads
    async with env.factory() as session:
        assert (await session.exec(select(ResourcePermissionMode))).one().version == 3
        assert (await session.exec(select(PermissionGrantAssignee))).one().state == source_state
        assert not (await session.exec(select(PermissionProjectionOperation))).all()


@pytest.mark.parametrize("status", ["PROJECTING", "FAILED_CLOSED"])
async def test_non_current_resources_fail_closed(repair_env, status):
    env = repair_env
    async with env.factory() as session:
        session.add(
            ResourcePermissionMode(
                tenant_id=1, resource_type="tool", resource_id="902", mode="CUSTOM", version=3, projection_state=status
            )
        )
        await session.commit()
    with pytest.raises(PermissionPublishNotReadyError, match="non-current"):
        await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=True, operator_id=1)
    assert not env.fga.calls


async def test_builtin_skill_entrypoint_uses_real_permission_creation(repair_env, monkeypatch):
    from bisheng.linsight.domain.services.skill_permission import ensure_builtin_skill_permission
    from bisheng.permission.application import process_runtime

    env = repair_env
    monkeypatch.setattr(
        process_runtime,
        "get_f048_process_runtime",
        AsyncMock(return_value=SimpleNamespace(components=SimpleNamespace(facade=env.runtime))),
    )
    await ensure_builtin_skill_permission(SimpleNamespace(id=902, tenant_id=1))
    assert ("tenant:1#member", "visible", "linsight_skill:902") in env.fga.present
    async with env.factory() as session:
        assert (await session.exec(select(PermissionProjectionOperation))).one().status == "FINALIZED"
