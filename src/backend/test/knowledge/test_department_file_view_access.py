from __future__ import annotations

import importlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateTable
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.audit_log import AuditLog
from bisheng.knowledge.domain.models.department_file_view_grant import (
    DepartmentFileViewGrant,
    DepartmentFileViewGrantStatus,
)
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessSource,
    DepartmentFileAccessStatus,
    DepartmentFileResource,
    DepartmentFileViewAccessService,
)
from bisheng.knowledge.domain.services.department_file_view_grant_audit_writer import (
    DepartmentFileViewGrantAuditWriter,
)
from bisheng.user.domain.services.auth import LoginUser

SCHEMA_MIGRATION = "bisheng.core.database.alembic.versions.v2_6_0_f067_department_file_view_grant"
DATA_MIGRATION = "bisheng.core.database.alembic.versions.v2_6_0_f068_department_file_view_scenario_seed"


@pytest.fixture
async def grant_session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(DepartmentFileViewGrant.__table__.create)
        await conn.run_sync(AuditLog.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


def test_grant_schema_has_fixed_business_key_and_no_cascade_or_expiry() -> None:
    table = DepartmentFileViewGrant.__table__
    column_names = set(table.columns.keys())

    assert {
        "id",
        "tenant_id",
        "user_id",
        "space_id",
        "file_id",
        "department_id",
        "approval_instance_id",
        "grant_source",
        "status",
        "granted_at",
        "revoked_at",
        "revoked_by",
        "revoked_reason",
        "invalidated_at",
        "invalidated_reason",
        "create_time",
        "update_time",
    } <= column_names
    assert "expires_at" not in column_names
    assert not table.foreign_keys

    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("tenant_id", "user_id", "space_id", "file_id") in unique_sets

    index_sets = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert ("tenant_id", "user_id", "status") in index_sets
    assert ("tenant_id", "space_id", "file_id", "status") in index_sets
    assert ("tenant_id", "department_id", "status") in index_sets
    assert ("approval_instance_id",) in index_sets


@pytest.mark.asyncio
async def test_repository_activation_is_idempotent_and_reuses_business_row(
    grant_session: AsyncSession,
) -> None:
    repository = DepartmentFileViewGrantRepositoryImpl(grant_session)

    first = await repository.activate(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=11,
        department_id=12,
        approval_instance_id=100,
    )
    await grant_session.commit()
    original_id = first.id

    second = await repository.activate(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=11,
        department_id=13,
        approval_instance_id=101,
    )
    await grant_session.commit()

    assert second.id == original_id
    assert second.status == DepartmentFileViewGrantStatus.ACTIVE
    assert second.department_id == 13
    assert second.approval_instance_id == 101
    assert second.revoked_at is None
    assert second.revoked_reason is None
    assert second.invalidated_at is None
    assert second.invalidated_reason is None
    assert (
        len(
            await repository.list_by_user_and_files(
                tenant_id=1,
                user_id=9,
                resource_keys={(10, 11)},
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_revoke_requires_latest_instance_and_can_be_reactivated(
    grant_session: AsyncSession,
) -> None:
    repository = DepartmentFileViewGrantRepositoryImpl(grant_session)
    row = await repository.activate(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=11,
        department_id=12,
        approval_instance_id=100,
    )

    stale = await repository.revoke(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=11,
        approval_instance_id=99,
        revoked_by=7,
        reason="stale",
    )
    assert stale is None
    assert row.status == DepartmentFileViewGrantStatus.ACTIVE

    revoked = await repository.revoke(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=11,
        approval_instance_id=100,
        revoked_by=7,
        reason="manual",
    )
    assert revoked is row
    assert row.status == DepartmentFileViewGrantStatus.REVOKED
    assert row.revoked_by == 7
    assert row.revoked_reason == "manual"

    reactivated = await repository.activate(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=11,
        department_id=12,
        approval_instance_id=101,
    )
    assert reactivated.status == DepartmentFileViewGrantStatus.ACTIVE
    assert reactivated.revoked_at is None
    assert reactivated.revoked_by is None
    assert reactivated.revoked_reason is None


@pytest.mark.asyncio
async def test_invalidate_and_audit_share_caller_transaction(
    grant_session: AsyncSession,
) -> None:
    repository = DepartmentFileViewGrantRepositoryImpl(grant_session)
    writer = DepartmentFileViewGrantAuditWriter(grant_session)
    await repository.activate(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=11,
        department_id=12,
        approval_instance_id=100,
    )
    invalidated = await repository.invalidate_by_space(
        tenant_id=1,
        space_id=10,
        reason="department_rebound",
    )
    assert len(invalidated) == 1
    assert invalidated[0].status == DepartmentFileViewGrantStatus.INVALIDATED

    writer.add_transition(
        grant=invalidated[0],
        operator_id=7,
        action="department_file_view_grant.invalidated",
        old_status=DepartmentFileViewGrantStatus.ACTIVE,
        new_status=DepartmentFileViewGrantStatus.INVALIDATED,
        reason="department_rebound",
    )

    assert grant_session.new
    await grant_session.rollback()

    assert (
        await repository.list_by_user_and_files(
            tenant_id=1,
            user_id=9,
            resource_keys={(10, 11)},
        )
        == []
    )
    audit_rows = list((await grant_session.exec(sa.select(AuditLog))).all())
    assert audit_rows == []


@pytest.mark.asyncio
async def test_active_batch_lookup_ignores_revoked_and_wrong_department(
    grant_session: AsyncSession,
) -> None:
    repository = DepartmentFileViewGrantRepositoryImpl(grant_session)
    active = await repository.activate(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=11,
        department_id=12,
        approval_instance_id=100,
    )
    revoked = await repository.activate(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=13,
        department_id=12,
        approval_instance_id=101,
    )
    await repository.revoke(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=13,
        approval_instance_id=101,
        revoked_by=7,
        reason="manual",
    )
    await grant_session.commit()

    result = await repository.list_active_by_user_and_files(
        tenant_id=1,
        user_id=9,
        resources={(10, 11): 12, (10, 13): 12, (10, 99): 12},
    )

    assert result == {(10, 11): active}
    assert revoked.status == DepartmentFileViewGrantStatus.REVOKED


@pytest.mark.asyncio
async def test_read_time_revalidation_invalidates_stale_grant_with_audit(
    grant_session: AsyncSession,
) -> None:
    repository = DepartmentFileViewGrantRepositoryImpl(grant_session)
    stale = await repository.activate(
        tenant_id=1,
        user_id=9,
        space_id=10,
        file_id=11,
        department_id=99,
        approval_instance_id=100,
    )
    await grant_session.commit()
    file_record = _file()
    resource = _resource(file_record, department_id=12)
    service = DepartmentFileViewAccessService(
        session=grant_session,
        grant_repository=repository,
        resource_loader=AsyncMock(return_value={11: resource}),
        permission_resolver=AsyncMock(return_value={11: set()}),
        approver_resolver=AsyncMock(return_value={12: set()}),
        persist_stale_grant_revalidation=True,
    )

    decision = await service.evaluate_file(
        login_user=_login_user(user_id=9),
        file=file_record,
    )

    await grant_session.refresh(stale)
    audit = (await grant_session.exec(select(AuditLog))).one()
    assert decision.status == DepartmentFileAccessStatus.APPROVAL_REQUIRED
    assert stale.status == DepartmentFileViewGrantStatus.INVALIDATED
    assert stale.invalidated_reason == "read_time_revalidation"
    assert audit.reason == "read_time_revalidation"
    assert audit.audit_metadata["old_status"] == "active"
    assert audit.audit_metadata["new_status"] == "invalidated"
    assert audit.audit_metadata["department_id"] == 99


def test_schema_and_data_migrations_are_separate_and_chain_from_current_head() -> None:
    schema_migration = importlib.import_module(SCHEMA_MIGRATION)
    data_migration = importlib.import_module(DATA_MIGRATION)

    assert schema_migration.down_revision == "f066_token_file_sync_rule"
    assert data_migration.down_revision == schema_migration.revision
    assert schema_migration.TABLE_NAME == "department_file_view_grant"
    assert not hasattr(schema_migration, "SCENARIO_CODE")
    assert data_migration.SCENARIO_CODE == "department_file_view_request"
    assert not hasattr(data_migration, "GRANT_TABLE")


def test_schema_migration_upgrade_downgrade_upgrade_on_isolated_database() -> None:
    migration = importlib.import_module(SCHEMA_MIGRATION)
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        with patch.object(migration, "op", operations):
            migration.upgrade()
            assert migration.TABLE_NAME in sa.inspect(connection).get_table_names()
            index_names = {index["name"] for index in sa.inspect(connection).get_indexes(migration.TABLE_NAME)}
            assert {
                "idx_dfvg_tenant_user_status",
                "idx_dfvg_tenant_space_file_status",
                "idx_dfvg_tenant_department_status",
                "idx_dfvg_approval_instance",
            } <= index_names

            migration.downgrade()
            assert migration.TABLE_NAME not in sa.inspect(connection).get_table_names()

            migration.upgrade()
            assert migration.TABLE_NAME in sa.inspect(connection).get_table_names()


def test_grant_schema_compiles_for_mysql() -> None:
    ddl = str(CreateTable(DepartmentFileViewGrant.__table__).compile(dialect=mysql.dialect()))

    assert "CREATE TABLE department_file_view_grant" in ddl
    assert "AUTO_INCREMENT" in ddl
    assert "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP" in ddl
    assert "uk_dfvg_tenant_user_space_file" in ddl


def test_model_defaults_do_not_require_tenant_business_branch() -> None:
    row = DepartmentFileViewGrant(
        user_id=9,
        space_id=10,
        file_id=11,
        department_id=12,
        approval_instance_id=100,
        granted_at=datetime(2026, 7, 23, 12, 0, 0),
    )

    assert row.tenant_id is None
    assert row.grant_source == "approval_instance"
    assert row.status == DepartmentFileViewGrantStatus.ACTIVE


def _file(*, file_id: int = 11, space_id: int = 10, uploader_id: int = 8):
    return SimpleNamespace(
        id=file_id,
        knowledge_id=space_id,
        user_id=uploader_id,
        file_name="安全制度.pdf",
        file_type=1,
        file_level_path="/20/21/",
        file_source="space_upload",
        file_size=4096,
        file_encoding="SG-001",
        abstract="不应在未授权列表返回的摘要",
        object_name="tenant_1/private/source.pdf",
        preview_file_object_name="tenant_1/private/preview.pdf",
        bbox_object_name="tenant_1/private/bbox.json",
        status=2,
        update_time=datetime(2026, 7, 23, 12, 0, 0),
        file_subcategory_code="policy",
    )


def _resource(
    file_record,
    *,
    creator_id: int = 7,
    department_id: int = 12,
    valid: bool = True,
):
    return DepartmentFileResource(
        file=file_record,
        space=SimpleNamespace(
            id=file_record.knowledge_id,
            user_id=creator_id,
            name="炼钢部知识库",
            tenant_id=1,
        ),
        scope=SimpleNamespace(
            space_id=file_record.knowledge_id,
            tenant_id=1,
            level="department",
            owner_type="department",
            owner_id=department_id,
        ),
        binding=SimpleNamespace(
            space_id=file_record.knowledge_id,
            tenant_id=1,
            department_id=department_id,
        ),
        department=SimpleNamespace(
            id=department_id,
            status="active",
            is_deleted=0,
            path=f"/1/{department_id}/",
        ),
        valid=valid,
    )


def _login_user(user_id: int, *, admin: bool = False) -> LoginUser:
    return LoginUser(
        user_id=user_id,
        user_name=f"user-{user_id}",
        user_role=[1] if admin else [2],
        tenant_id=1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "admin", "creator_id", "uploader_id", "approvers", "permissions", "source"),
    [
        (1, True, 7, 8, set(), set(), DepartmentFileAccessSource.ADMINISTRATOR),
        (7, False, 7, 8, set(), set(), DepartmentFileAccessSource.RESOURCE_OWNER),
        (8, False, 7, 8, set(), set(), DepartmentFileAccessSource.RESOURCE_OWNER),
        (9, False, 7, 8, {9}, set(), DepartmentFileAccessSource.DEPARTMENT_APPROVER),
        (9, False, 7, 8, set(), {"view_file"}, DepartmentFileAccessSource.PERMISSION_TEMPLATE),
    ],
)
async def test_access_service_direct_bypass_matrix(
    user_id: int,
    admin: bool,
    creator_id: int,
    uploader_id: int,
    approvers: set[int],
    permissions: set[str],
    source: str,
) -> None:
    file_record = _file(uploader_id=uploader_id)
    resource_loader = AsyncMock(return_value={file_record.id: _resource(file_record, creator_id=creator_id)})
    permission_resolver = AsyncMock(return_value={file_record.id: permissions})
    approver_resolver = AsyncMock(return_value={12: approvers})
    grant_repository = AsyncMock()
    grant_repository.list_active_by_user_and_files.return_value = {}
    service = DepartmentFileViewAccessService(
        grant_repository=grant_repository,
        resource_loader=resource_loader,
        permission_resolver=permission_resolver,
        approver_resolver=approver_resolver,
    )

    decisions = await service.evaluate_files(
        login_user=_login_user(user_id, admin=admin),
        files=[file_record],
    )

    assert decisions[file_record.id].status == DepartmentFileAccessStatus.ALLOWED
    assert decisions[file_record.id].source == source


@pytest.mark.asyncio
async def test_access_service_keeps_download_independent_from_content_grant() -> None:
    download_file = _file(file_id=11)
    grant_file = _file(file_id=12)
    resources = {
        download_file.id: _resource(download_file),
        grant_file.id: _resource(grant_file),
    }
    active_grant = SimpleNamespace(
        file_id=grant_file.id,
        space_id=grant_file.knowledge_id,
        department_id=12,
        status=DepartmentFileViewGrantStatus.ACTIVE,
    )
    grant_repository = AsyncMock()
    grant_repository.list_active_by_user_and_files.return_value = {
        (grant_file.knowledge_id, grant_file.id): active_grant,
    }
    service = DepartmentFileViewAccessService(
        grant_repository=grant_repository,
        resource_loader=AsyncMock(return_value=resources),
        permission_resolver=AsyncMock(
            return_value={
                download_file.id: {"download_file"},
                grant_file.id: set(),
            }
        ),
        approver_resolver=AsyncMock(return_value={12: set()}),
    )

    decisions = await service.evaluate_files(
        login_user=_login_user(9),
        files=[download_file, grant_file],
    )

    assert decisions[download_file.id].status == DepartmentFileAccessStatus.APPROVAL_REQUIRED
    assert decisions[download_file.id].can_download is True
    assert decisions[grant_file.id].status == DepartmentFileAccessStatus.ALLOWED
    assert decisions[grant_file.id].source == DepartmentFileAccessSource.APPROVAL_GRANT
    assert decisions[grant_file.id].can_download is False


@pytest.mark.asyncio
async def test_access_service_fails_closed_for_tampered_resource_snapshot() -> None:
    file_record = _file()
    invalid_resource = _resource(file_record, valid=False)
    service = DepartmentFileViewAccessService(
        grant_repository=AsyncMock(),
        resource_loader=AsyncMock(return_value={file_record.id: invalid_resource}),
        permission_resolver=AsyncMock(return_value={file_record.id: {"view_file", "download_file"}}),
        approver_resolver=AsyncMock(return_value={12: {9}}),
    )

    decision = (
        await service.evaluate_files(
            login_user=_login_user(9),
            files=[file_record],
        )
    )[file_record.id]

    assert decision.status == DepartmentFileAccessStatus.UNAVAILABLE
    assert decision.source is None
    assert decision.can_download is False


@pytest.mark.asyncio
async def test_access_service_batches_resource_permission_approver_and_grant_reads() -> None:
    files = [_file(file_id=11), _file(file_id=12)]
    resource_loader = AsyncMock(return_value={file.id: _resource(file) for file in files})
    permission_resolver = AsyncMock(return_value={file.id: set() for file in files})
    approver_resolver = AsyncMock(return_value={12: set()})
    grant_repository = AsyncMock()
    grant_repository.list_active_by_user_and_files.return_value = {}
    service = DepartmentFileViewAccessService(
        grant_repository=grant_repository,
        resource_loader=resource_loader,
        permission_resolver=permission_resolver,
        approver_resolver=approver_resolver,
    )

    await service.evaluate_files(login_user=_login_user(9), files=files)

    resource_loader.assert_awaited_once()
    permission_resolver.assert_awaited_once()
    approver_resolver.assert_awaited_once()
    grant_repository.list_active_by_user_and_files.assert_awaited_once()


def test_unauthorized_metadata_projection_uses_allowlist() -> None:
    file_record = _file()
    decision = SimpleNamespace(
        status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
        can_download=True,
    )

    projected = DepartmentFileViewAccessService.project_safe_metadata(
        file_record=file_record,
        space_name="炼钢部知识库",
        decision=decision,
        tags=["制度", "安全"],
    )

    assert projected == {
        "id": 11,
        "space_id": 10,
        "file_name": "安全制度.pdf",
        "space_name": "炼钢部知识库",
        "folder_path": "/20/21/",
        "file_source": "space_upload",
        "file_ext": "pdf",
        "file_subcategory_code": "policy",
        "tags": ["制度", "安全"],
        "updated_at": datetime(2026, 7, 23, 12, 0, 0),
        "content_access": DepartmentFileAccessStatus.APPROVAL_REQUIRED,
        "can_download": True,
    }
    assert {
        "abstract",
        "summary",
        "file_size",
        "file_encoding",
        "object_name",
        "preview_file_object_name",
        "bbox_object_name",
    }.isdisjoint(projected)
