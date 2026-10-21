"""Only an attested department binding may use the owner-reconciliation port."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeContainerPermissionAdapter,
    KnowledgeContainerPermissionRecord,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", [None, SimpleNamespace(tenant_id=8, admin_user_id=6)])
async def test_non_department_or_foreign_binding_cannot_rebind_creator(binding):
    permission = SimpleNamespace(sync_business_owner=AsyncMock())
    record = KnowledgeContainerPermissionRecord(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="42",
        status="PUBLISHED",
        kind="SPACE",
        owner_user_id=1,
        permission_version=4,
        context_version="ctx",
    )
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=SimpleNamespace(load_permission_record=AsyncMock(return_value=record)),
        permission=permission,
    )
    with patch(
        "bisheng.knowledge.domain.services.knowledge_permission_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
        new=AsyncMock(return_value=binding),
    ):
        with pytest.raises(PermissionInvalidResourceError):
            await adapter.sync_department_owner(resource_id="42", operator_user_id=2)
    permission.sync_business_owner.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("admin_id", [None, 6])
async def test_owner_comes_from_binding_not_operator_or_audit_creator(admin_id):
    permission = SimpleNamespace(sync_business_owner=AsyncMock())
    record = KnowledgeContainerPermissionRecord(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="42",
        status="PUBLISHED",
        kind="SPACE",
        owner_user_id=1,
        permission_version=4,
        context_version="ctx",
    )
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=SimpleNamespace(load_permission_record=AsyncMock(return_value=record)),
        permission=permission,
    )
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_permission_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(tenant_id=7, admin_user_id=admin_id)),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_permission_service.UserTenantDao.aget_user_tenants",
            new=AsyncMock(return_value=[SimpleNamespace(tenant_id=7, status="active", is_active=1)]),
        ),
    ):
        await adapter.sync_department_owner(resource_id="42", operator_user_id=2)
    assert permission.sync_business_owner.await_args.kwargs["owner_user_id"] == admin_id
    assert permission.sync_business_owner.await_args.kwargs["actor"].user_id == 2


@pytest.mark.parametrize(
    "tenant_rows",
    [
        [],
        [SimpleNamespace(tenant_id=8, status="active", is_active=1)],
        [SimpleNamespace(tenant_id=7, status="inactive", is_active=1)],
        [SimpleNamespace(tenant_id=7, status="active", is_active=0)],
    ],
)
async def test_inactive_or_foreign_owner_is_rejected_before_permission_write(tenant_rows):
    permission = SimpleNamespace(sync_business_owner=AsyncMock())
    record = KnowledgeContainerPermissionRecord(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="42",
        status="PUBLISHED",
        kind="SPACE",
        owner_user_id=1,
        permission_version=4,
        context_version="ctx",
    )
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=SimpleNamespace(load_permission_record=AsyncMock(return_value=record)),
        permission=permission,
    )
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_permission_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(tenant_id=7, admin_user_id=6)),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_permission_service.UserTenantDao.aget_user_tenants",
            new=AsyncMock(return_value=tenant_rows),
        ),
    ):
        with pytest.raises(PermissionInvalidResourceError):
            await adapter.sync_department_owner(resource_id="42", operator_user_id=2)
    permission.sync_business_owner.assert_not_awaited()
