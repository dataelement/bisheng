"""Department spaces use business tenants with the proven physical directory."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.department import DepartmentPermissionDeniedError
from bisheng.common.request_scope import admitted_request_scope
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    tenant_execution_scope,
    visible_tenant_ids,
)
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpace,
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    DepartmentKnowledgeSpaceBatchCreateReq,
    DepartmentKnowledgeSpaceBatchItem,
    DepartmentKnowledgeSpaceVisibilityReq,
)
from bisheng.knowledge.domain.services import department_knowledge_space_service as module
from test.department.test_management_directory_scope import directory_db as directory_db
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


@pytest.mark.parametrize("home,super_admin", [(1, True), (2, False)])
async def test_department_creation_uses_selected_business_tenant(directory_db, monkeypatch, home, super_admin):
    await directory_db.create(DepartmentKnowledgeSpace)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.department_knowledge_space.get_async_db_session", directory_db.sessions
    )
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=True))
    user = UserPayload(user_id=191, tenant_id=home, user_role=[], is_global_super=super_admin)
    writes = []

    async def create(self, **kwargs):
        writes.append(get_current_tenant_id())
        return SimpleNamespace(id=101)

    monkeypatch.setattr(module.KnowledgeSpaceService, "create_knowledge_space", create)
    monkeypatch.setattr(module.KnowledgeSpaceService, "get_space_info", AsyncMock(return_value=SimpleNamespace(id=101)))
    monkeypatch.setattr(module.DepartmentKnowledgeSpaceService, "_grant_department_members_viewer", AsyncMock())
    monkeypatch.setattr(module.DepartmentKnowledgeSpaceService, "_grant_default_department_admins", AsyncMock())
    storage_contexts = []

    async def admins(*args):
        storage_contexts.append(get_current_tenant_id())
        return []

    monkeypatch.setattr(module.DepartmentService, "aget_admins", admins)
    token = admitted_request_scope.set(SimpleNamespace(kind="tenant", tenant_id=2))
    try:
        with tenant_execution_scope(2):
            rows = await module.DepartmentKnowledgeSpaceService.batch_create_spaces(
                request=None,
                login_user=user,
                req=DepartmentKnowledgeSpaceBatchCreateReq(items=[DepartmentKnowledgeSpaceBatchItem(department_id=20)]),
            )
            binding = await DepartmentKnowledgeSpaceDao.aget_by_department_id(20)
            assert rows[0].id == 101
            assert binding.tenant_id == 2 and binding.created_by == 191
            assert writes == [2] and storage_contexts == [1]
            assert get_current_tenant_id() == 2 and user.tenant_id == home
            with pytest.raises(DepartmentPermissionDeniedError):
                await module.DepartmentKnowledgeSpaceService._load_departments([40])
    finally:
        admitted_request_scope.reset(token)


async def test_child_hide_cannot_update_root_or_other_tenant_bindings(directory_db, monkeypatch):
    from sqlmodel import select

    await directory_db.create(DepartmentKnowledgeSpace)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.department_knowledge_space.get_async_db_session", directory_db.sessions
    )
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=True))
    for tenant, dept, space in [(1, 10, 101), (2, 20, 102), (3, 40, 103)]:
        with tenant_execution_scope(tenant):
            await DepartmentKnowledgeSpaceDao.acreate(
                tenant_id=tenant, department_id=dept, space_id=space, created_by=191
            )
    with tenant_execution_scope(2):
        token = visible_tenant_ids.set(frozenset({1, 2}))
        try:
            changed = await module.DepartmentKnowledgeSpaceService.set_spaces_hidden(
                login_user=UserPayload(user_id=7, tenant_id=2, user_role=[]),
                req=DepartmentKnowledgeSpaceVisibilityReq(department_ids=[10, 20, 40], is_hidden=True),
            )
            assert changed == 1
        finally:
            visible_tenant_ids.reset(token)
    with bypass_tenant_filter():
        async with directory_db.sessions() as session:
            rows = (await session.exec(select(DepartmentKnowledgeSpace))).all()
            assert {row.tenant_id: row.is_hidden for row in rows} == {1: False, 2: True, 3: False}
