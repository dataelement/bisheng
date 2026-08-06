from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.domain.models.grant_subject_user import (
    GrantSubjectDepartment,
    GrantSubjectUserCandidate,
    GrantSubjectUserDepartmentLink,
)
from bisheng.permission.domain.services.grant_subject_user_service import GrantSubjectUserService


@pytest.fixture
def repository():
    return SimpleNamespace(
        list_visible_departments=AsyncMock(
            return_value=[
                GrantSubjectDepartment(
                    department_id=10,
                    dept_id="BS@10",
                    name="默认组织",
                    parent_id=None,
                    path="/10/",
                ),
                GrantSubjectDepartment(
                    department_id=11,
                    dept_id="BS@11",
                    name="研发部",
                    parent_id=10,
                    path="/10/11/",
                ),
                GrantSubjectDepartment(
                    department_id=12,
                    dept_id="BS@12",
                    name="项目组",
                    parent_id=10,
                    path="/10/12/",
                ),
            ]
        ),
        list_candidates=AsyncMock(
            return_value=[
                GrantSubjectUserCandidate(
                    user_id=7,
                    user_name="Alice",
                    external_id="EMP007",
                )
            ]
        ),
        list_department_links=AsyncMock(
            return_value=[
                GrantSubjectUserDepartmentLink(user_id=7, department_id=11, is_primary=True),
                GrantSubjectUserDepartmentLink(user_id=7, department_id=12, is_primary=False),
            ]
        ),
    )


@pytest.mark.asyncio
async def test_service_returns_all_visible_department_memberships(repository):
    result = await GrantSubjectUserService(repository).list_users(
        tenant_id=3,
        keyword="Ali",
        page=2,
        page_size=20,
    )

    assert result == [
        {
            "user_id": 7,
            "user_name": "Alice",
            "external_id": "EMP007",
            "primary_department_path": "默认组织/研发部",
            "department_paths": ["默认组织/研发部", "默认组织/项目组"],
            "department_memberships": [
                {
                    "department_id": 11,
                    "dept_id": "BS@11",
                    "name": "研发部",
                    "path": "默认组织/研发部",
                    "is_primary": True,
                },
                {
                    "department_id": 12,
                    "dept_id": "BS@12",
                    "name": "项目组",
                    "path": "默认组织/项目组",
                    "is_primary": False,
                },
            ],
        }
    ]
    repository.list_candidates.assert_awaited_once_with(
        tenant_id=3,
        visible_department_ids=(10, 11, 12),
        keyword="Ali",
        page=2,
        page_size=20,
        department_id=None,
        unassigned=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("department_id", "unassigned"),
    [(11, False), (None, True)],
)
async def test_service_forwards_direct_department_and_unassigned_filters(
    repository,
    department_id,
    unassigned,
):
    await GrantSubjectUserService(repository).list_users(
        tenant_id=3,
        keyword="",
        page=1,
        page_size=50,
        department_id=department_id,
        unassigned=unassigned,
    )

    repository.list_candidates.assert_awaited_once_with(
        tenant_id=3,
        visible_department_ids=(10, 11, 12),
        keyword="",
        page=1,
        page_size=50,
        department_id=department_id,
        unassigned=unassigned,
    )


@pytest.mark.asyncio
async def test_service_rejects_mutually_exclusive_filters(repository):
    with pytest.raises(ValueError, match="department_id and unassigned"):
        await GrantSubjectUserService(repository).list_users(
            tenant_id=3,
            keyword="",
            page=1,
            page_size=50,
            department_id=11,
            unassigned=True,
        )

    repository.list_candidates.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_does_not_expose_an_out_of_scope_department(repository):
    result = await GrantSubjectUserService(repository).list_users(
        tenant_id=3,
        keyword="",
        page=1,
        page_size=50,
        department_id=999,
    )

    assert result == []
    repository.list_candidates.assert_not_awaited()

