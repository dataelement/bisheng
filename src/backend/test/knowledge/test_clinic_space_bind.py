"""科室库绑定校验：只能绑授权子树内的 office。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpaceCreateDepartmentDeniedError
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
)
from bisheng.knowledge.domain.services.clinic_department_bind import CLINIC_BIND_DENIED_MSG
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _login_user(*, is_admin: bool = False):
    return SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: is_admin, user_name="tester")


def _dept(dept_id: int, *, org_level: str | None, path: str, status: str = "active"):
    return SimpleNamespace(
        id=dept_id,
        status=status,
        org_level=org_level,
        path=path,
        is_deleted=0,
    )


@pytest.mark.asyncio
async def test_create_clinic_rejects_non_office_department() -> None:
    svc = KnowledgeSpaceService(request=None, login_user=_login_user(is_admin=True))
    dept = _dept(2, org_level="dept", path="/1/2/")

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id",
        new=AsyncMock(return_value=dept),
    ):
        with pytest.raises(SpaceCreateDepartmentDeniedError) as exc:
            await svc._resolve_space_scope_on_create(
                space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                department_id=2,
                user_group_id=None,
                is_clinic=True,
            )
    assert CLINIC_BIND_DENIED_MSG in str(exc.value.message)


@pytest.mark.asyncio
async def test_create_clinic_rejects_office_outside_admin_grant() -> None:
    svc = KnowledgeSpaceService(request=None, login_user=_login_user())
    dept = _dept(1, org_level="dept", path="/1/")
    granted_office = _dept(2, org_level="office", path="/1/2/")
    office = _dept(4, org_level="office", path="/3/4/")

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id",
            new=AsyncMock(return_value=office),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=[1]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=[dept, granted_office, office]),
        ),
    ):
        with pytest.raises(SpaceCreateDepartmentDeniedError):
            await svc._resolve_space_scope_on_create(
                space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                department_id=4,
                user_group_id=None,
                is_clinic=True,
            )


@pytest.mark.asyncio
async def test_create_clinic_allows_office_in_admin_grant_subtree() -> None:
    svc = KnowledgeSpaceService(request=None, login_user=_login_user())
    dept = _dept(1, org_level="dept", path="/1/")
    office = _dept(2, org_level="office", path="/1/2/")

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id",
            new=AsyncMock(return_value=office),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentAdminGrantDao.aget_department_ids_by_user_id",
            new=AsyncMock(return_value=[1]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_active_by_tenant",
            new=AsyncMock(return_value=[dept, office]),
        ),
    ):
        level, owner_type, owner_id = await svc._resolve_space_scope_on_create(
            space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
            department_id=2,
            user_group_id=None,
            is_clinic=True,
        )

    assert level == KnowledgeSpaceLevelEnum.TEAM_KS
    assert owner_type == KnowledgeSpaceOwnerTypeEnum.USER
    assert owner_id == 7
