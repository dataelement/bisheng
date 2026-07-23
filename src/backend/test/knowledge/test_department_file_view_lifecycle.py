from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.audit_log import AuditLog
from bisheng.knowledge.domain.models.department_file_view_grant import (
    DepartmentFileViewGrant,
    DepartmentFileViewGrantStatus,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.department_file_view_grant_audit_writer import (
    DepartmentFileViewGrantAuditWriter,
)
from bisheng.knowledge.domain.services.department_file_view_lifecycle_service import (
    DepartmentFileViewLifecycleService,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


@pytest_asyncio.fixture
async def lifecycle_session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: SQLModel.metadata.create_all(
                sync_connection,
                tables=[
                    KnowledgeFile.__table__,
                    DepartmentFileViewGrant.__table__,
                    AuditLog.__table__,
                ],
            )
        )

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    yield factory
    await engine.dispose()


async def _seed_file_and_grant(
    factory,
    *,
    file_id: int = 11,
    user_id: int = 9,
) -> None:
    async with factory() as session:
        session.add(
            KnowledgeFile(
                id=file_id,
                tenant_id=1,
                user_id=3,
                user_name="上传者",
                knowledge_id=10,
                file_name="安全制度.pdf",
                file_type=FileType.FILE.value,
                file_level_path="",
                status=KnowledgeFileStatus.SUCCESS.value,
            )
        )
        session.add(
            DepartmentFileViewGrant(
                tenant_id=1,
                user_id=user_id,
                space_id=10,
                file_id=file_id,
                department_id=12,
                approval_instance_id=100 + user_id,
            )
        )
        await session.commit()


def _service(session: AsyncSession) -> DepartmentFileViewLifecycleService:
    return DepartmentFileViewLifecycleService(
        session=session,
        file_repository=KnowledgeFileRepositoryImpl(session),
        grant_repository=DepartmentFileViewGrantRepositoryImpl(session),
    )


@pytest.mark.asyncio
async def test_same_space_rename_and_folder_move_keep_grant_and_copy_does_not_inherit(
    lifecycle_session_factory,
) -> None:
    await _seed_file_and_grant(lifecycle_session_factory)
    async with lifecycle_session_factory() as session:
        file = await session.get(KnowledgeFile, 11)
        file.file_name = "安全制度-修订.pdf"
        file.file_level_path = "/21"
        session.add(
            KnowledgeFile(
                id=12,
                tenant_id=1,
                user_id=3,
                user_name="上传者",
                knowledge_id=10,
                file_name="安全制度-副本.pdf",
                file_type=FileType.FILE.value,
                file_level_path="/21",
                status=KnowledgeFileStatus.SUCCESS.value,
            )
        )
        await session.commit()

    async with lifecycle_session_factory() as session:
        repository = DepartmentFileViewGrantRepositoryImpl(session)
        grants = await repository.list_active_by_user_and_files(
            tenant_id=1,
            user_id=9,
            resources={(10, 11): 12, (10, 12): 12},
        )
        assert set(grants) == {(10, 11)}


@pytest.mark.asyncio
async def test_file_delete_commits_file_grant_and_audit_together(
    lifecycle_session_factory,
) -> None:
    await _seed_file_and_grant(lifecycle_session_factory)
    async with lifecycle_session_factory() as session:
        await _service(session).prepare_file_delete(
            tenant_id=1,
            space_id=10,
            file_ids=[11],
            operator_id=7,
            operator_name="管理员",
        )
        await session.commit()

    async with lifecycle_session_factory() as session:
        assert await session.get(KnowledgeFile, 11) is None
        grant = (await session.exec(select(DepartmentFileViewGrant))).one()
        audit = (await session.exec(select(AuditLog))).one()
        assert grant.status == DepartmentFileViewGrantStatus.INVALIDATED
        assert grant.invalidated_reason == "file_deleted"
        assert audit.reason == "file_deleted"
        assert audit.audit_metadata["old_status"] == "active"
        assert audit.audit_metadata["new_status"] == "invalidated"
        assert audit.audit_metadata["space_id"] == 10
        assert audit.audit_metadata["file_id"] == 11
        assert audit.operator_id == 7


@pytest.mark.asyncio
async def test_file_delete_failure_rolls_back_file_grant_and_audit_together(
    lifecycle_session_factory,
) -> None:
    await _seed_file_and_grant(lifecycle_session_factory)
    async with lifecycle_session_factory() as session:
        await _service(session).prepare_file_delete(
            tenant_id=1,
            space_id=10,
            file_ids=[11],
            operator_id=7,
            operator_name="管理员",
        )
        await session.rollback()

    async with lifecycle_session_factory() as session:
        assert await session.get(KnowledgeFile, 11) is not None
        grant = (await session.exec(select(DepartmentFileViewGrant))).one()
        assert grant.status == DepartmentFileViewGrantStatus.ACTIVE
        assert (await session.exec(select(AuditLog))).all() == []


@pytest.mark.asyncio
async def test_department_rebind_invalidation_and_audit_share_transaction(
    lifecycle_session_factory,
) -> None:
    await _seed_file_and_grant(lifecycle_session_factory)
    async with lifecycle_session_factory() as session:
        await _service(session).prepare_department_rebind(
            tenant_id=1,
            space_id=10,
            old_department_id=12,
            new_department_id=13,
            operator_id=7,
            operator_name="管理员",
        )
        await session.commit()

    async with lifecycle_session_factory() as session:
        grant = (await session.exec(select(DepartmentFileViewGrant))).one()
        audit = (await session.exec(select(AuditLog))).one()
        assert grant.status == DepartmentFileViewGrantStatus.INVALIDATED
        assert grant.invalidated_reason == "department_rebound"
        assert audit.reason == "department_rebound"
        assert audit.audit_metadata["department_id"] == 12


@pytest.mark.asyncio
async def test_department_rebind_failure_rolls_back_grant_and_audit(
    lifecycle_session_factory,
) -> None:
    await _seed_file_and_grant(lifecycle_session_factory)
    async with lifecycle_session_factory() as session:
        await _service(session).prepare_department_rebind(
            tenant_id=1,
            space_id=10,
            old_department_id=12,
            new_department_id=13,
            operator_id=7,
            operator_name="管理员",
        )
        await session.rollback()

    async with lifecycle_session_factory() as session:
        grant = (await session.exec(select(DepartmentFileViewGrant))).one()
        assert grant.status == DepartmentFileViewGrantStatus.ACTIVE
        assert (await session.exec(select(AuditLog))).all() == []


@pytest.mark.asyncio
async def test_revoke_and_reactivate_persist_transition_audits_atomically(
    lifecycle_session_factory,
) -> None:
    await _seed_file_and_grant(lifecycle_session_factory)
    async with lifecycle_session_factory() as session:
        repository = DepartmentFileViewGrantRepositoryImpl(session)
        grant = await repository.revoke(
            tenant_id=1,
            user_id=9,
            space_id=10,
            file_id=11,
            approval_instance_id=109,
            revoked_by=7,
            reason="权限回收",
        )
        assert grant is not None
        DepartmentFileViewGrantAuditWriter(session).add_transition(
            grant=grant,
            operator_id=7,
            operator_name="管理员",
            action="approval.department_file_view.grant.revoke",
            old_status="active",
            new_status=grant.status,
            reason="权限回收",
        )
        await session.commit()

    async with lifecycle_session_factory() as session:
        repository = DepartmentFileViewGrantRepositoryImpl(session)
        grant = await repository.activate(
            tenant_id=1,
            user_id=9,
            space_id=10,
            file_id=11,
            department_id=12,
            approval_instance_id=209,
        )
        DepartmentFileViewGrantAuditWriter(session).add_transition(
            grant=grant,
            operator_id=0,
            operator_name="system",
            action="approval.department_file_view.grant.activate",
            old_status="revoked",
            new_status=grant.status,
            reason="approval_handler",
        )
        await session.commit()

    async with lifecycle_session_factory() as session:
        grant = (await session.exec(select(DepartmentFileViewGrant))).one()
        audits = (await session.exec(select(AuditLog).order_by(AuditLog.create_time))).all()
        assert grant.status == DepartmentFileViewGrantStatus.ACTIVE
        assert grant.approval_instance_id == 209
        assert grant.revoked_at is None
        assert grant.revoked_by is None
        assert grant.revoked_reason is None
        assert [(audit.audit_metadata["old_status"], audit.audit_metadata["new_status"]) for audit in audits] == [
            ("active", "revoked"),
            ("revoked", "active"),
        ]


@pytest.mark.asyncio
async def test_delete_coordinator_commits_prepared_lifecycle_transaction() -> None:
    transaction_session = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    lifecycle = SimpleNamespace(
        session=transaction_session,
        prepare_file_delete=AsyncMock(),
    )
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name="管理员")
    service.department_file_view_lifecycle_service = lifecycle

    await service._delete_file_rows_with_department_grants(
        space_id=10,
        tenant_id=1,
        file_ids=[11, 11, 12],
    )

    lifecycle.prepare_file_delete.assert_awaited_once_with(
        tenant_id=1,
        space_id=10,
        file_ids=[11, 12],
        operator_id=7,
        operator_name="管理员",
    )
    transaction_session.commit.assert_awaited_once()
    transaction_session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_coordinator_rolls_back_failed_lifecycle_transaction() -> None:
    transaction_session = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    lifecycle = SimpleNamespace(
        session=transaction_session,
        prepare_file_delete=AsyncMock(side_effect=RuntimeError("write failed")),
    )
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name="管理员")
    service.department_file_view_lifecycle_service = lifecycle

    with pytest.raises(RuntimeError, match="write failed"):
        await service._delete_file_rows_with_department_grants(
            space_id=10,
            tenant_id=1,
            file_ids=[11],
        )

    transaction_session.commit.assert_not_awaited()
    transaction_session.rollback.assert_awaited_once()
