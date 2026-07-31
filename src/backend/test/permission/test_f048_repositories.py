"""F048 repository idempotency, version, cursor, and tenant contracts.

覆盖 AC: AC-19, AC-25, AC-27, AC-68, AC-93, AC-94, AC-143, AC-147
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database import tenant_filter
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionMigrationItem,
    PermissionMigrationRun,
    PermissionProjectionOperation,
    PermissionProjectionTuple,
)
from bisheng.permission.domain.repositories.catalog_repository import CatalogRepository
from bisheng.permission.domain.repositories.grant_repository import GrantRepository
from bisheng.permission.domain.repositories.migration_repository import (
    MigrationRepository,
    _migration_source_checksum,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

F048_TABLE_NAMES = (
    "authorization_model_release",
    "permission_catalog_release",
    "permission_action",
    "permission_action_resource_scope",
    "permission_model",
    "permission_model_action",
    "permission_catalog_projection_tuple",
    "permission_projection_operation",
    "permission_projection_tuple",
    "permission_grant",
    "permission_grant_assignee",
    "resource_permission_mode",
    "permission_migration_run",
    "permission_migration_item",
)


@pytest.fixture
async def session_factory() -> AsyncIterator[SessionFactory]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_metadata = sa.MetaData()
    for name in F048_TABLE_NAMES:
        cloned = SQLModel.metadata.tables[name].to_metadata(test_metadata)
        cloned.c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(test_metadata.create_all)

    tenant_filter._tenant_aware_tables.update(
        {
            "permission_grant",
            "permission_grant_assignee",
            "resource_permission_mode",
            "permission_projection_operation",
            "permission_projection_tuple",
            "permission_migration_item",
        }
    )
    tenant_filter.register_tenant_filter_events()

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    yield factory
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_tenant_context() -> AsyncIterator[None]:
    token = set_current_tenant_id(1)
    yield
    current_tenant_id.reset(token)


async def _seed_catalog(session_factory: SessionFactory) -> PermissionCatalogRelease:
    async with session_factory() as session:
        model_release = AuthorizationModelRelease(
            environment="test",
            store_id="store",
            model_version="f048",
            model_id="model",
            model_checksum="a" * 64,
            required_relations_checksum="b" * 64,
            openfga_version="1.15.1",
            status="ACTIVE",
        )
        session.add(model_release)
        await session.flush()
        release = PermissionCatalogRelease(
            release_key="catalog-1",
            version=1,
            status="CURRENT",
            required_authorization_model_release_id=model_release.id,
            draft_owner_id=7,
            idempotency_key="catalog-key",
            checksum="c" * 64,
        )
        session.add(release)
        await session.commit()
        await session.refresh(release)
        return release


@pytest.mark.asyncio
async def test_catalog_current_cas_and_cross_tenant_impact_cursor(
    session_factory: SessionFactory,
) -> None:
    release = await _seed_catalog(session_factory)
    catalog_repository = CatalogRepository(session_factory)
    grant_repository = GrantRepository(session_factory)

    current = await catalog_repository.aget_current_release(for_update=True)
    assert current is not None and current.id == release.id
    assert await catalog_repository.aupdate_release_cas(
        release_id=release.id,
        expected_version=1,
        values={"write_fenced": True},
    )
    assert not await catalog_repository.aupdate_release_cas(
        release_id=release.id,
        expected_version=1,
        values={"write_fenced": False},
    )

    for tenant_id, resource_id in ((1, "a"), (2, "b")):
        token = set_current_tenant_id(tenant_id)
        try:
            await grant_repository.acreate_grant(
                PermissionGrant(
                    resource_type="workflow",
                    resource_id=resource_id,
                    model_key="viewer",
                    state="ACTIVE",
                    projection_state="CURRENT",
                )
            )
        finally:
            current_tenant_id.reset(token)

    rows, cursor = await catalog_repository.aget_impact_cursor(
        after_tenant_id=None,
        after_resource_type=None,
        after_resource_id=None,
        limit=10,
    )
    assert rows == [(1, "workflow", "a"), (2, "workflow", "b")]
    assert cursor is None


@pytest.mark.asyncio
async def test_grant_and_assignee_idempotency_version_and_cursor(
    session_factory: SessionFactory,
) -> None:
    repository = GrantRepository(session_factory)
    grant = PermissionGrant(
        resource_type="knowledge_space",
        resource_id="100",
        model_key="editor",
        state="ACTIVE",
        projection_state="CURRENT",
    )
    first = await repository.acreate_grant(grant)
    duplicate = await repository.acreate_grant(
        PermissionGrant(
            resource_type="knowledge_space",
            resource_id="100",
            model_key="editor",
            state="ACTIVE",
            projection_state="CURRENT",
        )
    )
    assert duplicate.id == first.id

    assignee = PermissionGrantAssignee(
        grant_id=first.id,
        subject_type="department",
        subject_id="17",
        userset_relation="member",
        include_children=True,
        source_type="DEPARTMENT",
        source_ref="17",
        source_locator="department:17#member:children=1",
        source_fingerprint="d" * 64,
        projected_subject="department:17#descendant_member",
        state="ACTIVE",
    )
    stored = await repository.acreate_assignee(assignee)
    duplicate_assignee = await repository.acreate_assignee(assignee.model_copy(update={"id": None}))
    assert duplicate_assignee.id == stored.id
    assert await repository.aupdate_assignee_cas(
        assignee_id=stored.id,
        expected_version=1,
        values={"state": "INACTIVE"},
    )
    assert not await repository.aupdate_assignee_cas(
        assignee_id=stored.id,
        expected_version=1,
        values={"state": "ACTIVE"},
    )

    items, next_cursor = await repository.aget_assignee_cursor(
        resource_type="knowledge_space",
        resource_id="100",
        after_id=0,
        limit=1,
    )
    assert [item.id for item in items] == [stored.id]
    assert next_cursor is None


@pytest.mark.asyncio
async def test_repository_queries_remain_tenant_isolated(
    session_factory: SessionFactory,
) -> None:
    repository = GrantRepository(session_factory)
    first = await repository.acreate_grant(
        PermissionGrant(
            resource_type="tool",
            resource_id="same",
            model_key="owner",
            state="ACTIVE",
            projection_state="CURRENT",
        )
    )
    token = set_current_tenant_id(2)
    try:
        second = await repository.acreate_grant(
            PermissionGrant(
                resource_type="tool",
                resource_id="same",
                model_key="owner",
                state="ACTIVE",
                projection_state="CURRENT",
            )
        )
        assert second.id != first.id
        loaded = await repository.aget_grant(
            resource_type="tool",
            resource_id="same",
            model_key="owner",
        )
        assert loaded is not None and loaded.id == second.id
    finally:
        current_tenant_id.reset(token)

    loaded = await repository.aget_grant(
        resource_type="tool",
        resource_id="same",
        model_key="owner",
    )
    assert loaded is not None and loaded.id == first.id


@pytest.mark.asyncio
async def test_projection_operation_idempotency_checksum_and_status_cas(
    session_factory: SessionFactory,
) -> None:
    repository = ProjectionRepository(session_factory)
    operation = PermissionProjectionOperation(
        idempotency_key="op-key",
        request_checksum="a" * 64,
        operation_type="GRANT_MUTATION",
        scope_type="RESOURCE",
        scope_key="tool:same",
        expected_version=1,
        target_version=2,
        store_id="store",
        model_id="model",
        before_checksum="b" * 64,
        after_checksum="c" * 64,
        operator_id=7,
    )
    tuple_row = PermissionProjectionTuple(
        phase="COMMIT",
        sequence=1,
        action="WRITE",
        fga_user="user:7",
        relation="assignee",
        fga_object="permission_grant:1",
        tuple_fingerprint="d" * 64,
        inverse_action="DELETE",
    )
    stored = await repository.acreate_operation(operation, [tuple_row])
    duplicate = await repository.acreate_operation(
        operation.model_copy(update={"id": None}),
        [tuple_row.model_copy(update={"id": None, "operation_id": None})],
    )
    assert duplicate.id == stored.id

    with pytest.raises(PermissionVersionConflictError):
        await repository.acreate_operation(
            operation.model_copy(update={"id": None, "request_checksum": "e" * 64}),
            [],
        )

    assert await repository.aupdate_operation_status_cas(
        operation_id=stored.id,
        expected_status="PREPARED",
        target_status="STAGING",
    )
    assert not await repository.aupdate_operation_status_cas(
        operation_id=stored.id,
        expected_status="PREPARED",
        target_status="COMMITTED",
    )
    assert await repository.aget_operation_checksum(stored.id) is not None


@pytest.mark.asyncio
async def test_migration_environment_lease_item_and_checkpoint_resume(
    session_factory: SessionFactory,
) -> None:
    repository = MigrationRepository(session_factory)
    run = await repository.aget_or_create_run(
        PermissionMigrationRun(
            environment_fingerprint="f" * 64,
            phase="D1",
            store_id="store",
            source_model_id="old",
            target_model_id="new",
        )
    )
    duplicate = await repository.aget_or_create_run(run.model_copy(update={"id": None}))
    assert duplicate.id == run.id

    assert await repository.aacquire_environment_lease(
        run_id=run.id,
        expected_version=1,
        lock_token="lease",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert not await repository.aacquire_environment_lease(
        run_id=run.id,
        expected_version=1,
        lock_token="other",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert await repository.aupdate_checkpoint_cas(
        run_id=run.id,
        expected_version=2,
        phase="D2",
        checkpoint="cursor-10",
        source_checksum="1" * 64,
        target_checksum="2" * 64,
    )

    item = await repository.aupsert_item(
        PermissionMigrationItem(
            run_id=run.id,
            tenant_id=2,
            source_kind="CONFIG",
            source_locator="config:relation_models",
            source_checksum="3" * 64,
            status="MIGRATED",
            severity="INFO",
        )
    )
    duplicate_item = await repository.aupsert_item(item.model_copy(update={"id": None}))
    assert duplicate_item.id == item.id
    batch_items = await repository.aupsert_items(
        tuple(
            PermissionMigrationItem(
                run_id=run.id,
                tenant_id=2,
                source_kind="TUPLE",
                source_locator=f"tuple:{index}",
                source_checksum=str(index) * 64,
                status="MIGRATED",
                severity="INFO",
            )
            for index in (4, 5)
        )
    )
    assert len(batch_items) == 2
    assert all(row.id is not None for row in batch_items)

    items, cursor = await repository.aget_item_cursor(
        run_id=run.id,
        statuses=("MIGRATED",),
        after_id=0,
        limit=10,
    )
    assert [row.id for row in items] == [
        item.id,
        *(row.id for row in batch_items),
    ]
    assert cursor is None

    source_checksum = await repository.aget_run_checksum(run.id)
    await repository.aupsert_item(
        PermissionMigrationItem(
            run_id=run.id,
            tenant_id=None,
            source_kind="MODEL_MAPPING",
            source_locator="mapping:model_mapping:visibility-only",
            source_checksum="6" * 64,
            status="READY",
            severity="INFO",
            difference_type="VISIBILITY_ONLY_MODEL_PRESERVED",
        )
    )
    assert await repository.aget_run_checksum(run.id) == source_checksum

    assert await repository.aupdate_run_state_cas(
        run_id=run.id,
        expected_version=3,
        phase="SOURCE_VALIDATING",
        status="BLOCKED",
        checkpoint="mapping-blocked",
        source_checksum=source_checksum,
        target_checksum=None,
        blocker_count=7,
    )
    updated_run = await repository.aget_run(run.id)
    assert updated_run is not None
    assert updated_run.blocker_count == 7


def test_migration_source_checksum_is_independent_of_database_collation_order() -> None:
    run = PermissionMigrationRun(
        environment_fingerprint="f" * 64,
        phase="VERIFYING",
        store_id="store",
        source_model_id="legacy",
        source_watermark="watermark",
    )
    items = (
        PermissionMigrationItem(
            run_id=1,
            source_kind="TUPLE",
            source_locator="tuple:department:2|parent|department:5|",
            source_checksum="2" * 64,
            status="READY",
            severity="INFO",
        ),
        PermissionMigrationItem(
            run_id=1,
            source_kind="TUPLE",
            source_locator="tuple:department:200#member|viewer|workflow:1|",
            source_checksum="3" * 64,
            status="READY",
            severity="INFO",
        ),
    )

    assert _migration_source_checksum(run, items) == _migration_source_checksum(
        run,
        reversed(items),
    )
