"""Deletion preflights follow the same administrator scope as space listings."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.folder_deletion import RESERVED_KEY, make_marker
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
from bisheng.permission.application.identity import current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor


@pytest.fixture
async def deletion_visibility():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                model.__table__
                for model in (
                    KnowledgeFile,
                    KnowledgeSpaceFileChangeRequest,
                    KnowledgeSpaceFileChangeFootprint,
                    KnowledgeSpaceFileChangeExecutionStep,
                )
            ],
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    tenant_token = set_current_tenant_id(42)
    actor_token = current_permission_actor.set(None)
    try:
        async with sessions() as session, session.begin():
            for resource_id, tenant_id, space_id, file_type, path in (
                (41, 42, 7, 0, ""),
                (42, 42, 7, 0, ""),
                (43, 42, 7, 1, "/42"),
                (44, 43, 7, 0, ""),
                (45, 42, 8, 0, ""),
            ):
                session.add(
                    KnowledgeFile(
                        id=resource_id,
                        tenant_id=tenant_id,
                        knowledge_id=space_id,
                        user_id=10,
                        file_name=f"resource-{resource_id}",
                        file_type=file_type,
                        file_level_path=path,
                        status=8 if resource_id == 42 else 2,
                        user_metadata={RESERVED_KEY: make_marker(str(uuid4()), 10, datetime.now(UTC))}
                        if resource_id == 42
                        else {},
                    )
                )
        owner = SimpleNamespace(
            login_user=SimpleNamespace(user_id=9, tenant_id=42, is_global_super=True),
            _load_space_listing_scope=AsyncMock(return_value=(SimpleNamespace(id=7, tenant_id=42), None)),
            _batch_actions=AsyncMock(return_value={"7": {"manage_permission"}}),
            _filter_visible_child_items=AsyncMock(return_value=[]),
        )
        yield KnowledgeFolderDeletionService(7, sessions), owner
    finally:
        current_permission_actor.reset(actor_token)
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


async def test_full_scope_super_admin_reads_normal_folder_status(deletion_visibility):
    service, owner = deletion_visibility
    current_permission_actor.set(PermissionActor(user_id=9, current_tenant_id=42, super_admin=True))
    (item,) = await service.query(owner, [41], {})
    assert item.state == "idle"


async def test_full_scope_super_admin_still_observes_active_deleting_ancestor(deletion_visibility):
    service, owner = deletion_visibility
    current_permission_actor.set(PermissionActor(user_id=9, current_tenant_id=42, super_admin=True))
    (item,) = await service.query(owner, [43], {})
    assert item.state == "running"
    assert item.operation_id is None


@pytest.mark.parametrize(
    "super_admin,data_scope",
    [
        (False, DATA_SCOPE_ALL),
        (True, DATA_SCOPE_PERSONAL),
        (False, DATA_SCOPE_PERSONAL),
    ],
)
async def test_non_system_scopes_keep_resource_visibility_checks(deletion_visibility, super_admin, data_scope):
    service, owner = deletion_visibility
    owner.login_user.is_global_super = super_admin
    current_permission_actor.set(
        PermissionActor(
            user_id=9,
            current_tenant_id=42,
            super_admin=super_admin,
            data_scope=data_scope,
        )
    )
    (item,) = await service.query(owner, [41], {})
    assert item.state == "unavailable"


async def test_full_scope_super_admin_cannot_query_other_tenant_or_space(deletion_visibility):
    service, owner = deletion_visibility
    current_permission_actor.set(PermissionActor(user_id=9, current_tenant_id=42, super_admin=True))
    items = await service.query(owner, [44, 45], {})
    assert all(item.state not in {"idle", "running"} and item.operation_id is None for item in items)


@pytest.mark.parametrize("super_admin,expected_anchor", [(True, 42), (False, 43)])
async def test_page_projection_only_exposes_visible_deletion_anchors(deletion_visibility, super_admin, expected_anchor):
    service, owner = deletion_visibility
    owner.login_user.is_global_super = super_admin
    current_permission_actor.set(PermissionActor(user_id=9, current_tenant_id=42, super_admin=super_admin))
    async with service.sessions() as session:
        file = await session.get(KnowledgeFile, 43)
    items = [{}]
    await service.project_page([file], items, None, owner=owner, space=SimpleNamespace(id=7, tenant_id=42))
    status = items[0]["deletion_status"]
    assert status["state"] == "running"
    assert status["root_folder_id"] == expected_anchor
    assert (status["operation_id"] is not None) is super_admin
