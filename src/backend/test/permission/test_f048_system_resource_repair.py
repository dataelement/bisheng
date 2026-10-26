"""Preset-tool repairs preserve grants and use the durable SQL projection protocol."""

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
    AuthorizationModelMismatchError,
    InvalidPermissionModeError,
    PermissionInvalidResourceError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, tenant_execution_scope
from bisheng.permission.application import control_state, sql_runtime, system_resource_reconcile
from bisheng.permission.application.control_state import RuntimeCatalogSnapshot, SqlPermissionControlState
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
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.projection_service import ProjectionService
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from test.permission.test_f048_projection_service import FakeFGAProjection, FakeRecentMarker


def _spec(tenant_id=1, resource_id="902"):
    return SystemOwnedResourceSpec(
        tenant_id=tenant_id,
        resource_type="tool",
        resource_id=resource_id,
        action_codes=("use", "visible"),
        context_version=f"preset:{tenant_id}:{resource_id}",
    )


def _target(spec=None, version=3):
    spec = spec or _spec()
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=spec.tenant_id,
        resource_type=spec.resource_type,
        resource_id=spec.resource_id,
        resource_version=version,
        context_version=spec.context_version,
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
        assert not deletes
        assert all(row.relation in {"visible", "system_use_marker"} and row.user == "user:*" for row in writes)
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
            assert {(row.fga_user, row.relation, row.fga_object) for row in ledger} == {row.key for row in writes}
            mode = (
                await session.exec(
                    select(ResourcePermissionMode).where(ResourcePermissionMode.operation_id == operation.id)
                )
            ).one()
            assert mode.projection_state == "PROJECTING"
            assert mode.version == operation.expected_version
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
            models=(),
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
    runtime = F048PermissionRuntime(
        client=fga,
        state=state,
        marker=marker,
        decision=object(),
        projection=projection,
        sources=object(),
        owner=object(),
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


async def _seed(env, spec=None, *, projection_state="CURRENT", mode="CUSTOM"):
    spec = spec or _spec()
    with bypass_tenant_filter():
        async with env.factory() as session:
            session.add(
                ResourcePermissionMode(
                    tenant_id=spec.tenant_id,
                    resource_type="tool",
                    resource_id=spec.resource_id,
                    mode=mode,
                    version=3,
                    projection_state=projection_state,
                )
            )
            grant = PermissionGrant(
                tenant_id=spec.tenant_id,
                resource_type="tool",
                resource_id=spec.resource_id,
                model_key="owner",
                state="ACTIVE",
                projection_state="CURRENT",
            )
            session.add(grant)
            await session.flush()
            session.add(
                PermissionGrantAssignee(
                    tenant_id=spec.tenant_id,
                    grant_id=grant.id,
                    subject_type="user",
                    subject_id="1",
                    source_type="DIRECT",
                    source_ref="owner:1",
                    source_locator="owner:1",
                    source_fingerprint="s" * 64,
                    projected_subject="user:1",
                    protected=True,
                    state="ACTIVE",
                )
            )
            await session.commit()
    env.fga.present.update(
        {
            ("user:1", "visible", spec.object_key),
            ("permission_grant:owner", "grant", spec.object_key),
            ("user:*", "custom_mode", spec.object_key),
            ("user:*", "permission_enabled", spec.object_key),
        }
    )


@pytest.mark.parametrize("missing", [("visible",), ("system_use_marker",), ("visible", "system_use_marker"), ()])
async def test_current_tool_repairs_exact_missing_tuples_and_preserves_existing_authorization(repair_env, missing):
    env = repair_env
    await _seed(env)
    for relation in {"visible", "system_use_marker"} - set(missing):
        env.fga.present.add(("user:*", relation, "tool:902"))
    original = set(env.fga.present)

    audit = await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=False, operator_id=7)
    assert audit.before[0].missing_relations == missing
    assert audit.missing_tuple_count == len(missing)
    assert not env.fga.calls
    async with env.factory() as session:
        assert not (await session.exec(select(PermissionProjectionOperation))).all()

    report = await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=True, operator_id=7)

    assert report.current_count == 1
    assert env.fga.present == original | {("user:*", relation, "tool:902") for relation in missing}
    async with env.factory() as session:
        mode = (await session.exec(select(ResourcePermissionMode))).one()
        grant = (await session.exec(select(PermissionGrant))).one()
        source = (await session.exec(select(PermissionGrantAssignee))).one()
        operations = (await session.exec(select(PermissionProjectionOperation))).all()
    assert mode.mode == "CUSTOM" and mode.projection_state == "CURRENT"
    assert mode.version == (4 if missing else 3)
    assert (grant.model_key, grant.version, grant.state, grant.projection_state) == ("owner", 1, "ACTIVE", "CURRENT")
    assert (source.subject_id, source.version, source.state, source.protected) == ("1", 1, "ACTIVE", True)
    assert len(operations) == bool(missing)
    if missing:
        assert (operations[0].status, operations[0].operation_type, operations[0].operator_id) == (
            "FINALIZED",
            "RESOURCE_SYSTEM_REPAIR",
            7,
        )

    again = await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=True, operator_id=7)
    assert again.incomplete_count == 0
    assert len(env.fga.calls) == bool(missing)


async def test_later_tuple_loss_creates_a_new_versioned_repair(repair_env):
    env = repair_env
    await _seed(env)
    await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=True, operator_id=1)
    env.fga.present.remove(("user:*", "visible", "tool:902"))

    await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=True, operator_id=1)

    async with env.factory() as session:
        operations = (
            await session.exec(select(PermissionProjectionOperation).order_by(PermissionProjectionOperation.id))
        ).all()
        mode = (await session.exec(select(ResourcePermissionMode))).one()
    assert [one.expected_version for one in operations] == [3, 4]
    assert len({one.idempotency_key for one in operations}) == 2
    assert mode.version == 5


@pytest.mark.parametrize("status", ["PROJECTING", "FAILED_CLOSED"])
async def test_non_current_resource_blocks_without_reading_or_writing_fga(repair_env, status):
    env = repair_env
    await _seed(env, projection_state=status)
    with pytest.raises(PermissionPublishNotReadyError, match="non-current"):
        await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=True, operator_id=1)
    assert not env.fga.reads and not env.fga.calls


async def test_partial_commit_fails_closed_and_keeps_recoverable_ledger(repair_env):
    env = repair_env
    await _seed(env)
    env.fga.timeout_mode = "mixed"
    with pytest.raises(PermissionProjectionFailedError):
        await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=True, operator_id=1)
    async with env.factory() as session:
        mode = (await session.exec(select(ResourcePermissionMode))).one()
        operation = (await session.exec(select(PermissionProjectionOperation))).one()
        rows = (await session.exec(select(PermissionProjectionTuple))).all()
    assert mode.projection_state == operation.status == "FAILED_CLOSED"
    assert mode.version == 3
    assert {row.relation for row in rows} == {"visible", "system_use_marker"}


async def test_commit_timeout_after_write_converges_using_original_ledger(repair_env):
    env = repair_env
    await _seed(env)
    env.fga.timeout_mode = "after"
    report = await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=True, operator_id=1)
    assert report.current_count == 1
    assert len(env.fga.calls) == 1
    async with env.factory() as session:
        operation = (await session.exec(select(PermissionProjectionOperation))).one()
    assert operation.status == "FINALIZED"


@pytest.mark.parametrize("failure", ["catalog", "version", "mode", "conditional", "read", "marker"])
async def test_unsafe_audit_or_prepare_never_writes_fga(repair_env, monkeypatch, failure):
    env = repair_env
    await _seed(env, mode="INHERIT" if failure == "mode" else "CUSTOM")
    target = _target(version=2 if failure == "version" else 3)
    error = PermissionPublishNotReadyError
    if failure == "catalog":
        env.fga.model_id = "wrong-model"
        error = AuthorizationModelMismatchError
    elif failure == "mode":
        error = InvalidPermissionModeError
    elif failure == "conditional":
        env.fga.extra_rows = [
            {"user": "user:*", "relation": "visible", "object": "tool:902", "condition": {"name": "conditional"}}
        ]
    elif failure == "read":
        monkeypatch.setattr(env.fga, "read_tuples", AsyncMock(side_effect=RuntimeError("read unavailable")))
        error = RuntimeError
    elif failure == "marker":
        env.marker.ready = False
    with pytest.raises(error):
        await env.runtime.repair_system_owned(
            actor=PermissionActor(user_id=1, current_tenant_id=1), target=target, action_codes=("use", "visible")
        )
    assert not env.fga.calls
    async with env.factory() as session:
        assert (await session.exec(select(ResourcePermissionMode))).one().projection_state == "CURRENT"


async def test_version_race_abandons_prepared_operation_without_overwriting_mode(repair_env, monkeypatch):
    env = repair_env
    await _seed(env)
    monkeypatch.setattr(env.state, "mark_projecting", AsyncMock(side_effect=PermissionVersionConflictError()))
    with pytest.raises(PermissionVersionConflictError):
        await reconcile_system_owned_resources(env.runtime, (_spec(),), apply=True, operator_id=1)
    assert not env.fga.calls
    async with env.factory() as session:
        mode = (await session.exec(select(ResourcePermissionMode))).one()
        operation = (await session.exec(select(PermissionProjectionOperation))).one()
    assert operation.status == "FAILED_CLOSED"
    assert mode.projection_state == "CURRENT" and mode.version == 3


async def test_repair_binds_each_tenant_for_reads_and_writes_and_restores_caller(repair_env):
    env = repair_env
    specs = (_spec(), _spec(tenant_id=2, resource_id="903"))
    for spec in specs:
        await _seed(env, spec)
    with tenant_execution_scope(99):
        report = await reconcile_system_owned_resources(env.runtime, specs, apply=True, operator_id=1)
        assert get_current_tenant_id() == 99
    assert report.current_count == 2
    assert {(tenant, read["object"]) for tenant, read in env.fga.reads} == {(1, "tool:902"), (2, "tool:903")}
    with bypass_tenant_filter():
        async with env.factory() as session:
            operations = (await session.exec(select(PermissionProjectionOperation))).all()
    assert {(op.tenant_id, op.scope_key) for op in operations} == {(1, "tool:902"), (2, "tool:903")}


@pytest.mark.parametrize("changes", [{"resource_type": "dashboard"}, {"resource_version": 0}, {"tenant_id": 2}])
async def test_invalid_or_cross_tenant_repair_target_is_rejected(repair_env, changes):
    env = repair_env
    await _seed(env)
    with pytest.raises(PermissionInvalidResourceError):
        await env.runtime.repair_system_owned(
            actor=PermissionActor(user_id=1, current_tenant_id=1),
            target=_target().model_copy(update=changes),
            action_codes=("use", "visible"),
        )
    assert not env.fga.calls


async def test_inventory_repairs_historical_preset_but_excludes_deleted_and_non_preset_tools(repair_env):
    env = repair_env
    specs = (_spec(), _spec(resource_id="904"), _spec(resource_id="905"))
    for spec in specs:
        await _seed(env, spec)
    async with env.factory() as session:
        session.add_all(
            [
                GptsToolsType(id=902, tenant_id=1, name="Web search", is_preset=1, user_id=1, is_delete=0),
                GptsToolsType(id=904, tenant_id=1, name="API tool", is_preset=0, user_id=1, is_delete=0),
                GptsToolsType(id=905, tenant_id=1, name="Deleted preset", is_preset=1, user_id=1, is_delete=1),
            ]
        )
        await session.commit()

    inventory = await bootstrap.load_system_owned_resource_inventory()
    report = await reconcile_system_owned_resources(env.runtime, inventory.resources, apply=True, operator_id=1)

    assert [spec.resource_id for spec in inventory.resources] == ["902"]
    assert report.current_count == 1
    assert {row.object for writes, _ in env.fga.calls for row in writes} == {"tool:902"}
