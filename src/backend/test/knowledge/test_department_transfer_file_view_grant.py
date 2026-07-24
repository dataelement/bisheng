from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.department_file_view_grant import (
    DepartmentFileViewGrant,
    DepartmentFileViewGrantStatus,
)
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)


@pytest_asyncio.fixture
async def grant_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: SQLModel.metadata.create_all(
                sync_connection,
                tables=[DepartmentFileViewGrant.__table__],
            )
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_invalidation_does_not_revoke_reactivated_grant(grant_session):
    granted_at = datetime(2026, 7, 24, 9, 0, 0)
    grant = DepartmentFileViewGrant(
        tenant_id=1,
        user_id=7,
        space_id=100,
        file_id=301,
        department_id=10,
        approval_instance_id=5001,
        granted_at=granted_at,
    )
    grant_session.add(grant)
    await grant_session.commit()
    await grant_session.refresh(grant)
    repository = DepartmentFileViewGrantRepositoryImpl(grant_session)

    reactivated = await repository.activate(
        tenant_id=1,
        user_id=7,
        space_id=100,
        file_id=301,
        department_id=20,
        approval_instance_id=5002,
    )
    await grant_session.commit()

    invalidated = await repository.invalidate_snapshot_grant(
        tenant_id=1,
        grant_id=int(reactivated.id),
        user_id=7,
        expected_approval_instance_id=5001,
        expected_granted_at=granted_at,
        reason="primary_department_changed:70",
    )

    assert invalidated is None
    assert reactivated.status == DepartmentFileViewGrantStatus.ACTIVE
    assert reactivated.approval_instance_id == 5002


@pytest.mark.asyncio
async def test_snapshot_invalidation_records_event_reason(grant_session):
    granted_at = datetime.now() - timedelta(minutes=2)
    grant = DepartmentFileViewGrant(
        tenant_id=1,
        user_id=7,
        space_id=100,
        file_id=301,
        department_id=10,
        approval_instance_id=5001,
        granted_at=granted_at,
    )
    grant_session.add(grant)
    await grant_session.commit()
    await grant_session.refresh(grant)
    repository = DepartmentFileViewGrantRepositoryImpl(grant_session)

    invalidated = await repository.invalidate_snapshot_grant(
        tenant_id=1,
        grant_id=int(grant.id),
        user_id=7,
        expected_approval_instance_id=5001,
        expected_granted_at=granted_at,
        reason="primary_department_changed:71",
    )

    assert invalidated is grant
    assert grant.status == DepartmentFileViewGrantStatus.INVALIDATED
    assert grant.invalidated_reason == "primary_department_changed:71"


@pytest.mark.asyncio
async def test_approval_protects_post_transfer_grant_before_activation(monkeypatch):
    from bisheng.approval.domain.services import department_file_view_handler as module
    from bisheng.approval.domain.services.department_file_view_handler import (
        DepartmentFileViewApprovalHandler,
    )
    from bisheng.permission.domain.services import (
        department_transfer_grant_guard as guard_module,
    )

    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    @asynccontextmanager
    async def session_factory():
        yield session

    file = SimpleNamespace(id=301, knowledge_id=100)
    grant = SimpleNamespace(id=91, status=DepartmentFileViewGrantStatus.ACTIVE)
    call_order: list[str] = []

    async def activate_grant(**_kwargs):
        call_order.append("activate")
        return grant

    async def protect_grant(**_kwargs):
        call_order.append("protect")

    grant_repository = SimpleNamespace(
        activate=AsyncMock(side_effect=activate_grant),
    )
    protect = AsyncMock(side_effect=protect_grant)
    add_transition = Mock()
    monkeypatch.setattr(module, "get_async_db_session", session_factory)
    monkeypatch.setattr(
        module,
        "KnowledgeFileRepositoryImpl",
        lambda _session: SimpleNamespace(
            find_by_id_for_update=AsyncMock(return_value=file),
        ),
    )
    monkeypatch.setattr(
        module,
        "DepartmentFileViewGrantRepositoryImpl",
        lambda _session: grant_repository,
    )
    monkeypatch.setattr(
        module,
        "DepartmentFileViewAccessService",
        lambda **_kwargs: SimpleNamespace(
            load_resource=AsyncMock(
                return_value=SimpleNamespace(valid=True, department_id=10),
            ),
        ),
    )
    monkeypatch.setattr(
        module,
        "DepartmentFileViewGrantAuditWriter",
        lambda _session: SimpleNamespace(add_transition=add_transition),
    )
    monkeypatch.setattr(
        guard_module,
        "protect_department_file_grant",
        protect,
    )

    result = await DepartmentFileViewApprovalHandler().on_approved(
        5002,
        {
            "tenant_id": 1,
            "applicant_user_id": 7,
            "space_id": 100,
            "file_id": 301,
            "department_id": 10,
        },
    )

    protect.assert_awaited_once_with(
        user_id=7,
        space_id=100,
        file_id=301,
        approval_instance_id=5002,
    )
    grant_repository.activate.assert_awaited_once()
    assert call_order == ["protect", "activate"]
    session.commit.assert_awaited_once()
    assert result == {"status": DepartmentFileViewGrantStatus.ACTIVE, "grant_id": 91}
