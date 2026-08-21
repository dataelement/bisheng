"""SQL reservation and finalization contracts for F048 projections."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import (
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.permission.application import sql_runtime
from bisheng.permission.application.control_state import (
    SqlPermissionControlState,
)
from bisheng.permission.application.sql_runtime import (
    SqlProjectionFinalizer,
    SqlProjectionScopeGuard,
)
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.projection_plan import (
    ProjectionPlan,
    ProjectionTupleDelta,
)
from bisheng.permission.domain.services.visibility_projection_service import (
    VisibilityProjectionCompiler,
)


@pytest.fixture(autouse=True)
def tenant_context() -> AsyncIterator[None]:
    token = set_current_tenant_id(7)
    yield
    current_tenant_id.reset(token)


@pytest.fixture
async def session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = sa.MetaData()
    for name in (
        "permission_projection_operation",
        "permission_migration_run",
        "permission_migration_item",
        "permission_visible_source_projection",
        "permission_grant",
        "permission_grant_assignee",
        "resource_permission_mode",
    ):
        cloned = SQLModel.metadata.tables[name].to_metadata(metadata)
        cloned.c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(sql_runtime, "get_async_db_session", factory)
    yield factory
    await engine.dispose()


def _plan() -> ProjectionPlan:
    return ProjectionPlan(
        tenant_id=7,
        idempotency_key="mode-switch-7",
        operation_type="MODE_SWITCH",
        scope_type="resource",
        scope_key="folder:42",
        expected_version=3,
        target_version=4,
        store_id="store",
        model_id="model",
        operator_id=9,
        change_item_count=1,
        deltas=(
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=0,
                action="DELETE",
                user="user:*",
                relation="custom_mode",
                object="folder:42",
            ),
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=1,
                action="WRITE",
                user="user:*",
                relation="inherit_mode",
                object="folder:42",
            ),
        ),
    )


async def _seed_projecting_state(session_factory) -> int:
    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                operation = PermissionProjectionOperation(
                    tenant_id=7,
                    idempotency_key="mode-switch-7",
                    request_checksum="a" * 64,
                    operation_type="MODE_SWITCH",
                    scope_type="resource",
                    scope_key="folder:42",
                    expected_version=3,
                    target_version=4,
                    store_id="store",
                    model_id="model",
                    status="COMMITTED",
                    before_checksum="b" * 64,
                    after_checksum="c" * 64,
                    operator_id=9,
                )
                session.add(operation)
                await session.flush()
                mode = ResourcePermissionMode(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    mode="CUSTOM",
                    version=3,
                    projection_state="PROJECTING",
                    operation_id=int(operation.id),
                )
                grant = PermissionGrant(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    model_key="viewer",
                    state="PENDING",
                    projection_state="PROJECTING",
                )
                session.add_all((mode, grant))
                await session.flush()
                common = {
                    "tenant_id": 7,
                    "grant_id": int(grant.id),
                    "subject_type": "user",
                    "userset_relation": None,
                    "include_children": False,
                    "source_type": "DIRECT",
                    "protected": False,
                }
                session.add_all(
                    (
                        PermissionGrantAssignee(
                            id=101,
                            subject_id="11",
                            source_ref="user:11",
                            source_locator="direct:user:11",
                            source_fingerprint="d" * 64,
                            projected_subject="user:11",
                            state="PENDING",
                            version=1,
                            **common,
                        ),
                        PermissionGrantAssignee(
                            id=102,
                            subject_id="12",
                            source_ref="user:12",
                            source_locator="direct:user:12",
                            source_fingerprint="e" * 64,
                            projected_subject="user:12",
                            state="PENDING_DELETE",
                            version=4,
                            **common,
                        ),
                    )
                )
                session.add_all(
                    (
                        PermissionVisibleSourceProjection(
                            tenant_id=7,
                            resource_type="folder",
                            resource_id="42",
                            visibility_class="ordinary",
                            projected_subject="user:11",
                            source_kind="GRANT_ASSIGNEE",
                            source_owner_key="grant_assignee:101",
                            source_locator="direct:user:11",
                            source_fingerprint="d" * 64,
                            contribution_fingerprint="1" * 64,
                            model_key="viewer",
                            source_version=1,
                            tuple_fingerprint="2" * 64,
                            state="PENDING",
                            operation_id=int(operation.id),
                        ),
                        PermissionVisibleSourceProjection(
                            tenant_id=7,
                            resource_type="folder",
                            resource_id="42",
                            visibility_class="ordinary",
                            projected_subject="user:12",
                            source_kind="GRANT_ASSIGNEE",
                            source_owner_key="grant_assignee:102",
                            source_locator="direct:user:12",
                            source_fingerprint="e" * 64,
                            contribution_fingerprint="3" * 64,
                            model_key="viewer",
                            source_version=4,
                            tuple_fingerprint="4" * 64,
                            state="PENDING",
                            operation_id=int(operation.id),
                        ),
                    )
                )
            return int(operation.id)


@pytest.mark.asyncio
async def test_resource_scope_reservation_requires_bound_operation(
    session_factory,
) -> None:
    operation_id = await _seed_projecting_state(session_factory)
    guard = SqlProjectionScopeGuard()

    await guard.reserve(_plan(), operation_id)
    assert await guard.is_expected_version(_plan(), operation_id) is True
    assert await guard.is_expected_version(_plan(), operation_id + 1) is False
    with pytest.raises(PermissionPublishNotReadyError):
        await guard.reserve(_plan(), operation_id + 1)


@pytest.mark.asyncio
async def test_resource_finalizer_atomically_converges_and_replays(
    session_factory,
) -> None:
    operation_id = await _seed_projecting_state(session_factory)
    finalizer = SqlProjectionFinalizer()

    await finalizer.finalize(_plan(), operation_id)
    await finalizer.finalize(_plan(), operation_id)

    with bypass_tenant_filter():
        async with session_factory() as session:
            mode = (await session.execute(select(ResourcePermissionMode))).scalars().one()
            grant = (await session.execute(select(PermissionGrant))).scalars().one()
            assignees = list(
                (await session.execute(select(PermissionGrantAssignee).order_by(PermissionGrantAssignee.id))).scalars()
            )
            visible_sources = list(
                (
                    await session.execute(
                        select(PermissionVisibleSourceProjection).order_by(PermissionVisibleSourceProjection.id)
                    )
                ).scalars()
            )

    assert (mode.version, mode.projection_state, mode.mode) == (
        4,
        "CURRENT",
        "INHERIT",
    )
    assert (grant.state, grant.projection_state) == ("ACTIVE", "CURRENT")
    assert [(row.state, row.version) for row in assignees] == [
        ("ACTIVE", 1),
        ("INACTIVE", 5),
    ]
    assert [row.state for row in visible_sources] == ["ACTIVE", "RETIRED"]


@pytest.mark.asyncio
async def test_resource_finalizer_retires_old_model_source_after_assignee_move(
    session_factory,
) -> None:
    plan = ProjectionPlan(
        tenant_id=7,
        idempotency_key="move-visible-7",
        operation_type="GRANT_MUTATION",
        scope_type="resource",
        scope_key="folder:42",
        expected_version=3,
        target_version=4,
        store_id="store",
        model_id="model",
        operator_id=9,
        change_item_count=1,
        deltas=(
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=0,
                action="WRITE",
                user="user:11",
                relation="ordinary_assignee",
                object="permission_grant:g-editor",
            ),
        ),
    )
    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                operation = PermissionProjectionOperation(
                    tenant_id=7,
                    idempotency_key=plan.idempotency_key,
                    request_checksum="a" * 64,
                    operation_type=plan.operation_type,
                    scope_type=plan.scope_type,
                    scope_key=plan.scope_key,
                    expected_version=plan.expected_version,
                    target_version=plan.target_version,
                    store_id=plan.store_id,
                    model_id=plan.model_id,
                    status="COMMITTED",
                    before_checksum="b" * 64,
                    after_checksum="c" * 64,
                    operator_id=plan.operator_id,
                )
                session.add(operation)
                await session.flush()
                mode = ResourcePermissionMode(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    mode="CUSTOM",
                    version=3,
                    projection_state="PROJECTING",
                    operation_id=int(operation.id),
                )
                old_grant = PermissionGrant(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    model_key="viewer",
                    state="ACTIVE",
                    projection_state="PROJECTING",
                )
                target_grant = PermissionGrant(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    model_key="editor",
                    state="PENDING",
                    projection_state="PROJECTING",
                )
                session.add_all((mode, old_grant, target_grant))
                await session.flush()
                session.add(
                    PermissionGrantAssignee(
                        id=201,
                        tenant_id=7,
                        grant_id=int(target_grant.id),
                        subject_type="user",
                        subject_id="11",
                        userset_relation=None,
                        include_children=False,
                        source_type="DIRECT",
                        source_ref="user:11",
                        source_locator="direct:user:11",
                        source_fingerprint="d" * 64,
                        projected_subject="user:11",
                        protected=False,
                        state="PENDING",
                        version=2,
                    )
                )
                session.add_all(
                    (
                        PermissionVisibleSourceProjection(
                            tenant_id=7,
                            resource_type="folder",
                            resource_id="42",
                            visibility_class="ordinary",
                            projected_subject="user:11",
                            source_kind="GRANT_ASSIGNEE",
                            source_owner_key="grant_assignee:201",
                            source_locator="direct:user:11",
                            source_fingerprint="d" * 64,
                            contribution_fingerprint="5" * 64,
                            model_key="viewer",
                            source_version=1,
                            tuple_fingerprint="7" * 64,
                            state="PENDING",
                            operation_id=int(operation.id),
                        ),
                        PermissionVisibleSourceProjection(
                            tenant_id=7,
                            resource_type="folder",
                            resource_id="42",
                            visibility_class="ordinary",
                            projected_subject="user:11",
                            source_kind="GRANT_ASSIGNEE",
                            source_owner_key="grant_assignee:201",
                            source_locator="direct:user:11",
                            source_fingerprint="d" * 64,
                            contribution_fingerprint="6" * 64,
                            model_key="editor",
                            source_version=2,
                            tuple_fingerprint="7" * 64,
                            state="PENDING",
                            operation_id=int(operation.id),
                        ),
                    )
                )
                operation_id = int(operation.id)

    await SqlProjectionFinalizer().finalize(plan, operation_id)

    with bypass_tenant_filter():
        async with session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(PermissionVisibleSourceProjection).order_by(PermissionVisibleSourceProjection.model_key)
                    )
                ).scalars()
            )
    assert [(row.model_key, row.state) for row in rows] == [
        ("editor", "ACTIVE"),
        ("viewer", "RETIRED"),
    ]


@pytest.mark.asyncio
async def test_assignee_move_preserves_identity_and_advances_version(
    session_factory,
) -> None:
    source = GrantSourceService().canonicalize_source(
        source_id=101,
        subject_type="user",
        subject_id="11",
        source_type="DIRECT",
    )
    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                old_grant = PermissionGrant(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    model_key="viewer",
                    state="ACTIVE",
                    projection_state="CURRENT",
                )
                target_grant = PermissionGrant(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    model_key="editor",
                    state="PENDING",
                    projection_state="PROJECTING",
                )
                session.add_all((old_grant, target_grant))
                await session.flush()
                session.add(
                    PermissionGrantAssignee(
                        id=source.source_id,
                        tenant_id=7,
                        grant_id=int(old_grant.id),
                        subject_type=source.subject_type,
                        subject_id=source.subject_id,
                        userset_relation=source.userset_relation,
                        include_children=source.include_children,
                        source_type=source.source_type,
                        source_ref=source.source_ref,
                        source_locator=source.source_locator,
                        source_fingerprint=source.source_fingerprint,
                        projected_subject=source.projected_subject,
                        protected=source.protected,
                        state="ACTIVE",
                        version=1,
                    )
                )
                await session.flush()

                moved = await SqlPermissionControlState._upsert_assignee(
                    session,
                    grant_row=target_grant,
                    source=replace(source, version=2),
                    state="PENDING",
                )

                assert moved.id == 101
                assert moved.grant_id == target_grant.id
                assert moved.version == 2


@pytest.mark.asyncio
async def test_assignee_move_replaces_inactive_target_identity(
    session_factory,
) -> None:
    source = GrantSourceService().canonicalize_source(
        source_id=101,
        subject_type="user",
        subject_id="11",
        source_type="DIRECT",
    )
    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                old_grant = PermissionGrant(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    model_key="viewer",
                    state="ACTIVE",
                    projection_state="CURRENT",
                )
                target_grant = PermissionGrant(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    model_key="editor",
                    state="ACTIVE",
                    projection_state="CURRENT",
                )
                session.add_all((old_grant, target_grant))
                await session.flush()
                session.add_all(
                    (
                        PermissionGrantAssignee(
                            id=source.source_id,
                            tenant_id=7,
                            grant_id=int(old_grant.id),
                            subject_type=source.subject_type,
                            subject_id=source.subject_id,
                            userset_relation=source.userset_relation,
                            include_children=source.include_children,
                            source_type=source.source_type,
                            source_ref=source.source_ref,
                            source_locator=source.source_locator,
                            source_fingerprint=source.source_fingerprint,
                            projected_subject=source.projected_subject,
                            protected=source.protected,
                            state="ACTIVE",
                            version=1,
                        ),
                        PermissionGrantAssignee(
                            id=202,
                            tenant_id=7,
                            grant_id=int(target_grant.id),
                            subject_type=source.subject_type,
                            subject_id=source.subject_id,
                            userset_relation=source.userset_relation,
                            include_children=source.include_children,
                            source_type=source.source_type,
                            source_ref=source.source_ref,
                            source_locator=source.source_locator,
                            source_fingerprint=source.source_fingerprint,
                            projected_subject=source.projected_subject,
                            protected=source.protected,
                            state="INACTIVE",
                            version=4,
                        ),
                        PermissionVisibleSourceProjection(
                            tenant_id=7,
                            resource_type="folder",
                            resource_id="42",
                            visibility_class="ordinary",
                            projected_subject=source.projected_subject,
                            source_kind="GRANT_ASSIGNEE",
                            source_owner_key="grant_assignee:202",
                            source_locator=source.source_locator,
                            source_fingerprint=source.source_fingerprint,
                            contribution_fingerprint="8" * 64,
                            model_key="editor",
                            source_version=4,
                            tuple_fingerprint="9" * 64,
                            state="RETIRED",
                        ),
                    )
                )
                await session.flush()

                moved = await SqlPermissionControlState._upsert_assignee(
                    session,
                    grant_row=target_grant,
                    source=replace(source, version=2),
                    state="PENDING",
                )

                assert moved.id == 101
                assert moved.grant_id == target_grant.id
                assert moved.version == 2

            rows = list(
                (await session.execute(select(PermissionGrantAssignee).order_by(PermissionGrantAssignee.id)))
                .scalars()
                .all()
            )

    assert [(row.id, row.grant_id, row.state, row.version) for row in rows] == [
        (101, target_grant.id, "PENDING", 2),
    ]


@pytest.mark.asyncio
async def test_visible_source_after_state_is_frozen_then_finalized(
    session_factory,
) -> None:
    source = GrantSourceService().canonicalize_source(
        source_id=201,
        subject_type="user",
        subject_id="21",
        source_type="DIRECT",
    )
    grant = GrantSnapshot(
        grant_id="g-viewer",
        tenant_id=7,
        resource_type="folder",
        resource_id="42",
        model=GrantModelSnapshot(
            model_key="viewer",
            active=True,
            action_codes=("download",),
            derived_level=1,
        ),
        active=True,
        sources=(source,),
    )
    compiler = VisibilityProjectionCompiler()
    added = compiler.compile(
        tenant_id=7,
        grants=(grant,),
        existing_sources=(),
    )

    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                operation = PermissionProjectionOperation(
                    tenant_id=7,
                    idempotency_key="visible-add",
                    request_checksum="a" * 64,
                    operation_type="GRANT_MUTATION",
                    scope_type="resource",
                    scope_key="folder:42",
                    expected_version=3,
                    target_version=4,
                    store_id="store",
                    model_id="model",
                    status="PREPARED",
                    before_checksum="b" * 64,
                    after_checksum="c" * 64,
                    operator_id=9,
                )
                session.add(operation)
                await session.flush()
                operation_id = int(operation.id)
                await SqlPermissionControlState._prepare_visible_sources(
                    session,
                    tenant_id=7,
                    visibility=added,
                    operation_id=operation_id,
                )
        async with session_factory() as session:
            pending = (await session.execute(select(PermissionVisibleSourceProjection))).scalars().one()
            assert (pending.state, pending.operation_id) == ("PENDING", operation_id)
        async with session_factory() as session:
            async with session.begin():
                await SqlPermissionControlState._finalize_visible_sources(
                    session,
                    tenant_id=7,
                    visibility=added,
                    operation_id=operation_id,
                )
        async with session_factory() as session:
            active = (await session.execute(select(PermissionVisibleSourceProjection))).scalars().one()
            assert active.state == "ACTIVE"

    removed = compiler.compile(
        tenant_id=7,
        grants=(replace(grant, active=False, sources=()),),
        existing_sources=added.active_sources,
    )
    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                await SqlPermissionControlState._prepare_visible_sources(
                    session,
                    tenant_id=7,
                    visibility=removed,
                    operation_id=operation_id,
                )
        async with session_factory() as session:
            pending = (await session.execute(select(PermissionVisibleSourceProjection))).scalars().one()
            assert pending.state == "PENDING"
        async with session_factory() as session:
            async with session.begin():
                await SqlPermissionControlState._finalize_visible_sources(
                    session,
                    tenant_id=7,
                    visibility=removed,
                    operation_id=operation_id,
                )
        async with session_factory() as session:
            retired = (await session.execute(select(PermissionVisibleSourceProjection))).scalars().one()
            assert retired.state == "RETIRED"


def test_resource_claim_rejects_competing_same_version_operation() -> None:
    row = ResourcePermissionMode(
        tenant_id=7,
        resource_type="folder",
        resource_id="42",
        mode="CUSTOM",
        version=3,
        projection_state="CURRENT",
        operation_id=8,
    )

    SqlPermissionControlState._claim_projection_operation(
        row,
        expected_version=3,
        operation_id=9,
        allowed_initial_states=("CURRENT",),
    )
    SqlPermissionControlState._claim_projection_operation(
        row,
        expected_version=3,
        operation_id=9,
        allowed_initial_states=("CURRENT",),
    )
    with pytest.raises(PermissionVersionConflictError):
        SqlPermissionControlState._claim_projection_operation(
            row,
            expected_version=3,
            operation_id=10,
            allowed_initial_states=("CURRENT",),
        )
